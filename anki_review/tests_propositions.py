from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .models import Card, Deck, Note, PropositionModification

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    PAS_A_PAS_ELEVES=False,
    VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv", VAPID_CONTACT="mailto:t@example.com",
)


class FilSynchrone:
    """Remplace threading.Thread : exécute tout de suite (pas de fil dans les tests)."""
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@override_settings(**CONFIG)
@mock.patch("anki_review.notifications.connection")
@mock.patch("anki_review.notifications.threading.Thread", FilSynchrone)
class PropositionsTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user("prof-p", "mdp-test-123", role=User.PROF, is_staff=True)
        self.eleve = User.objects.create_user("eleve-p", "mdp-test-123", role=User.ELEVE)
        self.deck = Deck.objects.create(nom="Optique", slug="optique", cree_par=self.prof)
        self.note = Note.objects.create(deck=self.deck, question="Loi de Snell", reponse="n1 sin i1 = n2 sin i2", cree_par=self.prof)
        Card.objects.create(note=self.note, etudiant=self.eleve)

    def _proposer(self):
        self.client.force_login(self.eleve)
        return self.client.post(reverse("anki_review:modifier_note", args=[self.note.id]), {
            "deck": Deck.objects.get(cree_par=self.eleve).id, "question": "Loi de Snell-Descartes", "reponse": "n1 sin i1 = n2 sin i2", "tags": "",
        })

    def test_proposition_previent_le_proprietaire(self, _connexion):
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self._proposer()
        self.assertEqual(PropositionModification.objects.count(), 1)
        envoi.assert_called_once()
        destinataire, message = envoi.call_args.args
        self.assertEqual(destinataire, self.prof)
        self.assertIn("Loi de Snell", message["corps"])
        self.assertTrue(message["tag"].startswith("anki-proposition-"))

    def test_bandeau_accueil(self, _connexion):
        with mock.patch("anki_review.notifications.envoyer_message"):
            self._proposer()
        self.client.force_login(self.prof)
        html = self.client.get(reverse("anki_review:liste_decks")).content.decode()
        self.assertIn("1 modification proposée", html)
        self.client.force_login(self.eleve)
        html = self.client.get(reverse("anki_review:liste_decks")).content.decode()
        self.assertNotIn("modification proposée", html)

    def test_reglage_coupe_la_notification(self, _connexion):
        from .models import PreferencesNotification
        self.client.force_login(self.prof)
        self.client.post(reverse("anki_review:notifications_preferences"), {})  # case décochée
        self.assertFalse(PreferencesNotification.pour(self.prof).propositions)
        with mock.patch("anki_review.notifications.envoyer_message") as envoi:
            self._proposer()
        envoi.assert_not_called()

    def test_reglage_eleve_garde_les_autres_choix(self, _connexion):
        from .models import PreferencesNotification
        self.client.force_login(self.eleve)
        self.client.post(reverse("anki_review:notifications_preferences"), {"cartes_a_reviser": "on"})
        p = PreferencesNotification.pour(self.eleve)
        self.assertEqual((p.cartes_a_reviser, p.nouvelles_cartes, p.propositions), (True, False, False))
        html = self.client.get(reverse("anki_review:notifications")).content.decode()
        self.assertIn('name="propositions"', html)
