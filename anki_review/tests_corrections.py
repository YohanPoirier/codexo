"""Corrections issues de la revue du code (octobre 2026)."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Classe, User
from exercises.models import Exercise, Theme

from .models import Card, Deck, Note, PropositionModification

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


@override_settings(**CONFIG)
class RevisionTests(TestCase):
    def setUp(self):
        self.eleve = eleve("e-rev")
        self.deck = Deck.objects.create(nom="Optique", slug="optique")
        self.client.force_login(self.eleve)
        self.url = reverse("anki_review:reviser", args=["optique"])

    def _carte(self, q="Q"):
        note = Note.objects.create(deck=self.deck, question=q, reponse="R")
        return Card.objects.get(note=note, etudiant=self.eleve) if Card.objects.filter(
            note=note, etudiant=self.eleve).exists() else Card.objects.create(note=note, etudiant=self.eleve)

    def test_reponse_envoyee_deux_fois_ne_compte_qu_une_fois(self):
        carte = self._carte()
        version = carte.prochaine_revision.isoformat()
        donnees = {"carte_id": carte.id, "reponse": "good", "version": version}
        self.client.post(self.url, donnees)
        carte.refresh_from_db()
        apres_une = (carte.repetitions, carte.intervalle_jours, carte.prochaine_revision)
        self.client.post(self.url, donnees)  # double appui / requête rejouée
        carte.refresh_from_db()
        self.assertEqual((carte.repetitions, carte.intervalle_jours, carte.prochaine_revision), apres_une)

    def test_reponse_sans_version_toujours_acceptee(self):
        carte = self._carte()
        self.client.post(self.url, {"carte_id": carte.id, "reponse": "good"})
        carte.refresh_from_db()
        self.assertEqual(carte.repetitions, 1)

    def test_page_de_revision_porte_la_version(self):
        carte = self._carte()
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="version"', html)
        self.assertIn(carte.prochaine_revision.isoformat(), html)

    def test_recharger_la_page_ne_fait_pas_avancer_la_file_d_apprentissage(self):
        rate = self._carte("rate")
        self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        avant = self.client.session["anki_file_apprentissage"]
        for _ in range(4):
            self.client.get(self.url)
        self.assertEqual(self.client.session["anki_file_apprentissage"], avant)

    def test_repondre_a_une_carte_ordinaire_fait_avancer_les_cartes_ratees(self):
        rate = self._carte("rate")
        autre = self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        self.client.post(self.url, {"carte_id": autre.id, "reponse": "good"})
        entree = next(e for e in self.client.session["anki_file_apprentissage"] if e["id"] == rate.id)
        self.assertEqual(entree["n"], 1)

    def test_restantes_ne_compte_pas_deux_fois_une_carte_ratee_et_echue(self):
        rate = self._carte("rate")
        self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        Card.objects.filter(pk=rate.pk).update(prochaine_revision=timezone.now())  # échue ET en file
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["restantes"], 2)


@override_settings(**CONFIG)
class PropositionDejaTraiteeTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user("prof-t", "mdp-test-solide-1", role=User.PROF)
        self.auteur = eleve("e-prop")
        deck = Deck.objects.create(nom="D", slug="d", cree_par=self.prof)
        self.note = Note.objects.create(deck=deck, question="actuelle", reponse="R", cree_par=self.prof)
        self.prop = PropositionModification.objects.create(
            note=self.note, auteur=self.auteur, question="ancienne proposition", reponse="R", tags="")
        self.client.force_login(self.prof)

    def test_proposition_refusee_ne_peut_plus_etre_acceptee(self):
        self.client.post(reverse("anki_review:refuser_proposition", args=[self.prop.id]))
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        self.note.refresh_from_db()
        self.prop.refresh_from_db()
        self.assertEqual(self.note.question, "actuelle")
        self.assertEqual(self.prop.statut, PropositionModification.Statut.REFUSEE)

    def test_proposition_acceptee_ne_s_applique_qu_une_fois(self):
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        Note.objects.filter(pk=self.note.pk).update(question="modifiée depuis")
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        self.note.refresh_from_db()
        self.assertEqual(self.note.question, "modifiée depuis")


@override_settings(**CONFIG)
class ExercicesMasquesEtEnvoisTests(TestCase):
    def setUp(self):
        pcsi = Classe.objects.create(name="PCSI", slug="pcsi")
        psi = Classe.objects.create(name="PSI", slug="psi")
        self.theme = Theme.objects.create(name="T", slug="t")
        self.theme.enabled_for_classes.set([pcsi, psi])
        self.ex = Exercise.objects.create(
            theme=self.theme, title="E", slug="e", statement="x", function_name="f",
            solution_code="def f():\n    return 1\n")
        self.ex.enabled_for_classes.set([psi])  # réservé aux PSI
        self.pcsi = eleve("e-pcsi")
        self.pcsi.classe = pcsi
        self.pcsi.save()
        self.psi = eleve("e-psi")
        self.psi.classe = psi
        self.psi.save()

    def test_exercice_masque_ni_tests_ni_corrige(self):
        self.client.force_login(self.pcsi)
        self.assertEqual(self.client.get(reverse("exercise_tests", args=[self.ex.id])).status_code, 404)
        r = self.client.post(reverse("submit_result", args=[self.ex.id]),
                             {"code": "x", "success": "1"})
        self.assertEqual(r.status_code, 404)

    def test_exercice_ouvert_a_la_classe_fonctionne(self):
        self.client.force_login(self.psi)
        self.assertEqual(self.client.get(reverse("exercise_tests", args=[self.ex.id])).status_code, 200)

    def test_envois_mal_formes_donnent_400_et_pas_500(self):
        self.client.force_login(self.psi)
        url = reverse("submit_result", args=[self.ex.id])
        for corps in ("pas du json", "[1, 2]", '{"time_seconds": "abc"}', '{"code": 5}'):
            r = self.client.post(url, corps, content_type="application/json")
            self.assertEqual(r.status_code, 400, corps)
        r = self.client.post(url, {"code": "x", "time_seconds": "abc"})
        self.assertEqual(r.status_code, 400)
        ok = self.client.post(url, '{"code": "x", "success": true, "time_seconds": 3}',
                              content_type="application/json")
        self.assertEqual(ok.status_code, 200)


class RoleEtAccesTests(TestCase):
    def test_professeur_repasse_eleve_perd_is_staff(self):
        prof = User.objects.create_user("prof-r", "mdp-test-solide-1", role=User.PROF)
        self.assertTrue(prof.is_staff)
        prof.role = User.ELEVE
        prof.save()
        prof.refresh_from_db()
        self.assertFalse(prof.is_staff)

    def test_compte_technique_staff_sans_role_prof_garde_is_staff(self):
        technique = User.objects.create_user("tech-r", "mdp-test-solide-1", is_staff=True)
        technique.display_name = "Technique"
        technique.save()
        technique.refresh_from_db()
        self.assertTrue(technique.is_staff)

    def test_superuser_garde_ses_droits(self):
        admin = User.objects.create_superuser("adm-r", "mdp-test-solide-1")
        admin.role = User.ELEVE
        admin.save()
        admin.refresh_from_db()
        self.assertTrue(admin.is_staff and admin.is_superuser)


@override_settings(PAS_A_PAS_ELEVES=True, **{k: v for k, v in CONFIG.items() if k != "PAS_A_PAS_ELEVES"})
class IntroNeBloquePasAnkiTests(TestCase):
    def test_appli_anki_non_redirigee_vers_la_presentation(self):
        u = User.objects.create_user("e-intro", "mdp-test-solide-1", role=User.ELEVE)
        self.client.force_login(u)  # n'a pas encore vu la présentation
        reponse = self.client.get(reverse("anki_review:liste_decks"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.client.get(reverse("theme_list")).status_code, 302)  # le site, si


@override_settings(**CONFIG)
class CarteRecupereeGardeeTests(TestCase):
    """Un étudiant qui a récupéré une carte la garde, même si son propriétaire cesse de la partager."""

    def setUp(self):
        self.a, self.b = eleve("A-gardee"), eleve("B-gardee")
        self.deck = Deck.objects.create(nom="Paquet 1", slug="paquet-1", cree_par=self.a)
        self.note = Note.objects.create(
            deck=self.deck, question="Q", reponse="R", cree_par=self.a, partagee_avec_classe=True)
        Card.objects.create(note=self.note, etudiant=self.a)
        self.client.force_login(self.b)
        self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.note.id]))
        Note.objects.filter(pk=self.note.pk).update(partagee_avec_classe=False)  # A arrête de partager

    def test_paquet_et_carte_restent_accessibles_a_celui_qui_l_a_recuperee(self):
        html = self.client.get(reverse("anki_review:liste_decks")).content.decode()
        self.assertIn("Paquet 1", html)
        self.assertEqual(self.client.get(reverse("anki_review:reviser", args=["paquet-1"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("anki_review:edition_deck", args=["paquet-1"])).status_code, 200)

    def test_il_peut_encore_proposer_une_correction(self):
        r = self.client.post(reverse("anki_review:modifier_note", args=[self.note.id]), {
            "deck": self.deck.id, "question": "Q corrigée", "reponse": "R", "tags": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PropositionModification.objects.filter(note=self.note).count(), 1)

    def test_un_autre_etudiant_ne_voit_pas_le_paquet(self):
        self.client.force_login(eleve("C-gardee"))
        self.assertEqual(self.client.get(reverse("anki_review:reviser", args=["paquet-1"])).status_code, 404)

    def test_son_paquet_n_est_pas_propose_pour_y_ajouter_ses_cartes(self):
        reponse = self.client.get(reverse("anki_review:ajouter_note"))
        self.assertNotIn(self.deck, list(reponse.context["decks"]))


@override_settings(**CONFIG)
class SuppressionPaquetTests(TestCase):
    """Personne ne peut priver les autres d'une carte qu'ils utilisent."""

    def setUp(self):
        self.a, self.b = eleve("A-suppr"), eleve("B-suppr")
        self.deck = Deck.objects.create(nom="Paquet 1", slug="paquet-1", cree_par=self.a)
        self.partagee = Note.objects.create(
            deck=self.deck, question="partagée", reponse="R", cree_par=self.a, partagee_avec_classe=True)
        self.privee = Note.objects.create(deck=self.deck, question="privée", reponse="R", cree_par=self.a)
        for note in (self.partagee, self.privee):
            Card.objects.create(note=note, etudiant=self.a)
        Card.objects.create(note=self.partagee, etudiant=self.b)  # B l'a récupérée
        self.url = reverse("anki_review:supprimer_deck", args=[self.deck.id])

    def test_le_paquet_et_la_carte_utilisee_sont_conserves(self):
        self.client.force_login(self.a)
        self.client.post(self.url)
        self.assertTrue(Deck.objects.filter(pk=self.deck.pk).exists())
        self.partagee.refresh_from_db()
        self.assertEqual(self.partagee.cree_par, self.b)  # B en devient propriétaire
        self.assertTrue(Card.objects.filter(note=self.partagee, etudiant=self.b).exists())
        self.deck.refresh_from_db()
        self.assertEqual(self.deck.cree_par, self.b)  # et du paquet

    def test_les_cartes_que_personne_d_autre_n_utilise_sont_supprimees(self):
        self.client.force_login(self.a)
        self.client.post(self.url)
        self.assertFalse(Note.objects.filter(pk=self.privee.pk).exists())
        self.assertFalse(Card.objects.filter(etudiant=self.a).exists())

    def test_b_garde_acces_a_son_paquet_et_peut_le_reviser(self):
        self.client.force_login(self.a)
        self.client.post(self.url)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("anki_review:reviser", args=["paquet-1"])).status_code, 200)

    def test_cartes_ajoutees_par_b_dans_le_paquet_de_a_conservees(self):
        perso = Note.objects.create(deck=self.deck, question="de B", reponse="R", cree_par=self.b)
        Card.objects.create(note=perso, etudiant=self.b)
        self.client.force_login(self.a)
        self.client.post(self.url)
        self.assertTrue(Note.objects.filter(pk=perso.pk).exists())

    def test_paquet_que_personne_d_autre_n_utilise_est_vraiment_supprime(self):
        Card.objects.filter(etudiant=self.b).delete()
        self.client.force_login(self.a)
        self.client.post(self.url)
        self.assertFalse(Deck.objects.filter(pk=self.deck.pk).exists())

    def test_le_professeur_supprime_tout(self):
        prof = User.objects.create_user("prof-suppr", "mdp-test-solide-1", role=User.PROF)
        prof.a_vu_intro_pas_a_pas = True
        prof.save()
        self.client.force_login(prof)
        self.client.post(self.url)
        self.assertFalse(Deck.objects.filter(pk=self.deck.pk).exists())
        self.assertFalse(Note.objects.filter(pk=self.partagee.pk).exists())

    def test_retrait_d_une_carte_garde_le_transfert_de_propriete(self):
        self.client.force_login(self.a)
        self.client.post(reverse("anki_review:supprimer_note", args=[self.partagee.id]))
        self.partagee.refresh_from_db()
        self.assertEqual(self.partagee.cree_par, self.b)
