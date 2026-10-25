from importlib import import_module

from django.apps import apps as registre_apps
from django.test import TestCase, override_settings

from accounts.models import User

from .forms import DeckForm
from .models import Deck
from .slugs import SLUGS_RESERVES, slug_de_base, slug_unique
from .urls import urlpatterns

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)


def creer_via_formulaire(nom, proprietaire=None):
    formulaire = DeckForm({"nom": nom, "description": "", "matiere": ""})
    assert formulaire.is_valid(), formulaire.errors
    deck = formulaire.save(commit=False)
    deck.slug = ""  # comme à la création : le slug est généré par save()
    deck = formulaire.save()
    if proprietaire:
        deck.cree_par = proprietaire
        deck.save(update_fields=["cree_par"])
    return deck


class SlugsTests(TestCase):
    def test_nom_normal(self):
        self.assertEqual(slug_de_base("Optique géométrique"), "optique-geometrique")

    def test_nom_sans_lettre_donne_paquet_puis_numero(self):
        premier = creer_via_formulaire("???")
        second = creer_via_formulaire("😀")
        troisieme = creer_via_formulaire("!!!")
        self.assertEqual(premier.slug, "paquet")
        self.assertEqual(second.slug, "paquet-2")
        self.assertEqual(troisieme.slug, "paquet-3")

    def test_nom_reserve(self):
        self.assertEqual(creer_via_formulaire("Trafic").slug, "trafic-paquet")
        self.assertEqual(creer_via_formulaire("trafic").slug, "trafic-paquet-2")
        self.assertEqual(creer_via_formulaire("Import-Export").slug, "import-export-paquet")

    def test_nom_tres_long_reste_dans_les_50_caracteres(self):
        deck = creer_via_formulaire("a" * 120)
        self.assertLessEqual(len(deck.slug), 50)
        autre = creer_via_formulaire("a" * 120)
        self.assertLessEqual(len(autre.slug), 50)
        self.assertNotEqual(deck.slug, autre.slug)

    def test_modification_ne_change_pas_le_slug(self):
        deck = creer_via_formulaire("Optique")
        formulaire = DeckForm({"nom": "Optique 2", "description": "", "matiere": ""}, instance=deck)
        formulaire.save()
        deck.refresh_from_db()
        self.assertEqual(deck.slug, "optique")

    def test_liste_reservee_couvre_toutes_les_routes_fixes(self):
        """Si on ajoute une route fixe à anki_review/urls.py, il faut aussi l'ajouter à
        SLUGS_RESERVES : sinon un paquet portant ce nom serait inaccessible."""
        premiers_segments = set()
        for motif in urlpatterns:
            segment = str(motif.pattern).split("/")[0]
            if segment and not segment.startswith("<"):
                premiers_segments.add(segment)
        self.assertEqual(premiers_segments - SLUGS_RESERVES, set())


@override_settings(**CONFIG)
class AccueilAvecPaquetsDifficilesTests(TestCase):
    def test_accueil_ne_plante_pas(self):
        prof = User.objects.create_user("prof-s", "mdp-test-123", role=User.PROF)
        creer_via_formulaire("???", prof)
        creer_via_formulaire("Trafic", prof)
        self.client.force_login(prof)
        self.assertEqual(self.client.get("/anki/").status_code, 200)
        self.assertEqual(self.client.get("/anki/paquet/").status_code, 200)
        self.assertEqual(self.client.get("/anki/trafic-paquet/").status_code, 200)


class MigrationSlugsTests(TestCase):
    def test_rattrapage_des_slugs_vides_et_reserves(self):
        # Paquets « cassés » créés directement en base, comme avant la correction.
        casse_vide = Deck.objects.create(nom="???", slug="")
        casse_reserve = Deck.objects.create(nom="Trafic", slug="trafic")
        bon = Deck.objects.create(nom="Optique", slug="optique")

        migration = import_module("anki_review.migrations.0021_corriger_slugs_paquets")
        migration.corriger_slugs(registre_apps, None)

        for deck in (casse_vide, casse_reserve, bon):
            deck.refresh_from_db()
        self.assertEqual(casse_vide.slug, "paquet")
        self.assertEqual(casse_reserve.slug, "trafic-paquet")
        self.assertEqual(bon.slug, "optique")  # un paquet correct n'est pas touché

    def test_rattrapage_sans_paquet_casse_ne_fait_rien(self):
        Deck.objects.create(nom="Optique", slug="optique")
        migration = import_module("anki_review.migrations.0021_corriger_slugs_paquets")
        migration.corriger_slugs(registre_apps, None)
        self.assertEqual(list(Deck.objects.values_list("slug", flat=True)), ["optique"])

    def test_slug_unique_ignore_le_paquet_lui_meme(self):
        deck = Deck.objects.create(nom="Optique", slug="optique")
        self.assertEqual(slug_unique("Optique", exclure_pk=deck.pk), "optique")
        self.assertEqual(slug_unique("Optique"), "optique-2")
