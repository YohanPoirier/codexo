from django.test import TestCase, override_settings

from accounts.models import User

STOCKAGE_SIMPLE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STOCKAGE_SIMPLE, PAS_A_PAS_ELEVES=True)
class PwaTests(TestCase):
    """Manifestes et service worker : publics, jamais redirigés, bien formés."""

    def test_manifeste_codexo_public(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r["Content-Type"])
        data = r.json()
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual({i["sizes"] for i in data["icons"]}, {"192x192", "512x512"})

    def test_manifeste_anki_propre_a_anki(self):
        data = self.client.get("/anki.webmanifest").json()
        self.assertEqual(data["scope"], "/anki/")
        self.assertEqual(data["start_url"], "/anki/")
        self.assertTrue(all("anki_review" in i["src"] for i in data["icons"]))

    def test_service_worker_a_la_racine(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertEqual(r["Cache-Control"], "no-cache")
        corps = r.content.decode()
        self.assertIn("const PREFIXE_STATIC = '/static/';", corps)
        self.assertIn("const DEBUG = ", corps)

    def test_pages_pwa_jamais_redirigees_pour_un_eleve_connecte(self):
        """Élève devant changer son mot de passe ET n'ayant pas vu l'intro du pas à pas."""
        eleve = User.objects.create_user("eleve-pwa", "mdp-test-123", role=User.ELEVE)
        eleve.doit_changer_mot_de_passe = True
        eleve.a_vu_intro_pas_a_pas = False
        eleve.save()
        self.client.force_login(eleve)
        for chemin in ("/sw.js", "/manifest.webmanifest", "/anki.webmanifest"):
            self.assertEqual(self.client.get(chemin).status_code, 200, chemin)
        # Contrôle : une page ordinaire, elle, est bien redirigée.
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_pages_declarent_le_manifeste(self):
        r = self.client.get("/login/")
        self.assertContains(r, 'rel="manifest" href="/manifest.webmanifest"')
        self.assertContains(r, "js/pwa.js")
