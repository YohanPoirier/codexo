from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .models import Activite, Deck, Note

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    PAS_A_PAS_ELEVES=False,
)


@override_settings(**CONFIG)
class TraficTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(identifiant="prof", password="x", is_staff=True)
        self.eleve = User.objects.create_user(identifiant="eleve", password="x")
        self.deck = Deck.objects.create(nom="D", slug="d")

    def _notes(self, n):
        return [
            Note.objects.create(deck=self.deck, question=f"q{i}", reponse="r", cree_par=self.eleve)
            for i in range(n)
        ]

    def test_export_compte_une_activite_par_carte(self):
        notes = self._notes(3)
        self.client.force_login(self.eleve)
        r = self.client.post(
            reverse("anki_review:exporter_apkg_selection"), {"notes": [n.id for n in notes]}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Activite.objects.filter(type="export", etudiant=self.eleve).count(), 3)

    def test_page_trafic_affiche_imports_et_exports(self):
        for t, n in (("import", 30), ("export", 12), ("ajout", 2)):
            Activite.objects.bulk_create([Activite(etudiant=self.eleve, type=t) for _ in range(n)])
        self.client.force_login(self.prof)
        html = self.client.get(reverse("anki_review:trafic")).content.decode()
        self.assertIn("<strong>30</strong> imports", html)
        self.assertIn("<strong>12</strong> exports", html)
        self.assertIn("<strong>2</strong> ajouts (éditeur)", html)
