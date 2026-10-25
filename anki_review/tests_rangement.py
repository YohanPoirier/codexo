"""Paquets personnels et rangement automatique."""
import re
from importlib import import_module

from django.apps import apps as registre_apps
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from . import decks as gestion
from .models import Card, Deck, Note, PropositionModification, RegleRangement

CONFIG = dict(
    PAS_A_PAS_ELEVES=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def eleve(nom):
    u = User.objects.create_user(nom, "mdp-test-solide-1", role=User.ELEVE)
    u.a_vu_intro_pas_a_pas = True
    u.save()
    return u


def prof(nom="prof-r"):
    u = User.objects.create_user(nom, "mdp-test-solide-1", role=User.PROF, is_staff=True)
    u.a_vu_intro_pas_a_pas = True
    u.save()
    return u


def carte_de(auteur, deck, texte, partagee=True):
    """Une note écrite par `auteur`, rangée chez lui dans `deck`."""
    note = Note.objects.create(
        deck=deck, question=texte, reponse="R", cree_par=auteur, partagee_avec_classe=partagee)
    Card.objects.create(note=note, etudiant=auteur, deck=deck)
    return note


@override_settings(**CONFIG)
class RecuperationTests(TestCase):
    """Récupérer une carte partagée : on la range dans un paquet À SOI."""

    def setUp(self):
        self.a, self.b = eleve("A-rang"), eleve("B-rang")
        self.deck_a = Deck.objects.create(nom="Vocabulaire", slug="vocabulaire", cree_par=self.a, matiere="anglais")
        self.n1 = carte_de(self.a, self.deck_a, "dog")
        self.n2 = carte_de(self.a, self.deck_a, "cat")
        self.client.force_login(self.b)

    def _ranger(self, notes, **donnees):
        return self.client.post(
            reverse("anki_review:ranger_cartes"), {"notes": ",".join(str(n.id) for n in notes), **donnees})

    # ---- sans règle : rangée aussitôt dans un paquet de même nom, « Changer » pour choisir autrement
    def test_sans_regle_la_carte_est_rangee_dans_un_paquet_de_meme_nom(self):
        r = self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n1.id]))
        self.assertEqual(r.status_code, 302)
        deck_b = Deck.objects.get(cree_par=self.b)
        self.assertEqual((deck_b.nom, deck_b.matiere), ("Vocabulaire", "anglais"))
        self.assertEqual(Card.objects.get(etudiant=self.b).deck, deck_b)
        self.assertFalse(RegleRangement.objects.exists())  # le même nom se retrouve sans règle

    def test_sans_regle_en_ajax_on_recoit_le_paquet_et_le_lien_changer(self):
        r = self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n1.id]), **AJAX)
        self.assertEqual(r.json()["deck"], "Vocabulaire")
        self.assertIn(reverse("anki_review:ranger_cartes"), r.json()["changer"])

    def test_la_deuxieme_carte_retrouve_le_meme_paquet(self):
        self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n1.id]))
        self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n2.id]))
        self.assertEqual(Deck.objects.filter(cree_par=self.b).count(), 1)
        self.assertEqual(Card.objects.filter(etudiant=self.b).count(), 2)

    def test_la_page_de_choix_propose_le_paquet_de_meme_nom(self):
        r = self.client.get(reverse("anki_review:ranger_cartes") + f"?notes={self.n1.id},{self.n2.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Créer le paquet « Vocabulaire »")
        self.assertContains(r, "Se souvenir de ce choix")

    def test_meme_nom_cree_un_paquet_a_soi_avec_la_meme_matiere(self):
        self._ranger([self.n1, self.n2], choix="meme_nom")
        deck_b = Deck.objects.get(cree_par=self.b)
        self.assertEqual((deck_b.nom, deck_b.matiere), ("Vocabulaire", "anglais"))
        self.assertNotEqual(deck_b.pk, self.deck_a.pk)
        self.assertEqual(Card.objects.filter(etudiant=self.b, deck=deck_b).count(), 2)

    def test_meme_nom_reutilise_le_paquet_deja_a_soi(self):
        existant = Deck.objects.create(nom="Vocabulaire", slug="vocab-b", cree_par=self.b, matiere="anglais")
        self._ranger([self.n1], choix="meme_nom")
        self.assertEqual(Deck.objects.filter(cree_par=self.b).count(), 1)
        self.assertEqual(Card.objects.get(etudiant=self.b).deck, existant)

    def test_ranger_dans_un_paquet_existant(self):
        mien = Deck.objects.create(nom="Anglais", slug="anglais-b", cree_par=self.b)
        self._ranger([self.n1], choix="existant", deck_existant=mien.id)
        self.assertEqual(Card.objects.get(etudiant=self.b).deck, mien)

    def test_ranger_dans_un_nouveau_paquet(self):
        self._ranger([self.n1], choix="nouveau", nouveau_nom="Mon vocabulaire")
        self.assertEqual(Card.objects.get(etudiant=self.b).deck.nom, "Mon vocabulaire")

    def test_on_ne_peut_pas_ranger_dans_le_paquet_d_un_autre(self):
        r = self._ranger([self.n1], choix="existant", deck_existant=self.deck_a.id)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Card.objects.filter(etudiant=self.b).exists())

    def test_une_carte_privee_ne_peut_pas_etre_recuperee(self):
        privee = carte_de(self.a, self.deck_a, "secret", partagee=False)
        self._ranger([privee], choix="meme_nom")
        self.assertFalse(Card.objects.filter(etudiant=self.b).exists())

    def test_le_professeur_ne_recupere_pas(self):
        self.client.force_login(prof())
        self.assertEqual(self._ranger([self.n1], choix="meme_nom").status_code, 403)

    # ---- avec règle : rangement automatique
    def test_souvenir_pose_une_regle(self):
        self._ranger([self.n1], choix="meme_nom", souvenir="1")
        regle = RegleRangement.objects.get(etudiant=self.b)
        self.assertEqual((regle.origine, regle.destination.nom), (self.deck_a, "Vocabulaire"))

    def test_sans_souvenir_pas_de_regle(self):
        self._ranger([self.n1], choix="meme_nom")
        self.assertFalse(RegleRangement.objects.exists())

    def test_avec_regle_la_carte_suivante_est_rangee_sans_question(self):
        self._ranger([self.n1], choix="nouveau", nouveau_nom="Anglais B", souvenir="1")
        r = self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n2.id]), **AJAX)
        donnees = r.json()
        self.assertEqual(donnees["deck"], "Anglais B")
        self.assertIn("changer", donnees)
        self.assertEqual(Card.objects.get(etudiant=self.b, note=self.n2).deck.nom, "Anglais B")

    def test_avec_regle_tout_ajouter_range_le_groupe(self):
        self._ranger([self.n1], choix="nouveau", nouveau_nom="Anglais B", souvenir="1")
        nouvelle = carte_de(self.a, self.deck_a, "bird")
        r = self.client.post(
            reverse("anki_review:ajouter_paquet_partage", args=[self.deck_a.id, self.a.id]), **AJAX)
        self.assertEqual(r.json()["nouvelles"], 2)  # cat et bird : dog était déjà là
        self.assertEqual(Card.objects.get(etudiant=self.b, note=nouvelle).deck.nom, "Anglais B")

    def test_tout_ajouter_sans_regle_range_dans_un_paquet_de_meme_nom(self):
        r = self.client.post(
            reverse("anki_review:ajouter_paquet_partage", args=[self.deck_a.id, self.a.id]), **AJAX)
        self.assertEqual((r.json()["nouvelles"], r.json()["deck"]), (2, "Vocabulaire"))
        self.assertEqual(Card.objects.filter(etudiant=self.b, deck__nom="Vocabulaire").count(), 2)

    def test_une_regle_ne_deplace_pas_ce_qui_est_deja_range(self):
        self._ranger([self.n1], choix="meme_nom")  # dog -> « Vocabulaire » (à B)
        ancien = Card.objects.get(etudiant=self.b).deck
        autre = Deck.objects.create(nom="Autre", slug="autre-b", cree_par=self.b)
        self._ranger([self.n2], choix="existant", deck_existant=autre.id, souvenir="1")
        self.assertEqual(Card.objects.get(etudiant=self.b, note=self.n1).deck, ancien)

    def test_changer_apres_coup_deplace_la_carte(self):
        self._ranger([self.n1], choix="meme_nom")
        mien = Deck.objects.create(nom="Autre", slug="autre-b", cree_par=self.b)
        self._ranger([self.n1], choix="existant", deck_existant=mien.id)
        self.assertEqual(Card.objects.get(etudiant=self.b, note=self.n1).deck, mien)
        self.assertEqual(Card.objects.filter(etudiant=self.b).count(), 1)

    def test_la_regle_disparait_avec_le_paquet_de_destination(self):
        self._ranger([self.n1], choix="nouveau", nouveau_nom="Anglais B", souvenir="1")
        Deck.objects.get(cree_par=self.b, nom="Anglais B").delete()
        self.assertFalse(RegleRangement.objects.exists())

    def test_sans_destination_valide_rien_n_est_fait(self):
        self._ranger([self.n1], choix="nouveau", nouveau_nom="   ")
        self.assertFalse(Card.objects.filter(etudiant=self.b).exists())


@override_settings(**CONFIG)
class PaquetsPrivesTests(TestCase):
    def setUp(self):
        self.a, self.b = eleve("A-priv"), eleve("B-priv")
        self.deck_a = Deck.objects.create(nom="Secret", slug="secret", cree_par=self.a)
        carte_de(self.a, self.deck_a, "q", partagee=True)
        self.client.force_login(self.b)

    def test_le_paquet_d_un_autre_est_invisible_meme_s_il_contient_des_cartes_partagees(self):
        self.assertNotContains(self.client.get(reverse("anki_review:liste_decks")), "Secret")
        self.assertEqual(self.client.get(reverse("anki_review:reviser", args=["secret"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("anki_review:edition_deck", args=["secret"])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("anki_review:edition")), "Secret")

    def test_un_nouvel_etudiant_n_a_aucun_paquet(self):
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), "aucun paquet")

    def test_on_ne_peut_pas_ajouter_une_carte_dans_le_paquet_d_un_autre(self):
        r = self.client.post(reverse("anki_review:ajouter_note"), {
            "deck": self.deck_a.id, "type_carte": "normal", "question": "x", "reponse": "y", "tags": ""})
        self.assertEqual(r.status_code, 200)  # formulaire réaffiché avec une erreur
        self.assertEqual(Note.objects.filter(question="x").count(), 0)

    def test_creer_une_carte_la_range_dans_mon_paquet(self):
        mien = Deck.objects.create(nom="Mien", slug="mien", cree_par=self.b)
        self.client.post(reverse("anki_review:ajouter_note"), {
            "deck": mien.id, "type_carte": "normal", "question": "x", "reponse": "y", "tags": ""})
        note = Note.objects.get(question="x")
        self.assertEqual(note.deck, mien)
        self.assertEqual(Card.objects.get(note=note, etudiant=self.b).deck, mien)

    def test_le_professeur_voit_le_paquet_pour_moderer(self):
        self.client.force_login(prof())
        self.assertEqual(self.client.get(reverse("anki_review:edition_deck", args=["secret"])).status_code, 200)
        self.assertContains(self.client.get(reverse("anki_review:edition")), "Secret")

    def test_le_professeur_ne_revise_que_ses_paquets(self):
        self.client.force_login(prof())
        self.assertEqual(self.client.get(reverse("anki_review:reviser", args=["secret"])).status_code, 404)


@override_settings(**CONFIG)
class DeplacerEtChangerDePaquetTests(TestCase):
    def setUp(self):
        self.a, self.b = eleve("A-dep2"), eleve("B-dep2")
        self.d1 = Deck.objects.create(nom="D1", slug="d1", cree_par=self.a)
        self.d2 = Deck.objects.create(nom="D2", slug="d2", cree_par=self.a)
        self.mienne = carte_de(self.a, self.d1, "mienne")
        self.recue = carte_de(self.b, Deck.objects.create(nom="DB", slug="db", cree_par=self.b), "de B")
        Card.objects.create(note=self.recue, etudiant=self.a, deck=self.d1)  # A l'a récupérée
        self.client.force_login(self.a)

    def test_deplacer_tout_le_paquet(self):
        self.client.post(reverse("anki_review:deplacer_cartes", args=[self.d1.id]), {"destination": self.d2.id})
        self.assertEqual(Card.objects.filter(etudiant=self.a, deck=self.d2).count(), 2)
        self.assertTrue(Deck.objects.filter(pk=self.d1.pk).exists())  # conservé, vide
        self.mienne.refresh_from_db()
        self.recue.refresh_from_db()
        self.assertEqual(self.mienne.deck, self.d2)  # l'auteur : Note.deck suit
        self.assertNotEqual(self.recue.deck, self.d2)  # pas à lui : le paquet de l'auteur reste

    def test_pas_de_deplacement_vers_le_paquet_d_un_autre(self):
        r = self.client.post(
            reverse("anki_review:deplacer_cartes", args=[self.d1.id]), {"destination": self.recue.deck_id})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Card.objects.filter(etudiant=self.a, deck=self.d1).count(), 2)

    def test_pas_de_deplacement_depuis_le_paquet_d_un_autre(self):
        self.client.force_login(self.b)
        r = self.client.post(reverse("anki_review:deplacer_cartes", args=[self.d1.id]), {"destination": self.d2.id})
        self.assertEqual(r.status_code, 404)

    def test_l_auteur_change_le_paquet_de_sa_carte_en_la_modifiant(self):
        self.client.post(reverse("anki_review:modifier_note", args=[self.mienne.id]), {
            "deck": self.d2.id, "type_carte": "normal", "question": "mienne", "reponse": "R", "tags": ""})
        self.mienne.refresh_from_db()
        self.assertEqual(self.mienne.deck, self.d2)
        self.assertEqual(Card.objects.get(note=self.mienne, etudiant=self.a).deck, self.d2)

    def test_un_destinataire_range_sa_carte_sans_toucher_celle_de_l_auteur(self):
        r = self.client.post(reverse("anki_review:modifier_note", args=[self.recue.id]), {
            "deck": self.d2.id, "question": "de B", "reponse": "R", "tags": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Card.objects.get(note=self.recue, etudiant=self.a).deck, self.d2)
        self.recue.refresh_from_db()
        self.assertNotEqual(self.recue.deck, self.d2)
        self.assertEqual(self.recue.deck.cree_par, self.b)

    def test_le_professeur_qui_modifie_la_carte_d_un_eleve_ne_la_range_pas_chez_lui(self):
        p = prof()
        self.client.force_login(p)
        r = self.client.post(reverse("anki_review:modifier_note", args=[self.mienne.id]), {
            "type_carte": "normal", "question": "corrigée", "reponse": "R", "tags": ""})
        self.assertEqual(r.status_code, 302)
        self.mienne.refresh_from_db()
        self.assertEqual((self.mienne.question, self.mienne.deck), ("corrigée", self.d1))
        self.assertFalse(Card.objects.filter(etudiant=p).exists())

    def test_passer_en_double_cree_la_carte_miroir_dans_le_meme_paquet(self):
        self.client.post(reverse("anki_review:modifier_note", args=[self.mienne.id]), {
            "deck": self.d2.id, "type_carte": "double", "question": "mienne", "reponse": "R", "tags": ""})
        self.mienne.refresh_from_db()
        miroir = self.mienne.note_miroir
        self.assertEqual(self.mienne.deck, self.d2)
        self.assertEqual(miroir.deck, self.d2)
        self.assertEqual(Card.objects.get(note=miroir, etudiant=self.a).deck, self.d2)


@override_settings(**CONFIG)
class RevisionParPaquetPersonnelTests(TestCase):
    def test_la_revision_ne_montre_que_mes_cartes_de_mon_paquet(self):
        a, b = eleve("A-rev2"), eleve("B-rev2")
        deck_a = Deck.objects.create(nom="Optique", slug="optique", cree_par=a)
        note = carte_de(a, deck_a, "Snell")
        Card.objects.create(note=note, etudiant=b)  # B : rangée dans « Optique » à lui
        deck_b = Card.objects.get(etudiant=b).deck
        self.assertNotEqual(deck_a, deck_b)
        self.client.force_login(b)
        r = self.client.get(reverse("anki_review:reviser", args=[deck_b.slug]))
        self.assertEqual(r.context["carte"].etudiant, b)
        self.assertEqual(r.context["restantes"], 1)


@override_settings(**CONFIG)
class SuppressionDePaquetEtRegleTests(TestCase):
    def test_supprimer_son_paquet_retire_les_regles_associees(self):
        a, b = eleve("A-sr"), eleve("B-sr")
        origine = Deck.objects.create(nom="O", slug="o", cree_par=a)
        dest = Deck.objects.create(nom="Dest", slug="dest", cree_par=b)
        RegleRangement.objects.create(etudiant=b, origine=origine, destination=dest)
        self.client.force_login(b)
        self.client.post(reverse("anki_review:supprimer_deck", args=[dest.id]))
        self.assertFalse(RegleRangement.objects.exists())


class CarteSansPaquetTests(TestCase):
    """Une carte posée sans paquet est rangée automatiquement."""

    def test_regle_puis_meme_nom(self):
        a, b = eleve("A-def"), eleve("B-def")
        origine = Deck.objects.create(nom="Thermo", slug="thermo", cree_par=a)
        note = carte_de(a, origine, "q")
        self.assertEqual(gestion.paquet_par_defaut(a, note), origine)  # le sien
        carte = Card.objects.create(note=note, etudiant=b)
        self.assertEqual((carte.deck.nom, carte.deck.cree_par), ("Thermo", b))
        destination = Deck.objects.create(nom="Ailleurs", slug="ailleurs", cree_par=b)
        RegleRangement.objects.create(etudiant=b, origine=origine, destination=destination)
        autre = carte_de(a, origine, "q2")
        self.assertEqual(Card.objects.create(note=autre, etudiant=b).deck, destination)


class MigrationRangementTests(TestCase):
    """Migration 0024 : chacun reçoit ses propres paquets, rien n'est perdu."""

    def setUp(self):
        self.prof = prof("prof-mig")
        self.e1, self.e2, self.e3 = eleve("E1-mig"), eleve("E2-mig"), eleve("E3-mig")
        # Ancien état : un paquet du professeur, rempli de cartes que tous rangent LÀ.
        self.thermo = Deck.objects.create(nom="Thermo", slug="thermo", cree_par=self.prof, matiere="physique")
        self.officielles = [carte_de(self.prof, self.thermo, f"off{i}") for i in range(2)]
        for n in self.officielles:
            for e in (self.e1, self.e2):
                Card.objects.create(note=n, etudiant=e, deck=self.thermo)
        # E2 a écrit un paquet que E3 utilise aussi ; E3 y a ajouté une carte à lui.
        self.vocab = Deck.objects.create(nom="Vocab", slug="vocab", cree_par=self.e2)
        self.n_e2 = carte_de(self.e2, self.vocab, "de E2")
        Card.objects.create(note=self.n_e2, etudiant=self.e3, deck=self.vocab)
        self.n_e3 = Note.objects.create(deck=self.vocab, question="de E3", reponse="R", cree_par=self.e3)
        Card.objects.create(note=self.n_e3, etudiant=self.e3, deck=self.vocab)
        # Paquet sans propriétaire.
        self.orphelin = Deck.objects.create(nom="Ancien", slug="ancien", cree_par=None)
        n = Note.objects.create(deck=self.orphelin, question="vieille", reponse="R", cree_par=None)
        Card.objects.create(note=n, etudiant=self.e1, deck=self.orphelin)

    def _migrer(self):
        migration = import_module("anki_review.migrations.0024_rangement_donnees")
        migration.repartir_les_paquets(registre_apps, None)

    def test_chacun_range_chez_soi_sans_rien_perdre(self):
        nb_cartes, nb_notes = Card.objects.count(), Note.objects.count()
        self._migrer()
        self.assertEqual((Card.objects.count(), Note.objects.count()), (nb_cartes, nb_notes))
        for carte in Card.objects.select_related("deck"):
            self.assertEqual(carte.deck.cree_par_id, carte.etudiant_id)

    def test_un_eleve_retrouve_le_meme_paquet_au_nom_pres(self):
        self._migrer()
        deck_e1 = Card.objects.get(etudiant=self.e1, note=self.officielles[0]).deck
        self.assertEqual((deck_e1.nom, deck_e1.matiere), ("Thermo", "physique"))
        self.assertNotEqual(deck_e1.pk, self.thermo.pk)
        # Les deux cartes officielles sont dans le MÊME paquet de E1, et E2 a le sien.
        self.assertEqual(Card.objects.get(etudiant=self.e1, note=self.officielles[1]).deck, deck_e1)
        self.assertNotEqual(Card.objects.get(etudiant=self.e2, note=self.officielles[0]).deck, deck_e1)

    def test_le_professeur_garde_son_paquet(self):
        self._migrer()
        self.assertEqual(Card.objects.get(etudiant=self.prof, note=self.officielles[0]).deck, self.thermo)

    def test_la_regle_de_rangement_est_posee_automatiquement(self):
        self._migrer()
        deck_e1 = Card.objects.get(etudiant=self.e1, note=self.officielles[0]).deck
        regle = RegleRangement.objects.get(etudiant=self.e1, origine=self.thermo)
        self.assertEqual(regle.destination, deck_e1)
        # Pas de règle pour ses propres paquets.
        self.assertFalse(RegleRangement.objects.filter(etudiant=self.e2, origine=self.vocab).exists())

    def test_la_carte_de_e3_dans_le_paquet_de_e2_a_son_propre_paquet(self):
        self._migrer()
        deck_e3 = Card.objects.get(etudiant=self.e3, note=self.n_e2).deck
        self.assertEqual((deck_e3.nom, deck_e3.cree_par), ("Vocab", self.e3))
        # Sa propre carte, elle, était dans le paquet de E2 : elle le suit dans son paquet à lui.
        self.assertEqual(Card.objects.get(etudiant=self.e3, note=self.n_e3).deck, deck_e3)
        self.n_e3.refresh_from_db()
        self.assertEqual(self.n_e3.deck, deck_e3)  # Note.deck = paquet de l'auteur

    def test_un_paquet_sans_proprietaire_est_confie_au_professeur(self):
        self._migrer()
        self.orphelin.refresh_from_db()
        self.assertEqual(self.orphelin.cree_par, self.prof)

    def test_deuxieme_passage_ne_cree_rien_de_plus(self):
        self._migrer()
        nb_paquets, nb_regles = Deck.objects.count(), RegleRangement.objects.count()
        self._migrer()
        self.assertEqual((Deck.objects.count(), RegleRangement.objects.count()), (nb_paquets, nb_regles))


@override_settings(**CONFIG)
class PagesTests(TestCase):
    """Toutes les pages s'affichent, pour un élève et pour le professeur."""

    def setUp(self):
        self.p, self.a, self.b = prof("prof-pg"), eleve("A-pg"), eleve("B-pg")
        self.deck_p = Deck.objects.create(nom="Thermo", slug="thermo", cree_par=self.p, matiere="physique")
        self.off = carte_de(self.p, self.deck_p, "officielle")
        self.deck_a = Deck.objects.create(nom="Mon paquet", slug="mon-paquet", cree_par=self.a)
        self.mienne = carte_de(self.a, self.deck_a, "mienne", partagee=False)
        Card.objects.create(note=self.off, etudiant=self.a)  # rangée dans « Thermo » à lui
        self.deck_a_thermo = Card.objects.get(note=self.off, etudiant=self.a).deck

    def _ok(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r

    def test_pages_de_l_eleve(self):
        self.client.force_login(self.a)
        for nom, args in [
            ("liste_decks", []), ("edition", []), ("ajouter_note", []), ("ajouter_deck", []),
            ("import_export_accueil", []), ("import_export_fichier", []), ("partage_etudiants", []),
            ("notifications", []),
            ("edition_deck", [self.deck_a.slug]), ("edition_deck", [self.deck_a_thermo.slug]),
            ("reviser", [self.deck_a.slug]), ("reviser_matiere", ["sans-matiere"]),
            ("modifier_note", [self.mienne.id]), ("modifier_note", [self.off.id]),
            ("deplacer_cartes", [self.deck_a.id]), ("modifier_deck", [self.deck_a.id]),
        ]:
            self._ok(reverse(f"anki_review:{nom}", args=args))
        r = self._ok(reverse("anki_review:ranger_cartes") + f"?notes={self.off.id}")
        self.assertContains(r, "Thermo")

    def test_la_page_d_edition_montre_mes_paquets_et_pas_ceux_des_autres(self):
        self.client.force_login(self.a)
        r = self.client.get(reverse("anki_review:edition"))
        self.assertContains(r, "Mon paquet")
        self.assertNotContains(r, "mienne-de-b")

    def test_le_partage_montre_les_cartes_des_autres_et_la_page_de_l_eleve_b(self):
        carte_de(self.a, self.deck_a, "partagée par A", partagee=True)
        self.client.force_login(self.b)
        r = self._ok(reverse("anki_review:partage_etudiants"))
        self.assertContains(r, "partagée par A")
        self.assertContains(r, "Tout ajouter")

    def test_pages_du_professeur(self):
        self.client.force_login(self.p)
        for nom, args in [
            ("liste_decks", []), ("edition", []), ("ajouter_note", []), ("import_export_fichier", []),
            ("partage_etudiants", []), ("edition_deck", [self.deck_a.slug]), ("edition_deck", [self.deck_p.slug]),
            ("modifier_note", [self.mienne.id]), ("trafic", []),
        ]:
            self._ok(reverse(f"anki_review:{nom}", args=args))
        self._ok(reverse("anki_review:edition") + "?mes=1")

    def test_export_apkg_range_les_cartes_dans_mes_paquets(self):
        self.client.force_login(self.a)
        r = self.client.post(reverse("anki_review:exporter_apkg_selection"), {"notes": [self.mienne.id, self.off.id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="export.apkg"')


@override_settings(**CONFIG)
class ConnexionAnkiTests(TestCase):
    def setUp(self):
        self.a = eleve("A-conn")

    def test_un_visiteur_est_renvoye_vers_la_connexion_d_anki(self):
        r = self.client.get(reverse("anki_review:liste_decks"))
        self.assertRedirects(
            r, reverse("anki_review:connexion") + "?next=" + reverse("anki_review:liste_decks"),
            fetch_redirect_response=False)

    def test_la_page_est_celle_d_anki_sans_codexo(self):
        r = self.client.get(reverse("anki_review:connexion"))
        self.assertContains(r, "Se connecter")
        self.assertContains(r, 'class="brand"')
        visible = re.sub(r"<!--.*?-->", "", r.content.decode(), flags=re.S)
        self.assertNotIn("Codexo", visible)

    def test_la_connexion_ramene_dans_anki(self):
        r = self.client.post(reverse("anki_review:connexion"),
                             {"username": self.a.identifiant, "password": "mdp-test-solide-1"})
        self.assertRedirects(r, reverse("anki_review:liste_decks"), fetch_redirect_response=False)

    def test_la_connexion_respecte_next(self):
        url = reverse("anki_review:edition")
        r = self.client.post(reverse("anki_review:connexion") + "?next=" + url,
                             {"username": self.a.identifiant, "password": "mdp-test-solide-1", "next": url})
        self.assertRedirects(r, url, fetch_redirect_response=False)

    def test_mauvais_mot_de_passe(self):
        r = self.client.post(reverse("anki_review:connexion"),
                             {"username": self.a.identifiant, "password": "faux"})
        self.assertEqual(r.status_code, 200)
