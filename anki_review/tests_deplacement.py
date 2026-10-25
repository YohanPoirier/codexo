from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from . import decks as gestion
from .models import Card, Deck, Note, SuggestionDeplacement

CONFIG = dict(
    PAS_A_PAS_ELEVES=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)


def eleve(nom):
    u = User.objects.create_user(nom, "mdp-test-solide-1", role=User.ELEVE)
    u.a_vu_intro_pas_a_pas = True
    u.save()
    return u


def carte(deck, proprietaire, texte, partagee=False, detenteurs=()):
    note = Note.objects.create(
        deck=deck, question=texte, reponse="R", cree_par=proprietaire, partagee_avec_classe=partagee)
    for u in (proprietaire, *detenteurs):
        Card.objects.get_or_create(note=note, etudiant=u)
    return note


@override_settings(**CONFIG)
class DeplacementTests(TestCase):
    """Scénario : A et B ont écrit chacun un paquet « Vocabulaire », C a ajouté des cartes à celui de B."""

    def setUp(self):
        self.a, self.b, self.c = eleve("A-dep"), eleve("B-dep"), eleve("C-dep")
        self.deck_a = Deck.objects.create(nom="Vocabulaire A", slug="vocabulaire-a", cree_par=self.a)
        self.deck_b = Deck.objects.create(nom="Vocabulaire B", slug="vocabulaire-b", cree_par=self.b)
        self.a1 = carte(self.deck_a, self.a, "dog", partagee=True)
        self.a2 = carte(self.deck_a, self.a, "cat")
        self.b1 = carte(self.deck_b, self.b, "house", partagee=True)
        self.b2 = carte(self.deck_b, self.b, "tree", detenteurs=())
        self.c1 = carte(self.deck_b, self.c, "sun")  # C a ajouté une carte dans le paquet de B
        self.url_b = reverse("anki_review:deplacer_cartes", args=[self.deck_b.id])

    def _deplacer(self, utilisateur, source, destination):
        self.client.force_login(utilisateur)
        return self.client.post(
            reverse("anki_review:deplacer_cartes", args=[source.id]), {"destination": destination.id})

    # ---- le déplacement lui-même
    def test_les_cartes_de_b_changent_de_paquet_sans_etre_copiees(self):
        nb_notes, nb_cartes = Note.objects.count(), Card.objects.count()
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertEqual(Note.objects.count(), nb_notes)
        self.assertEqual(Card.objects.count(), nb_cartes)
        for note in (self.b1, self.b2):
            note.refresh_from_db()
            self.assertEqual(note.deck, self.deck_a)
            self.assertEqual(note.cree_par, self.b)
        self.b1.refresh_from_db()
        self.assertTrue(self.b1.partagee_avec_classe)  # le partage suit

    def test_la_progression_suit_la_carte(self):
        Card.objects.filter(note=self.b1, etudiant=self.b).update(repetitions=7)
        Card.objects.create(note=self.b1, etudiant=self.a, repetitions=3)  # A l'avait récupérée
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertEqual(Card.objects.get(note=self.b1, etudiant=self.b).repetitions, 7)
        self.assertEqual(Card.objects.get(note=self.b1, etudiant=self.a).repetitions, 3)

    def test_les_cartes_de_c_ne_bougent_pas_et_le_paquet_lui_est_transmis(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.c1.refresh_from_db()
        self.deck_b.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_b)
        self.assertEqual(self.deck_b.cree_par, self.c)  # B n'y a plus rien : paquet transmis à C

    def test_paquet_vide_et_cree_par_celui_qui_demenage_est_supprime(self):
        Note.objects.filter(pk=self.c1.pk).delete()
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertFalse(Deck.objects.filter(pk=self.deck_b.pk).exists())

    def test_cartes_recuperees_chez_d_autres_ne_sont_pas_deplacees(self):
        Card.objects.create(note=self.c1, etudiant=self.b)  # B a récupéré la carte de C
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_b)
        self.deck_b.refresh_from_db()
        self.assertEqual(self.deck_b.cree_par, self.b)  # B y a encore une carte : il reste propriétaire

    def test_carte_miroir_suit(self):
        miroir = Note.objects.create(deck=self.deck_b, question="R", reponse="tree", cree_par=self.b)
        Note.objects.filter(pk=self.b2.pk).update(note_miroir=miroir)
        Note.objects.filter(pk=miroir.pk).update(note_miroir=self.b2)
        self._deplacer(self.b, self.deck_b, self.deck_a)
        miroir.refresh_from_db()
        self.assertEqual(miroir.deck, self.deck_a)

    def test_destination_interdite_refusee(self):
        prive = Deck.objects.create(nom="Privé", slug="prive", cree_par=self.a)
        carte(prive, self.a, "secret")  # privé, non partagé
        self._deplacer(self.b, self.deck_b, prive)
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.deck, self.deck_b)

    def test_meme_paquet_et_paquet_sans_carte_a_soi(self):
        self.client.force_login(self.b)
        self.client.post(self.url_b, {"destination": self.deck_b.id})
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.deck, self.deck_b)
        # D n'a aucune carte à lui dans le paquet de B
        d = eleve("D-dep")
        self.client.force_login(d)
        self.assertEqual(self.client.get(self.url_b).status_code, 302)

    def test_page_de_choix(self):
        self.client.force_login(self.b)
        html = self.client.get(self.url_b).content.decode()
        self.assertIn("Vocabulaire A", html)  # destinations : paquets où il peut ajouter
        self.assertNotIn('<option value="%d">' % self.deck_b.id, html)

    def test_page_de_choix_introuvable_pour_un_paquet_invisible(self):
        prive = Deck.objects.create(nom="Privé", slug="prive", cree_par=self.a)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("anki_review:deplacer_cartes", args=[prive.id])).status_code, 404)

    def test_bouton_dans_l_edition(self):
        self.client.force_login(self.b)
        html = self.client.get(reverse("anki_review:edition")).content.decode()
        self.assertIn(self.url_b, html)

    # ---- suggestion aux autres
    def test_c_recoit_une_suggestion(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        self.assertEqual((s.destinataire, s.auteur, s.ancien_deck, s.nouveau_deck), (self.c, self.b, self.deck_b, self.deck_a))
        self.assertEqual(s.statut, SuggestionDeplacement.Statut.EN_ATTENTE)

    def test_pas_de_suggestion_a_celui_qui_deplace_ni_aux_autres_paquets(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertFalse(SuggestionDeplacement.objects.filter(destinataire=self.b).exists())
        self.assertFalse(SuggestionDeplacement.objects.filter(destinataire=self.a).exists())

    def test_pas_de_suggestion_si_la_destination_est_interdite_au_destinataire(self):
        # C ne peut pas ajouter dans le paquet privé de A (rien n'y est partagé)
        Note.objects.filter(deck=self.deck_a).update(partagee_avec_classe=False)
        Note.objects.filter(pk=self.b1.pk).update(partagee_avec_classe=False)  # rien de partagé non plus
        Deck.objects.filter(pk=self.deck_a.pk).update(cree_par=self.b)  # B peut y écrire (le sien)
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertFalse(SuggestionDeplacement.objects.exists())

    def test_jamais_de_suggestion_depuis_un_paquet_officiel_ni_aux_professeurs(self):
        prof = User.objects.create_user("prof-dep", "mdp-test-solide-1", role=User.PROF)
        officiel = Deck.objects.create(nom="Officiel", slug="officiel", cree_par=prof)
        carte(officiel, prof, "officielle", partagee=True)
        carte(officiel, self.b, "à B")
        self._deplacer(self.b, officiel, self.deck_a)
        self.assertFalse(SuggestionDeplacement.objects.exists())

    def test_pas_de_doublon_et_un_refus_n_est_pas_redemande(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        SuggestionDeplacement.objects.filter(pk=s.pk).update(statut=SuggestionDeplacement.Statut.REFUSEE)
        carte(self.deck_b, self.b, "encore une")
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.assertEqual(SuggestionDeplacement.objects.count(), 1)
        self.assertEqual(SuggestionDeplacement.objects.get().statut, SuggestionDeplacement.Statut.REFUSEE)

    def test_bandeau_sur_l_accueil_de_c(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        self.client.force_login(self.c)
        html = self.client.get(reverse("anki_review:liste_decks")).content.decode()
        self.assertIn("a déplacé ses cartes", html)
        self.assertIn("Vocabulaire B", html)
        self.assertIn("Vocabulaire A", html)
        self.client.force_login(self.a)
        self.assertNotIn("a déplacé ses cartes", self.client.get(reverse("anki_review:liste_decks")).content.decode())

    def test_c_accepte(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        self.client.force_login(self.c)
        self.client.post(reverse("anki_review:accepter_deplacement", args=[s.id]))
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_a)
        self.assertFalse(Deck.objects.filter(pk=self.deck_b.pk).exists())  # plus rien dedans : disparu
        # la suggestion a disparu avec l'ancien paquet : en tout cas plus rien n'est en attente
        self.assertFalse(SuggestionDeplacement.objects.filter(
            statut=SuggestionDeplacement.Statut.EN_ATTENTE).exists())

    def test_c_accepte_alors_que_le_paquet_survit(self):
        e = eleve("E-dep")
        carte(self.deck_b, e, "moon")  # E garde une carte à elle dans l'ancien paquet
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get(destinataire=self.c)
        self.client.force_login(self.c)
        self.client.post(reverse("anki_review:accepter_deplacement", args=[s.id]))
        s.refresh_from_db()
        self.assertEqual(s.statut, SuggestionDeplacement.Statut.ACCEPTEE)
        self.assertTrue(Deck.objects.filter(pk=self.deck_b.pk).exists())
        self.deck_b.refresh_from_db()
        self.assertEqual(self.deck_b.cree_par, e)  # C n'y a plus de carte : le paquet passe à E

    def test_c_refuse_et_garde_ses_cartes(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        self.client.force_login(self.c)
        self.client.post(reverse("anki_review:refuser_deplacement", args=[s.id]))
        self.c1.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_b)
        self.assertEqual(s.statut, SuggestionDeplacement.Statut.REFUSEE)
        self.client.get(reverse("anki_review:liste_decks"))
        self.assertNotIn("a déplacé ses cartes",
                         self.client.get(reverse("anki_review:liste_decks")).content.decode())

    def test_personne_d_autre_ne_peut_traiter_la_suggestion_de_c(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        for autre in (self.a, self.b):
            self.client.force_login(autre)
            self.assertEqual(self.client.post(reverse("anki_review:accepter_deplacement", args=[s.id])).status_code, 404)
            self.assertEqual(self.client.post(reverse("anki_review:refuser_deplacement", args=[s.id])).status_code, 404)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_b)

    def test_accepter_une_suggestion_devenue_impossible_ne_plante_pas(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        Note.objects.filter(pk=self.c1.pk).delete()  # C n'a plus rien à déplacer
        self.client.force_login(self.c)
        r = self.client.post(reverse("anki_review:accepter_deplacement", args=[s.id]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("plus possible", r.content.decode())
        s.refresh_from_db()
        self.assertEqual(s.statut, SuggestionDeplacement.Statut.EN_ATTENTE)  # transaction annulée

    def test_get_n_accepte_rien(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        s = SuggestionDeplacement.objects.get()
        self.client.force_login(self.c)
        self.client.get(reverse("anki_review:accepter_deplacement", args=[s.id]))
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.deck, self.deck_b)

    def test_suggestion_sans_objet_si_c_n_a_plus_de_carte_a_deplacer(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        Note.objects.filter(pk=self.c1.pk).delete()
        self.assertEqual(gestion.suggestions_en_attente(self.c), [])

    def test_suggestion_sans_objet_si_la_destination_n_est_plus_permise(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        Note.objects.filter(deck=self.deck_a).update(partagee_avec_classe=False)  # plus rien de partagé
        Deck.objects.filter(pk=self.deck_a.pk).update(cree_par=self.b)
        self.assertEqual(gestion.suggestions_en_attente(self.c), [])

    def test_suggestion_supprimee_avec_le_paquet(self):
        self._deplacer(self.b, self.deck_b, self.deck_a)
        Deck.objects.filter(pk=self.deck_a.pk).delete()
        self.assertFalse(SuggestionDeplacement.objects.exists())

    # ---- notification
    def test_notification_envoyee_a_c_selon_son_reglage(self):
        from .models import PreferencesNotification
        with mock.patch("anki_review.notifications.configuration_ok", return_value=True), \
                mock.patch("anki_review.notifications.envoyer_message") as envoi, \
                mock.patch("anki_review.notifications.threading.Thread") as fil:
            fil.side_effect = lambda target, daemon=None: mock.Mock(start=target)
            self._deplacer(self.b, self.deck_b, self.deck_a)
        envoi.assert_called_once()
        destinataire, message = envoi.call_args.args
        self.assertEqual(destinataire, self.c)
        self.assertIn("Vocabulaire B", message["corps"])
        self.assertIn("Vocabulaire A", message["corps"])

        PreferencesNotification.objects.update_or_create(etudiant=self.c, defaults={"propositions": False})
        SuggestionDeplacement.objects.all().delete()
        carte(self.deck_b, self.b, "x")
        with mock.patch("anki_review.notifications.configuration_ok", return_value=True), \
                mock.patch("anki_review.notifications.envoyer_message") as envoi2, \
                mock.patch("anki_review.notifications.threading.Thread") as fil:
            fil.side_effect = lambda target, daemon=None: mock.Mock(start=target)
            self._deplacer(self.b, self.deck_b, self.deck_a)
        envoi2.assert_not_called()

    def test_connexion_exigee(self):
        r = self.client.post(self.url_b, {"destination": self.deck_a.id})
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)
