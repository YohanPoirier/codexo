"""Import .apkg : choix de la destination de chaque paquet du fichier sur l'écran de sélection."""
import os
import tempfile

import genanki
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .apkg_import import analyser_apkg, decomposer_nom_anki, importer_apkg
from .models import Card, Deck, Note
from .tests_rangement import CONFIG, eleve

G1, G2 = "guid-dest-1", "guid-dest-2"


def apkg(nom_paquet="Physique::Électricité::C1 - Bases", guids=(G1,)):
    modele = genanki.Model(
        1968100499, "Basique", fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[{"name": "Carte 1", "qfmt": "{{Front}}", "afmt": "{{Back}}"}])
    paquet = genanki.Deck(2059400199, nom_paquet)
    for g in guids:
        paquet.add_note(genanki.Note(model=modele, fields=[f"Q {g}", "R"], guid=g))
    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "t.apkg")
        genanki.Package(paquet).write_to_file(chemin)
        return SimpleUploadedFile("t.apkg", open(chemin, "rb").read())


@override_settings(**CONFIG)
class DestinationImportTests(TestCase):
    def setUp(self):
        self.u = eleve("dest-u")
        self.client.force_login(self.u)

    def _selection(self, **donnees):
        """Téléverse puis confirme avec les destinations données (numéro de paquet = 1)."""
        r = self.client.post(reverse("anki_review:import_export_fichier"), {"fichier": apkg(guids=(G1, G2))})
        self.assertEqual(r.status_code, 200)
        nom_fichier = r.context["paquets"][0]["nom_deck"]
        corps = {"notes": [G1, G2], "nom_deck_1": nom_fichier}
        corps.update(donnees)
        return self.client.post(reverse("anki_review:import_apkg_confirmer"), corps)

    def test_decomposition_du_nom(self):
        self.assertEqual(decomposer_nom_anki("Physique::Électricité::C1 - Bases"),
                         ("physique", "Électricité", "C1 - Bases"))

    def test_l_analyse_propose_une_destination_par_defaut(self):
        paquets, _ = analyser_apkg(apkg())
        self.assertEqual(paquets[0]["defaut"]["partie"], "Électricité")
        self.assertEqual(paquets[0]["defaut"]["libelle"], "Physique › Électricité › C1 - Bases")

    def test_defaut_cree_le_paquet_d_apres_le_nom(self):
        self._selection(dest_1="defaut")
        deck = Deck.objects.get(cree_par=self.u)
        self.assertEqual((deck.matiere, deck.partie, deck.nom), ("physique", "Électricité", "C1 - Bases"))
        self.assertEqual(Card.objects.filter(etudiant=self.u, deck=deck).count(), 2)

    def test_vers_un_paquet_existant(self):
        cible = Deck.objects.create(nom="Mon vrac", slug="vrac", cree_par=self.u)
        self._selection(dest_1=f"deck:{cible.id}")
        self.assertEqual(Deck.objects.filter(cree_par=self.u).count(), 1)
        self.assertEqual(Card.objects.filter(etudiant=self.u, deck=cible).count(), 2)

    def test_vers_un_nouveau_paquet(self):
        self._selection(dest_1="nouveau", nom_1="  Révisions   DS ", matiere_1="physique", partie_1="Optique")
        deck = Deck.objects.get(cree_par=self.u)
        self.assertEqual((deck.matiere, deck.partie, deck.nom), ("physique", "Optique", "Révisions DS"))
        self.assertEqual(Note.objects.filter(deck=deck).count(), 2)

    def test_nouveau_sans_matiere_ignore_la_partie(self):
        self._selection(dest_1="nouveau", nom_1="Vrac", matiere_1="", partie_1="Optique")
        self.assertEqual(Deck.objects.get(cree_par=self.u).partie, "")

    def test_nouveau_sans_nom_reaffiche_la_selection_sans_rien_importer(self):
        r = self._selection(dest_1="nouveau", nom_1=" ")
        self.assertTemplateUsed(r, "anki_review/import_apkg_selection.html")
        self.assertContains(r, "Donne un nom")
        self.assertFalse(Note.objects.exists())
        # Le fichier est conservé : on peut corriger et confirmer.
        r = self.client.post(reverse("anki_review:import_apkg_confirmer"), {
            "notes": [G1], "nom_deck_1": "Physique::Électricité::C1 - Bases", "dest_1": "defaut"})
        self.assertEqual(Note.objects.count(), 1)

    def test_partie_avec_slash_refusee(self):
        r = self._selection(dest_1="nouveau", nom_1="X", partie_1="a/b")
        self.assertContains(r, "ni « / »")
        self.assertFalse(Deck.objects.exists())

    def test_on_ne_peut_pas_viser_le_paquet_d_un_autre(self):
        autre = Deck.objects.create(nom="Autre", slug="autre", cree_par=eleve("dest-v"))
        r = self._selection(dest_1=f"deck:{autre.id}")
        self.assertContains(r, "existe pas")
        self.assertFalse(Note.objects.exists())

    def test_carte_deja_connue_suit_la_destination_choisie(self):
        prof_ = eleve("dest-auteur")
        deck_a = Deck.objects.create(nom="A", slug="a", cree_par=prof_)
        note = Note.objects.create(deck=deck_a, question="Q", reponse="R", cree_par=prof_,
                                   guid=G1, partagee_avec_classe=True)
        Card.objects.create(note=note, etudiant=prof_, deck=deck_a)
        cible = Deck.objects.create(nom="Cible", slug="cible", cree_par=self.u)
        self._selection(dest_1=f"deck:{cible.id}")
        self.assertEqual(Card.objects.get(etudiant=self.u, note=note).deck, cible)


class LibelleSansMatiereTests(TestCase):
    def test_matiere_non_reconnue_est_ecrite_en_toutes_lettres(self):
        paquets, _ = analyser_apkg(apkg("fysique::outils mathématiques"))
        self.assertEqual(paquets[0]["defaut"]["libelle"], "Sans matière › fysique — outils mathématiques")
