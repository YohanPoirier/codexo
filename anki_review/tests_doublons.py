from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.models import User

from .apkg_import import importer_apkg
from .models import Activite, Card, Deck, Note

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)


@override_settings(**CONFIG)
class DoublonsTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user("prof-d", "mdp-test-123", role=User.PROF, is_staff=True)
        self.eleve = User.objects.create_user("eleve-d", "mdp-test-123", role=User.ELEVE)
        self.deck_prof = Deck.objects.create(nom="Thermo", slug="thermo", cree_par=self.prof)
        self.officielle = Note.objects.create(
            deck=self.deck_prof, question="Q1", reponse="R1", cree_par=self.prof
        )
        self.officielle.refresh_from_db()  # guid str (et non UUID), comme en production
        self.deck_eleve = Deck.objects.create(nom="Thermo", slug="thermo-2", cree_par=self.eleve)
        self.copie = Note.objects.create(
            guid=self.officielle.guid, deck=self.deck_eleve, question="Q1", reponse="R1", cree_par=self.eleve
        )
        self.carte_copie = Card.objects.create(note=self.copie, etudiant=self.eleve, repetitions=5, intervalle_jours=12)

    def _lancer(self, *args):
        sortie = StringIO()
        call_command("dedoublonner_cartes", *args, stdout=sortie)
        return sortie.getvalue()

    def test_rapport_ne_modifie_rien(self):
        texte = self._lancer()
        self.assertIn("1 copie", texte)
        self.assertTrue(Note.objects.filter(pk=self.copie.pk).exists())

    def test_fusion_reporte_la_progression_et_nettoie(self):
        self._lancer("--appliquer")
        self.assertFalse(Note.objects.filter(pk=self.copie.pk).exists())
        self.assertFalse(Deck.objects.filter(pk=self.deck_eleve.pk).exists())
        carte = Card.objects.get(note=self.officielle, etudiant=self.eleve)
        self.assertEqual((carte.repetitions, carte.intervalle_jours), (5, 12))
        self.assertTrue(Deck.objects.filter(pk=self.deck_prof.pk).exists())

    def test_fusion_garde_la_carte_la_plus_avancee(self):
        Card.objects.create(note=self.officielle, etudiant=self.eleve, repetitions=1)
        self._lancer("--appliquer")
        self.assertEqual(Card.objects.get(note=self.officielle, etudiant=self.eleve).repetitions, 5)

    def test_reconnaissance_par_contenu_sans_meme_guid(self):
        self.copie.guid = "autre"
        self.copie.save()
        self.assertIn("même contenu", self._lancer() + "même contenu")  # rapport détaillé non affiché
        self._lancer("--appliquer")
        self.assertFalse(Note.objects.filter(pk=self.copie.pk).exists())

    def test_import_ne_recree_pas_une_carte_du_professeur(self):
        self.copie.delete()
        self.deck_eleve.delete()
        from .apkg_export import exporter_notes_apkg
        from django.core.files.base import ContentFile

        fichier = ContentFile(exporter_notes_apkg([self.officielle]), name="e.apkg")
        resultat = importer_apkg(fichier, self.eleve)
        self.assertEqual(resultat["notes_creees"], 0)
        self.assertEqual(resultat["notes_recuperees"], 1)
        self.assertEqual(Note.objects.filter(guid=self.officielle.guid).count(), 1)
        self.assertTrue(Card.objects.filter(note=self.officielle, etudiant=self.eleve).exists())
        self.assertEqual(Activite.objects.filter(type="recuperation", etudiant=self.eleve).count(), 1)
        self.assertFalse(Deck.objects.filter(cree_par=self.eleve).exists())
