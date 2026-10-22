import base64
import json
import os
from datetime import timedelta
from io import StringIO
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from py_vapid import Vapid

from accounts.models import User

from . import notifications
from .models import AbonnementPush, Card, Deck, Note, PreferencesNotification

STOCKAGE_SIMPLE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _b64url(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _cles_vapid():
    """Paire de clés de test, générée par la vraie commande."""
    sortie = StringIO()
    call_command("generer_cles_vapid", stdout=sortie)
    lignes = dict(
        ligne.split("=", 1) for ligne in sortie.getvalue().splitlines()
        if ligne.startswith("VAPID_")
    )
    return lignes["VAPID_PUBLIC_KEY"], lignes["VAPID_PRIVATE_KEY"]


PUBLIQUE, PRIVEE = _cles_vapid()
CONFIG = dict(
    STORAGES=STOCKAGE_SIMPLE, PAS_A_PAS_ELEVES=False,
    VAPID_PUBLIC_KEY=PUBLIQUE, VAPID_PRIVATE_KEY=PRIVEE, VAPID_CONTACT="mailto:test@example.com",
)


def _abonnement_navigateur(i=1):
    """Faux abonnement tel que le produit un navigateur (vraie clé P-256 + secret d'authentification)."""
    cle = ec.generate_private_key(ec.SECP256R1())
    p256dh = _b64url(cle.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return {"endpoint": f"https://push.example.com/send/appareil-{i}",
            "keys": {"p256dh": p256dh, "auth": _b64url(os.urandom(16))}}


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.prof = User.objects.create_user("prof-notif", "mdp-test-123", role=User.PROF)
        cls.eleve = User.objects.create_user("eleve-notif", "mdp-test-123", role=User.ELEVE)
        cls.autre = User.objects.create_user("autre-notif", "mdp-test-123", role=User.ELEVE)
        cls.deck = Deck.objects.create(nom="Optique", slug="optique-notif", cree_par=cls.prof)

    def note(self, partagee=True, cree_par=None, il_y_a=None, question="Q"):
        n = Note.objects.create(
            deck=self.deck, question=question, reponse="R",
            cree_par=cree_par or self.prof, partagee_avec_classe=partagee,
        )
        if partagee:
            n.partagee_le = timezone.now() - (il_y_a or timedelta(hours=1))
            n.save(update_fields=["partagee_le"])
        return n

    def abonner(self, utilisateur, i=1):
        s = _abonnement_navigateur(i)
        return AbonnementPush.objects.create(
            etudiant=utilisateur, endpoint=s["endpoint"],
            p256dh=s["keys"]["p256dh"], auth=s["keys"]["auth"])


class ContenuTests(Base):
    def test_messages(self):
        self.assertIsNone(notifications.construire_message(0, 0))
        m = notifications.construire_message(1, 0)
        self.assertEqual(m["corps"], "Tu as 1 carte à réviser.")
        m = notifications.construire_message(12, 0)
        self.assertEqual(m["corps"], "Tu as 12 cartes à réviser.")
        self.assertEqual(m["url"], reverse("anki_review:liste_decks"))
        m = notifications.construire_message(0, 3)
        self.assertIn("3 nouvelles cartes", m["corps"])
        self.assertEqual(m["url"], reverse("anki_review:partage_etudiants"))
        m = notifications.construire_message(12, 1)
        self.assertEqual(m["corps"], "12 cartes à réviser et 1 nouvelle carte à ajouter.")

    def test_cartes_a_reviser(self):
        n1, n2, n3 = self.note(), self.note(), self.note()
        Card.objects.create(note=n1, etudiant=self.eleve)  # due (échéance = maintenant)
        Card.objects.create(note=n2, etudiant=self.eleve,
                            prochaine_revision=timezone.now() + timedelta(days=3))  # pas due
        Card.objects.create(note=n3, etudiant=self.eleve, suspendue=True)  # suspendue
        Card.objects.create(note=n1, etudiant=self.autre)  # un autre élève
        self.assertEqual(notifications.compter_a_reviser(self.eleve), 1)

    def test_nouvelles_cartes(self):
        depuis = timezone.now() - timedelta(days=7)
        recente = self.note(il_y_a=timedelta(days=2))
        deja = self.note(il_y_a=timedelta(days=1))
        self.note(il_y_a=timedelta(days=20))                       # trop ancienne
        self.note(partagee=False)                                  # privée
        self.note(cree_par=self.autre, il_y_a=timedelta(days=1))   # partagée par un élève, pas un prof
        Card.objects.create(note=deja, etudiant=self.eleve)        # déjà ajoutée
        self.assertEqual(notifications.compter_nouvelles_cartes(self.eleve, depuis), 1)
        self.assertEqual(notifications.compter_nouvelles_cartes(self.autre, depuis), 2)
        self.assertTrue(recente.pk)


@override_settings(**CONFIG)
class HebdomadaireTests(Base):
    def setUp(self):
        self.abonnement = self.abonner(self.eleve)
        self.note_due = self.note(il_y_a=timedelta(days=30))
        Card.objects.create(note=self.note_due, etudiant=self.eleve)
        self.nouvelle = self.note(il_y_a=timedelta(days=2))

    def test_message_combine_envoye_une_fois(self):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["a_reviser"], r[0]["nouvelles"], r[0]["envoyes"]), (1, 1, 1))
        envoi.assert_called_once()
        self.assertEqual(envoi.call_args.args[1]["titre"], "Anki")
        self.assertIsNotNone(PreferencesNotification.pour(self.eleve).dernier_passage)

        # Deuxième lancement dans la foulée : ignoré.
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire()
        envoi.assert_not_called()
        self.assertEqual(r[0]["statut"], "déjà traité cette semaine")

        # Une semaine plus tard : les nouvelles cartes déjà annoncées ne reviennent pas.
        dans_8_jours = timezone.now() + timedelta(days=8)
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire(maintenant=dans_8_jours)
        self.assertEqual(r[0]["nouvelles"], 0)
        self.assertEqual(r[0]["a_reviser"], 1)
        self.assertEqual(envoi.call_args.args[1]["titre"], "Cartes à réviser")

    def test_simulation_n_envoie_ni_n_enregistre(self):
        with mock.patch("anki_review.notifications.envoyer_push") as envoi:
            r = notifications.envoyer_hebdomadaire(simulation=True)
        envoi.assert_not_called()
        self.assertEqual(r[0]["statut"], "simulation (rien envoyé)")
        self.assertIsNone(PreferencesNotification.pour(self.eleve).dernier_passage)

    def test_preferences_respectees(self):
        prefs = PreferencesNotification.pour(self.eleve)
        prefs.nouvelles_cartes = False
        prefs.save()
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire()
        self.assertEqual((r[0]["a_reviser"], r[0]["nouvelles"]), (1, 0))
        self.assertEqual(envoi.call_args.args[1]["titre"], "Cartes à réviser")

        prefs.cartes_a_reviser = False
        prefs.dernier_passage = None
        prefs.save()
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire()
        envoi.assert_not_called()
        self.assertEqual(r[0]["statut"], "rien à annoncer")

    def test_prof_et_non_abonnes_ignores(self):
        self.abonner(self.prof, 2)  # un prof abonné ne reçoit pas le message hebdomadaire
        Card.objects.create(note=self.note_due, etudiant=self.autre)  # élève sans abonnement
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok"):
            r = notifications.envoyer_hebdomadaire()
        self.assertEqual([x["etudiant"] for x in r], [self.eleve])

    def test_echec_total_ne_marque_pas_la_semaine_traitee(self):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="erreur"):
            r = notifications.envoyer_hebdomadaire()
        self.assertEqual(r[0]["statut"], "échec de l'envoi")
        self.assertIsNone(PreferencesNotification.pour(self.eleve).dernier_passage)

    def test_commande(self):
        sortie = StringIO()
        call_command("envoyer_notifications", "--simulation", stdout=sortie)
        texte = sortie.getvalue()
        self.assertIn("eleve-notif", texte)
        self.assertIn("1 à réviser, 1 nouvelles", texte)

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_commande_sans_cles(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("envoyer_notifications", stdout=StringIO())


@override_settings(**CONFIG)
class EnvoiPushTests(Base):
    def test_envoi_reel_chiffre_et_signe(self):
        """Vrai chiffrement + signature VAPID avec pywebpush ; seul l'appel réseau est simulé."""
        abonnement = self.abonner(self.eleve)
        reponse = mock.Mock(status_code=201, ok=True)
        with mock.patch("requests.post", return_value=reponse) as post:
            statut = notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C", "url": "/anki/"})
        self.assertEqual(statut, "ok")
        self.assertEqual(post.call_args.args[0], abonnement.endpoint)
        entetes = post.call_args.kwargs["headers"]
        self.assertTrue(entetes["authorization"].startswith("vapid t="))
        self.assertIn(f"k={PUBLIQUE}", entetes["authorization"])
        self.assertEqual(entetes["content-encoding"], "aes128gcm")
        self.assertEqual(entetes["ttl"], str(notifications.TTL_SECONDES))
        self.assertTrue(post.call_args.kwargs["data"])  # charge utile chiffrée

    def test_charge_contient_les_icones_d_anki(self):
        abonnement = self.abonner(self.eleve)
        with mock.patch("pywebpush.webpush", return_value=mock.Mock(status_code=201)) as envoi:
            notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C", "url": "/anki/"})
        charge = json.loads(envoi.call_args.kwargs["data"])
        self.assertIn("anki_review/icons/favicon-192", charge["icone"])
        self.assertIn("anki_review/icons/badge-96", charge["badge"])

    def _erreur(self, statut):
        from pywebpush import WebPushException
        return WebPushException("echec", response=mock.Mock(status_code=statut))

    def test_appareil_desinscrit_supprime(self):
        abonnement = self.abonner(self.eleve)
        with mock.patch("pywebpush.webpush", side_effect=self._erreur(410)):
            self.assertEqual(notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C"}), "mort")
        self.assertFalse(AbonnementPush.objects.filter(pk=abonnement.pk).exists())

    def test_erreur_temporaire_conserve_l_abonnement(self):
        abonnement = self.abonner(self.eleve)
        with mock.patch("pywebpush.webpush", side_effect=self._erreur(500)):
            self.assertEqual(notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C"}), "erreur")
        self.assertTrue(AbonnementPush.objects.filter(pk=abonnement.pk).exists())


@override_settings(**CONFIG)
class VuesTests(Base):
    def post_json(self, nom, corps):
        return self.client.post(reverse(nom), data=json.dumps(corps), content_type="application/json")

    def test_abonner_et_desabonner(self):
        self.client.force_login(self.eleve)
        s = _abonnement_navigateur()
        self.assertEqual(self.post_json("anki_review:notifications_abonner", s).status_code, 200)
        a = AbonnementPush.objects.get()
        self.assertEqual(a.etudiant, self.eleve)
        self.assertTrue(PreferencesNotification.objects.filter(etudiant=self.eleve).exists())

        # Même appareil, autre compte : l'abonnement change de propriétaire, sans doublon.
        self.client.force_login(self.autre)
        self.post_json("anki_review:notifications_abonner", s)
        self.assertEqual(AbonnementPush.objects.count(), 1)
        self.assertEqual(AbonnementPush.objects.get().etudiant, self.autre)

        # Un élève ne peut pas désabonner l'appareil d'un autre.
        self.client.force_login(self.eleve)
        self.post_json("anki_review:notifications_desabonner", {"endpoint": s["endpoint"]})
        self.assertEqual(AbonnementPush.objects.count(), 1)
        self.client.force_login(self.autre)
        self.post_json("anki_review:notifications_desabonner", {"endpoint": s["endpoint"]})
        self.assertEqual(AbonnementPush.objects.count(), 0)

    def test_abonnement_invalide_refuse(self):
        self.client.force_login(self.eleve)
        for corps in ({}, {"endpoint": "http://x", "keys": {"p256dh": "a", "auth": "b"}},
                      {"endpoint": "https://x.example/1", "keys": {"p256dh": "", "auth": "b"}},
                      {"endpoint": "https://x.example/" + "a" * 2100, "keys": {"p256dh": "a", "auth": "b"}}):
            self.assertEqual(self.post_json("anki_review:notifications_abonner", corps).status_code, 400, corps)
        r = self.client.post(reverse("anki_review:notifications_abonner"), data="pas du json",
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(AbonnementPush.objects.count(), 0)

    def test_connexion_exigee_et_post_seulement(self):
        for nom in ("notifications_abonner", "notifications_desabonner",
                    "notifications_preferences", "notifications_test"):
            r = self.client.post(reverse(f"anki_review:{nom}"))
            self.assertEqual(r.status_code, 302, nom)
            self.assertIn("/login/", r["Location"])
        self.client.force_login(self.eleve)
        self.assertEqual(self.client.get(reverse("anki_review:notifications_abonner")).status_code, 405)

    @override_settings(VAPID_PUBLIC_KEY="")
    def test_non_configure(self):
        self.client.force_login(self.eleve)
        r = self.client.post(reverse("anki_review:notifications_abonner"),
                             data=json.dumps(_abonnement_navigateur()), content_type="application/json")
        self.assertEqual(r.status_code, 503)
        page = self.client.get(reverse("anki_review:notifications"))
        self.assertContains(page, "pas encore activées")
        self.assertNotContains(self.client.get(reverse("anki_review:liste_decks")), "notif-invitation")

    def test_preferences(self):
        self.client.force_login(self.eleve)
        self.client.post(reverse("anki_review:notifications_preferences"), {"cartes_a_reviser": "on"})
        p = PreferencesNotification.pour(self.eleve)
        self.assertTrue(p.cartes_a_reviser)
        self.assertFalse(p.nouvelles_cartes)

    def test_pages_et_bandeau(self):
        self.client.force_login(self.eleve)
        page = self.client.get(reverse("anki_review:notifications"))
        self.assertContains(page, "Cet appareil")
        self.assertContains(page, "Ce que tu veux recevoir")
        self.assertContains(page, "data-test hidden")  # masqué tant que l'appareil n'est pas abonné
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), "notif-invitation")
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), PUBLIQUE)

        # Prof : pas de réglages hebdomadaires, mais le test reste possible.
        # (TEMPORAIRE : le bandeau est aussi visible aux professeurs ; à remettre en
        # assertNotContains en même temps que contexte_invitation.)
        self.client.force_login(self.prof)
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), "notif-invitation")
        page = self.client.get(reverse("anki_review:notifications"))
        self.assertContains(page, "qu'aux élèves")
        self.assertNotContains(page, "Ce que tu veux recevoir")

    def test_bouton_de_test(self):
        self.client.force_login(self.eleve)
        r = self.client.post(reverse("anki_review:notifications_test"), follow=True)
        self.assertContains(r, "Aucune notification envoyée")
        self.abonner(self.eleve)
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = self.client.post(reverse("anki_review:notifications_test"), follow=True)
        self.assertContains(r, "Notification envoyée sur 1 appareil")
        self.assertEqual(envoi.call_args.args[1]["titre"], "Notification de test")


@override_settings(STORAGES=STOCKAGE_SIMPLE, PAS_A_PAS_ELEVES=False)
class DatePartageTests(Base):
    def test_partage_note_pose_et_retire_la_date(self):
        note = self.note(partagee=False)
        self.client.force_login(self.prof)
        url = reverse("anki_review:partager_note_toggle", args=[note.id])
        self.client.post(url)
        note.refresh_from_db()
        self.assertTrue(note.partagee_avec_classe)
        self.assertLess(timezone.now() - note.partagee_le, timedelta(minutes=1))
        self.client.post(url)
        note.refresh_from_db()
        self.assertFalse(note.partagee_avec_classe)
        self.assertIsNone(note.partagee_le)

    def test_partage_du_paquet_pose_la_date(self):
        a, b = self.note(partagee=False), self.note(partagee=False)
        self.client.force_login(self.prof)
        self.client.post(reverse("anki_review:partager_paquet_toggle", args=[self.deck.id]))
        for n in (a, b):
            n.refresh_from_db()
            self.assertTrue(n.partagee_avec_classe)
            self.assertIsNotNone(n.partagee_le)

    def test_modifier_une_note_deja_partagee_ne_la_rend_pas_nouvelle(self):
        note = self.note(il_y_a=timedelta(days=40))
        note.question = "Modifiée"
        note.save()
        note.refresh_from_db()
        self.assertLess(timezone.now() - note.partagee_le, timedelta(days=41))
        self.assertGreater(timezone.now() - note.partagee_le, timedelta(days=39))


class ClesTests(TestCase):
    def test_cles_generees_utilisables(self):
        publique, privee = _cles_vapid()
        v = Vapid.from_string(privee)
        recalculee = _b64url(v.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.assertEqual(publique, recalculee)


# ---------------------------------------------------------------- Codexo : nouveaux exercices

@override_settings(**CONFIG)
class ExercicesTests(Base):
    """Notification Codexo : les exercices devenus visibles pour la classe de l'élève."""

    def setUp(self):
        from accounts.models import Classe
        from exercises.models import Exercise, Theme
        self.Exercise = Exercise
        self.classe = Classe.objects.create(name="PCSI test", slug="pcsi-test")
        self.autre_classe = Classe.objects.create(name="MP test", slug="mp-test")
        self.theme = Theme.objects.create(name="Récursivité", slug="recursivite-notif", order=1)
        self.theme.enabled_for_classes.add(self.classe)
        self.eleve_classe = User.objects.create_user(
            "eleve-classe", "mdp-test-123", role=User.ELEVE, classe=self.classe)
        self.abonner(self.eleve_classe, 9)

    def exercice(self, titre, ouvert_a=None, theme=None):
        ex = self.Exercise.objects.create(
            theme=theme or self.theme, title=titre, slug=titre.lower().replace(" ", "-"),
            statement="x", function_name="f", solution_code="def f():\n    return 1\n")
        ex.enabled_for_classes.add(ouvert_a or self.classe)
        return ex

    def passage(self, **kw):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_hebdomadaire(**kw)
        return r, envoi

    def test_visibilite_par_classe(self):
        a = self.exercice("Factorielle")
        self.exercice("Fibonacci", ouvert_a=self.autre_classe)      # ouvert à une autre classe
        theme_ferme = type(self.theme).objects.create(name="Fermé", slug="ferme-notif")
        self.exercice("Caché", theme=theme_ferme)                    # thème fermé à la classe
        self.assertEqual(notifications.exercices_visibles_ids(self.eleve_classe), {a.id})

    def test_messages(self):
        self.assertIsNone(notifications.construire_message_exercices([]))
        a, b, c, d = (self.exercice(t) for t in ("Un", "Deux", "Trois", "Quatre"))
        m = notifications.construire_message_exercices([a])
        self.assertEqual((m["titre"], m["corps"]), ("Nouvel exercice", "Nouvel exercice : « Un »."))
        self.assertEqual(m["url"], reverse("exercise_list", args=[self.theme.slug]))
        self.assertEqual(m["appli"], "codexo")
        m = notifications.construire_message_exercices([a, b, c])
        self.assertEqual(m["corps"], "3 nouveaux exercices : « Un », « Deux », « Trois ».")
        m = notifications.construire_message_exercices([a, b, c, d])
        self.assertEqual(m["corps"], "4 nouveaux exercices, dont « Un », « Deux » et « Trois ».")
        autre = type(self.theme).objects.create(name="Autre", slug="autre-notif")
        e = self.exercice("Cinq", theme=autre)
        self.assertEqual(notifications.construire_message_exercices([a, e])["url"], reverse("theme_list"))

    def test_premier_passage_sert_d_etat_de_depart(self):
        self.exercice("Existant")
        r, envoi = self.passage()
        envoi.assert_not_called()
        self.assertEqual(r[0]["exercices"], 0)
        prefs = PreferencesNotification.pour(self.eleve_classe)
        self.assertEqual(len(prefs.exercices_connus), 1)

    def test_nouvel_exercice_annonce_par_une_notification_codexo_separee(self):
        self.exercice("Existant")
        self.passage()
        # Un exercice ajouté + des cartes à réviser : deux messages distincts.
        nouveau = self.exercice("Nouveau")
        note = self.note(il_y_a=timedelta(days=30))
        Card.objects.create(note=note, etudiant=self.eleve_classe)
        r, envoi = self.passage(force=True)
        messages_envoyes = [c.args[1] for c in envoi.call_args_list]
        self.assertEqual(len(messages_envoyes), 2)
        anki, codexo = messages_envoyes
        self.assertNotIn("appli", anki)
        self.assertEqual(codexo["appli"], "codexo")
        self.assertEqual(codexo["corps"], "Nouvel exercice : « Nouveau ».")
        self.assertTrue(nouveau.pk)
        self.assertEqual(r[0]["exercices"], 1)
        self.assertIn("Anki : ", r[0]["statut"])
        self.assertIn("Codexo : ", r[0]["statut"])
        # Annoncé une fois : le passage suivant ne le répète pas.
        r, envoi = self.passage(force=True)
        self.assertEqual(r[0]["exercices"], 0)
        self.assertEqual(envoi.call_count, 1)  # seulement les cartes à réviser (Anki)

    def test_exercice_rendu_visible_apres_coup(self):
        ex = self.exercice("Plus tard", ouvert_a=self.autre_classe)
        self.passage()
        ex.enabled_for_classes.add(self.classe)  # le prof l'ouvre à la classe
        r, envoi = self.passage(force=True)
        self.assertEqual(r[0]["exercices"], 1)
        self.assertEqual(envoi.call_args.args[1]["corps"], "Nouvel exercice : « Plus tard ».")

    def test_option_desactivee(self):
        self.passage()
        prefs = PreferencesNotification.pour(self.eleve_classe)
        prefs.nouveaux_exercices = False
        prefs.save()
        self.exercice("Nouveau")
        r, envoi = self.passage(force=True)
        envoi.assert_not_called()
        self.assertEqual(r[0]["statut"], "rien à annoncer")
        # Réactivée : l'exercice déjà passé pendant la coupure n'est pas annoncé après coup.
        prefs.refresh_from_db()
        prefs.nouveaux_exercices = True
        prefs.save()
        r, envoi = self.passage(force=True)
        self.assertEqual(r[0]["exercices"], 0)

    def test_echec_d_envoi_conserve_l_annonce_pour_la_semaine_suivante(self):
        self.passage()
        self.exercice("Nouveau")
        with mock.patch("anki_review.notifications.envoyer_push", return_value="erreur"):
            r = notifications.envoyer_hebdomadaire(force=True)
        self.assertEqual(r[0]["statut"], "échec de l'envoi")
        r, envoi = self.passage(force=True)
        self.assertEqual(r[0]["exercices"], 1)

    def test_simulation_n_avance_pas_l_etat(self):
        self.passage()
        self.exercice("Nouveau")
        r, envoi = self.passage(simulation=True, force=True)
        envoi.assert_not_called()
        self.assertEqual(r[0]["exercices"], 1)
        r, envoi = self.passage(force=True)
        self.assertEqual(r[0]["exercices"], 1)

    def test_charge_codexo(self):
        abonnement = AbonnementPush.objects.filter(etudiant=self.eleve_classe).first()
        with mock.patch("pywebpush.webpush", return_value=mock.Mock(status_code=201)) as envoi:
            notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C", "url": "/", "appli": "codexo"})
        charge = json.loads(envoi.call_args.kwargs["data"])
        self.assertEqual(charge["tag"], "codexo-nouveautes")
        self.assertRegex(charge["icone"], r"favicon-192")
        self.assertNotIn("anki_review", charge["icone"])
        self.assertRegex(charge["badge"], r"badge-96")
        self.assertNotIn("anki_review", charge["badge"])
        self.assertNotIn("appli", charge)

    def test_pages_codexo(self):
        self.client.force_login(self.eleve_classe)
        page = self.client.get(reverse("notifications_codexo"))
        self.assertContains(page, "Nouveaux exercices disponibles pour ta classe")
        self.assertContains(page, "data-test hidden")
        self.assertContains(self.client.get(reverse("theme_list")), "cx-notif-invitation")
        self.assertContains(self.client.get(reverse("theme_list")), reverse("notifications_codexo"))
        self.client.post(reverse("notifications_codexo_preferences"), {})
        self.assertFalse(PreferencesNotification.pour(self.eleve_classe).nouveaux_exercices)
        self.client.post(reverse("notifications_codexo_preferences"), {"nouveaux_exercices": "on"})
        self.assertTrue(PreferencesNotification.pour(self.eleve_classe).nouveaux_exercices)

        self.client.force_login(self.prof)
        # TEMPORAIRE : visible aussi aux professeurs (à remettre en assertNotContains).
        self.assertContains(self.client.get(reverse("theme_list")), "cx-notif-invitation")
        self.assertContains(self.client.get(reverse("notifications_codexo")), "qu'aux élèves")

    def test_connexion_exigee(self):
        for nom in ("notifications_codexo", "notifications_codexo_preferences"):
            self.assertEqual(self.client.get(reverse(nom)).status_code, 302)

    def test_bouton_de_test_codexo(self):
        self.client.force_login(self.eleve_classe)
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = self.client.post(reverse("anki_review:notifications_test"), {"appli": "codexo"})
        self.assertRedirects(r, reverse("notifications_codexo"), fetch_redirect_response=False)
        message = envoi.call_args.args[1]
        self.assertEqual(message["appli"], "codexo")
        self.assertEqual(message["url"], reverse("theme_list"))
