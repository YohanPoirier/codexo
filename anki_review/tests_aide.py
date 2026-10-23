import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from exercises.models import DemandeAide, Exercise, Theme

from .models import PreferencesNotification

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    PAS_A_PAS_ELEVES=False, NOTIFICATIONS_CODEXO=True,
    VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv", VAPID_CONTACT="mailto:t@example.com",
)


class FilSynchrone:
    """Remplace threading.Thread : exécute tout de suite (pas de fil dans les tests)."""
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@override_settings(**CONFIG)
class NotificationsCodexoTests(TestCase):
    def setUp(self):
        for cible, remplacement in (("anki_review.notifications.connection", mock.MagicMock()),
                                    ("anki_review.notifications.threading.Thread", FilSynchrone)):
            patcher = mock.patch(cible, remplacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prof = User.objects.create_user("prof-a", "mdp-test-123", role=User.PROF, is_staff=True)
        self.prof2 = User.objects.create_user("prof-b", "mdp-test-123", role=User.PROF, is_staff=True)
        self.eleve = User.objects.create_user("eleve-a", "mdp-test-123", role=User.ELEVE)
        theme = Theme.objects.create(name="Boucles", slug="boucles")
        self.ex = Exercise.objects.create(theme=theme, title="Somme", slug="somme", statement="x")

    def _demander(self):
        self.client.force_login(self.eleve)
        return self.client.post(
            reverse("demander_aide", args=[self.ex.id]),
            json.dumps({"code": "def f(): pass", "commentaire": "bloqué"}), content_type="application/json",
        )

    def test_nouvelle_demande_previent_les_professeurs(self):
        p = PreferencesNotification.pour(self.prof2)
        p.demandes_aide = False
        p.save()
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self._demander()
        self.assertEqual([c.args[0] for c in envoi.call_args_list], [self.prof])
        message = envoi.call_args.args[1]
        self.assertEqual(message["appli"], "codexo")
        self.assertIn("Somme", message["corps"])

    def test_reponse_previent_l_eleve(self):
        demande = DemandeAide.envoyer(self.eleve, self.ex, "code", "")
        self.client.force_login(self.prof)
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self.client.post(reverse("demande_aide_detail", args=[demande.id]), {"reponse": "Regarde la boucle."})
        envoi.assert_called_once()
        self.assertEqual(envoi.call_args.args[0], self.eleve)
        self.assertEqual(envoi.call_args.args[1]["url"], reverse("mes_demandes_aide"))

    def test_reglage_eleve_coupe_la_reponse(self):
        p = PreferencesNotification.pour(self.eleve)
        p.reponses_aide = False
        p.save()
        demande = DemandeAide.envoyer(self.eleve, self.ex, "code", "")
        self.client.force_login(self.prof)
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self.client.post(reverse("demande_aide_detail", args=[demande.id]), {"reponse": "ok"})
        envoi.assert_not_called()

    def test_demande_mot_de_passe_previent_les_professeurs(self):
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self.client.post(reverse("mot_de_passe_oublie"),
                             {"identifiant_saisi": "eleve-a", "email_contact": "a@example.com"})
        self.assertEqual({c.args[0] for c in envoi.call_args_list}, {self.prof, self.prof2})
        self.assertIn("eleve-a", envoi.call_args.args[1]["corps"])

    def test_rien_si_codexo_desactive(self):
        with override_settings(NOTIFICATIONS_CODEXO=False), \
                mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self._demander()
        envoi.assert_not_called()

    def test_page_reglages(self):
        self.client.force_login(self.eleve)
        html = self.client.get(reverse("notifications_codexo")).content.decode()
        self.assertIn('name="reponses_aide"', html)
        self.assertNotIn('name="demandes_aide"', html)
        self.client.post(reverse("notifications_codexo_preferences"), {"nouveaux_exercices": "on"})
        p = PreferencesNotification.pour(self.eleve)
        self.assertEqual((p.nouveaux_exercices, p.reponses_aide, p.demandes_aide), (True, False, True))
        self.client.force_login(self.prof)
        html = self.client.get(reverse("notifications_codexo")).content.decode()
        self.assertIn('name="demandes_aide"', html)
        self.assertIn('name="demandes_mdp"', html)

    def test_bandeaux_codexo(self):
        self.client.force_login(self.eleve)
        html = self.client.get(reverse("theme_list")).content.decode()
        self.assertIn('id="install-invitation"', html)
        self.assertIn('data-appli="codexo"', html)
        self.assertIn("cx-notif-invitation", html)
