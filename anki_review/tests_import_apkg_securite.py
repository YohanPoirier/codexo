import shutil
import tempfile
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

MEDIA = tempfile.mkdtemp()
CONFIG = dict(
    MEDIA_ROOT=MEDIA,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)


@override_settings(**CONFIG)
class ConfirmationImportApkgTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.eleve = User.objects.create_user("eleve-i", "mdp-eleve-solide-1")
        self.eleve.a_vu_intro_pas_a_pas = True
        self.eleve.save()
        self.client.force_login(self.eleve)
        self.victime = default_storage.save("anki_review/notes/victime.png", ContentFile(b"img"))

    def _confirmer(self, **donnees):
        return self.client.post(reverse("anki_review:import_apkg_confirmer"), {"notes": ["x"], **donnees})

    def test_chemin_du_formulaire_ignore_et_fichier_intact(self):
        reponse = self._confirmer(chemin_temp=self.victime)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(default_storage.exists(self.victime))

    def test_chemin_falsifie_en_session_refuse(self):
        for faux in (self.victime, "anki_review/import_temp/../notes/victime.png", 42):
            session = self.client.session
            session["import_apkg_temp"] = faux
            session.save()
            self._confirmer()
            self.assertTrue(default_storage.exists(self.victime), faux)

    def test_parcours_normal_importe_puis_supprime_le_temporaire(self):
        with mock.patch("anki_review.views.analyser_apkg", return_value=([], 0)):
            self.client.post(
                reverse("anki_review:import_export_fichier"),
                {"fichier": SimpleUploadedFile("p.apkg", b"zip")},
            )
        temp = self.client.session["import_apkg_temp"]
        self.assertTrue(default_storage.exists(temp))
        with mock.patch("anki_review.views.importer_apkg", return_value=None) as imp:
            self._confirmer()
        imp.assert_called_once()
        self.assertFalse(default_storage.exists(temp))
        self.assertNotIn("import_apkg_temp", self.client.session)
        self.assertTrue(default_storage.exists(self.victime))
