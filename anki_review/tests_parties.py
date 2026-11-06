"""Niveau « partie » (sous-matière) entre la matière et le paquet (chapitre)."""
import io
import os
import tempfile

import genanki
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import decks as gestion
from .apkg_export import _nom_paquet_anki, exporter_notes_apkg
from .apkg_import import importer_apkg
from .forms import DeckForm
from .management.commands.migrer_chapitres import CHAPITRES, chapitre_de
from .models import Card, Deck, Note
from .tests_rangement import CONFIG, carte_de, eleve, prof
from .views import _grouper_matieres


def paquet(user, nom, matiere="physique", partie="", slug=None):
    return Deck.objects.create(
        nom=nom, slug=slug or nom.lower().replace(" ", "-").replace("'", ""), cree_par=user,
        matiere=matiere, partie=partie)


@override_settings(**CONFIG)
class FormulairePartieTests(TestCase):
    def test_partie_acceptee_avec_une_matiere(self):
        f = DeckForm({"nom": "C1", "description": "", "matiere": "physique", "partie": "  Électricité  "})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["partie"], "Électricité")

    def test_partie_refusee_sans_matiere(self):
        f = DeckForm({"nom": "C1", "description": "", "matiere": "", "partie": "Électricité"})
        self.assertFalse(f.is_valid())
        self.assertIn("partie", f.errors)

    def test_partie_refusee_avec_slash_ou_double_deux_points(self):
        for mauvais in ("Élec/Optique", "Élec::Optique"):
            f = DeckForm({"nom": "C1", "description": "", "matiere": "physique", "partie": mauvais})
            self.assertFalse(f.is_valid(), mauvais)

    def test_creation_et_modification_via_les_vues(self):
        u = eleve("form-partie")
        self.client.force_login(u)
        r = self.client.post(reverse("anki_review:ajouter_deck"), {
            "nom": "C1 - Bases", "description": "", "matiere": "physique", "partie": "Électricité"})
        self.assertEqual(r.status_code, 302)
        deck = Deck.objects.get(nom="C1 - Bases")
        self.assertEqual((deck.matiere, deck.partie, deck.cree_par), ("physique", "Électricité", u))
        # La page propose les parties déjà utilisées de cette matière.
        page = self.client.get(reverse("anki_review:ajouter_deck"))
        self.assertContains(page, "Électricité")


@override_settings(**CONFIG)
class RegroupementTests(TestCase):
    def setUp(self):
        self.u = eleve("grp-partie")

    def test_trois_niveaux_et_totaux(self):
        a = paquet(self.u, "C1", partie="Électricité")
        b = paquet(self.u, "C2", partie="Électricité")
        c = paquet(self.u, "Lentilles", partie="Optique")
        d = paquet(self.u, "Vrac")
        e = paquet(self.u, "Mots", matiere="anglais")
        f = paquet(self.u, "Orphelin", matiere="")
        items = [{"deck": x, "dues": 2, "total": 5} for x in (a, b, c, d, e, f)]
        matieres = _grouper_matieres(items, sommes=("dues", "total"))
        self.assertEqual([m["libelle"] for m in matieres], ["Anglais", "Physique", "Sans matière"])
        physique = matieres[1]
        self.assertEqual([p["nom"] for p in physique["parties"]], ["Électricité", "Optique"])
        self.assertEqual(physique["parties"][0]["nb"], 2)
        self.assertEqual(physique["parties"][0]["dues"], 4)
        self.assertEqual([i["deck"].nom for i in physique["paquets"]], ["Vrac"])
        self.assertEqual((physique["nb_paquets"], physique["dues"], physique["total"]), (4, 8, 20))
        self.assertEqual(matieres[2]["parties"], [])

    def test_pages_revision_edition_partage_affichent_la_partie(self):
        deck = paquet(self.u, "C1 - Bases", partie="Électricité")
        carte_de(self.u, deck, "q")
        self.client.force_login(self.u)
        for nom in ("liste_decks", "edition", "partage_etudiants"):
            page = self.client.get(reverse(f"anki_review:{nom}"))
            self.assertEqual(page.status_code, 200, nom)
            self.assertContains(page, "Électricité", msg_prefix=nom)
            self.assertContains(page, "C1 - Bases", msg_prefix=nom)
        accueil = self.client.get(reverse("anki_review:liste_decks"))
        self.assertContains(accueil, "Réviser toute la partie")

    def test_reviser_partie(self):
        self.client.force_login(self.u)
        url = reverse("anki_review:reviser_partie", args=["physique", "Électricité"])
        # Aucune partie : retour à l'accueil.
        self.assertEqual(self.client.get(url).status_code, 302)
        deck = paquet(self.u, "C1", partie="Électricité")
        carte_de(self.u, deck, "q")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_selecteur_libelle_matiere_et_partie(self):
        from .views import _decks_pour_selecteur
        paquet(self.u, "C1", partie="Électricité")
        paquet(self.u, "Seul")
        libelles = {d.nom: d.libelle_matiere for d in _decks_pour_selecteur(Deck.objects.all())}
        self.assertEqual(libelles["C1"], "Physique › Électricité")
        self.assertEqual(libelles["Seul"], "Physique")


@override_settings(**CONFIG)
class RangementAvecPartieTests(TestCase):
    def setUp(self):
        self.p, self.e = prof("prof-partie"), eleve("eleve-partie")
        self.deck_p = paquet(self.p, "C1 - Bases", partie="Électricité")
        self.note = carte_de(self.p, self.deck_p, "Charge élémentaire")

    def test_paquet_de_meme_nom_garde_matiere_et_partie(self):
        d = gestion.paquet_de_meme_nom(self.e, self.deck_p)
        self.assertEqual((d.nom, d.matiere, d.partie, d.cree_par), ("C1 - Bases", "physique", "Électricité", self.e))
        # Un paquet de même nom mais SANS partie n'est pas réutilisé.
        autre = paquet(self.e, "C1 - Bases", slug="c1-bases-sans-partie")
        self.assertNotEqual(gestion.paquet_de_meme_nom(self.e, self.deck_p).pk, autre.pk)

    def test_recuperer_une_carte_la_range_dans_le_chapitre_de_la_meme_partie(self):
        self.client.force_login(self.e)
        self.client.post(reverse("anki_review:ranger_cartes"), {"notes": str(self.note.id), "choix": "meme_nom"})
        carte = Card.objects.get(note=self.note, etudiant=self.e)
        self.assertEqual(carte.deck.partie, "Électricité")

    def test_nouveau_paquet_hérite_de_la_partie(self):
        self.client.force_login(self.e)
        self.client.post(reverse("anki_review:ranger_cartes"), {
            "notes": str(self.note.id), "choix": "nouveau", "nouveau_nom": "Mon chapitre"})
        self.assertEqual(Deck.objects.get(nom="Mon chapitre", cree_par=self.e).partie, "Électricité")


@override_settings(**CONFIG)
class ApkgPartieTests(TestCase):
    def test_nom_anki_a_trois_niveaux(self):
        u = eleve("apkg-nom")
        self.assertEqual(
            _nom_paquet_anki(paquet(u, "C1 - Bases", partie="Électricité")),
            "Physique::Électricité::C1 - Bases")
        self.assertEqual(_nom_paquet_anki(paquet(u, "Optique", slug="optique")), "Physique::Optique")
        self.assertEqual(_nom_paquet_anki(paquet(u, "Libre", matiere="", slug="libre")), "Libre")

    def _apkg(self, nom_paquet, guid="g1"):
        modele = genanki.Model(
            1968100422, "Basique", fields=[{"name": "Front"}, {"name": "Back"}],
            templates=[{"name": "Carte 1", "qfmt": "{{Front}}", "afmt": "{{Back}}"}])
        paquet_anki = genanki.Deck(2059400110, nom_paquet)
        paquet_anki.add_note(genanki.Note(model=modele, fields=["Question", "Réponse"], guid=guid))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "t.apkg")
            genanki.Package(paquet_anki).write_to_file(chemin)
            return SimpleUploadedFile("t.apkg", open(chemin, "rb").read())

    def test_import_trois_segments_donne_matiere_partie_paquet(self):
        u = eleve("apkg-imp")
        importer_apkg(self._apkg("Physique::Électricité::C1 - Bases"), u)
        d = Deck.objects.get(cree_par=u)
        self.assertEqual((d.matiere, d.partie, d.nom), ("physique", "Électricité", "C1 - Bases"))

    def test_import_ancien_format_deux_segments_sans_partie(self):
        u = eleve("apkg-imp2")
        importer_apkg(self._apkg("Physique::Optique"), u)
        d = Deck.objects.get(cree_par=u)
        self.assertEqual((d.matiere, d.partie, d.nom), ("physique", "", "Optique"))

    def test_import_plus_de_trois_segments_aplatit_le_reste(self):
        u = eleve("apkg-imp3")
        importer_apkg(self._apkg("Physique::Optique::Lentilles::Minces"), u)
        d = Deck.objects.get(cree_par=u)
        self.assertEqual((d.partie, d.nom), ("Optique", "Lentilles — Minces"))

    def test_aller_retour_export_import(self):
        u, v = eleve("apkg-ar1"), eleve("apkg-ar2")
        deck = paquet(u, "C1 - Bases", partie="Électricité")
        note = carte_de(u, deck, "Question ?", partagee=False)
        contenu = exporter_notes_apkg(Note.objects.filter(pk=note.pk).select_related("deck"))
        importer_apkg(SimpleUploadedFile("x.apkg", contenu), v)
        d = Deck.objects.get(cree_par=v)
        self.assertEqual((d.matiere, d.partie, d.nom), ("physique", "Électricité", "C1 - Bases"))


@override_settings(**CONFIG)
class MigrationChapitresTests(TestCase):
    def setUp(self):
        self.p, self.e = prof("prof-mig"), eleve("eleve-mig")
        self.vieux_p = paquet(self.p, "Électricité", slug="electricite-p")
        self.vieux_e = paquet(self.e, "Électricité", slug="electricite-e")
        self.n1 = carte_de(self.p, self.vieux_p, "Charge", partagee=True)
        self.n1.tags = "Chap.1"
        self.n1.save()
        self.n3 = carte_de(self.p, self.vieux_p, "Premier ordre", partagee=True)
        self.n3.tags = "Autre Chap.3"
        self.n3.save()
        self.n_sans = carte_de(self.p, self.vieux_p, "Sans tag", partagee=True)
        # L'élève a récupéré deux cartes du professeur, avec de la progression.
        for note in (self.n1, self.n3):
            Card.objects.create(note=note, etudiant=self.e, deck=self.vieux_e, repetitions=4, intervalle_jours=12)
        self.math = paquet(self.p, "Outils mathématiques", slug="outils")

    def _lancer(self, *args):
        sortie = io.StringIO()
        call_command("migrer_chapitres", *args, stdout=sortie)
        return sortie.getvalue()

    def test_simulation_ne_modifie_rien(self):
        sortie = self._lancer()
        self.assertIn("SIMULATION", sortie)
        self.assertIn("Sans tag", sortie)
        self.assertTrue(Deck.objects.filter(pk=self.vieux_p.pk).exists())
        self.assertEqual(Card.objects.filter(deck=self.vieux_e).count(), 2)
        self.assertEqual(Deck.objects.filter(partie="Électricité").count(), 0)

    def test_application_range_chaque_carte_selon_son_tag(self):
        self._lancer("--appliquer")
        noms = CHAPITRES[("physique", "Électricité")]
        c1 = Deck.objects.get(cree_par=self.p, nom=noms[1])
        c3 = Deck.objects.get(cree_par=self.p, nom=noms[3])
        autres = Deck.objects.get(cree_par=self.p, nom="Autres")
        for deck in (c1, c3, autres):
            self.assertEqual((deck.matiere, deck.partie), ("physique", "Électricité"))
        self.assertEqual(Card.objects.get(note=self.n1, etudiant=self.p).deck, c1)
        self.assertEqual(Card.objects.get(note=self.n3, etudiant=self.p).deck, c3)
        self.assertEqual(Card.objects.get(note=self.n_sans, etudiant=self.p).deck, autres)
        # Note.deck (paquet de l'auteur) suit.
        self.n1.refresh_from_db()
        self.assertEqual(self.n1.deck, c1)
        # L'élève a ses propres paquets-chapitres, avec la progression intacte.
        carte = Card.objects.get(note=self.n3, etudiant=self.e)
        self.assertEqual((carte.deck.cree_par, carte.deck.nom, carte.deck.partie), (self.e, noms[3], "Électricité"))
        self.assertEqual((carte.repetitions, carte.intervalle_jours), (4, 12))
        # Anciens paquets vides supprimés ; l'autre paquet du professeur est intact.
        self.assertFalse(Deck.objects.filter(pk__in=[self.vieux_p.pk, self.vieux_e.pk]).exists())
        self.assertTrue(Deck.objects.filter(pk=self.math.pk).exists())

    def test_rejouable_sans_doublon(self):
        self._lancer("--appliquer")
        nb = Deck.objects.count()
        self._lancer("--appliquer")
        self.assertEqual(Deck.objects.count(), nb)

    def test_recuperation_apres_migration_va_dans_le_chapitre_de_l_eleve(self):
        self._lancer("--appliquer")
        autre = eleve("eleve-mig-2")
        note = Note.objects.get(pk=self.n3.pk)
        self.assertEqual(gestion.paquet_par_defaut(autre, note).partie, "Électricité")

    def test_chapitre_de_lit_le_tag(self):
        self.assertEqual(chapitre_de(Note(tags="x Chap.12 y")), 12)
        self.assertEqual(chapitre_de(Note(tags="Chapitre.3 Chap.x")), None)
        self.assertEqual(chapitre_de(Note(tags="Chap.5 Chap.2")), 2)
        self.assertIsNone(chapitre_de(Note(tags="")))
