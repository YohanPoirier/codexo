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
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/appareil-{i}",
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

    def abonner(self, utilisateur, i=1, appli="anki"):
        s = _abonnement_navigateur(i)
        return AbonnementPush.objects.create(
            etudiant=utilisateur, endpoint=s["endpoint"], appli=appli,
            p256dh=s["keys"]["p256dh"], auth=s["keys"]["auth"])


class ContenuTests(Base):
    def test_messages(self):
        self.assertIsNone(notifications.message_revisions(0))
        self.assertIsNone(notifications.message_nouvelles(0))
        self.assertEqual(notifications.message_revisions(1)["corps"], "Tu as 1 carte à réviser.")
        m = notifications.message_revisions(12)
        self.assertEqual(m["corps"], "Tu as 12 cartes à réviser.")
        self.assertEqual(m["url"], reverse("anki_review:liste_decks"))
        m = notifications.message_nouvelles(3)
        self.assertIn("3 nouvelles cartes", m["corps"])
        self.assertEqual(m["url"], reverse("anki_review:partage_etudiants"))
        self.assertNotEqual(m["tag"], notifications.message_revisions(1)["tag"])

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


def _heure_locale(jour, heure):
    """Instant (aware) correspondant à `jour` (0 = lundi) à `heure` h, heure de Paris, en
    semaine du 19 octobre 2026 (lundi)."""
    from datetime import datetime
    return timezone.make_aware(datetime(2026, 10, 19 + jour, heure, 0))


@override_settings(**CONFIG)
class PlanificationTests(Base):
    """Passage horaire : révisions au jour/heure choisis, nouvelles cartes tous les jours à 20 h."""

    def setUp(self):
        self.abonnement = self.abonner(self.eleve)
        self.note_due = self.note(il_y_a=timedelta(days=30))
        # Due bien avant la semaine fictive des tests (19-25 octobre 2026).
        Card.objects.create(note=self.note_due, etudiant=self.eleve,
                            prochaine_revision=_heure_locale(0, 0) - timedelta(days=30))

    def passage(self, maintenant, **kw):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_planifie(maintenant=maintenant, **kw)
        return r, [c.args[1]["titre"] for c in envoi.call_args_list]

    def test_revisions_au_jour_et_a_l_heure_choisis(self):
        # Par défaut : dimanche 18 h.
        self.assertEqual(self.passage(_heure_locale(6, 17))[1], [])
        r, titres = self.passage(_heure_locale(6, 18))
        self.assertEqual(titres, ["Cartes à réviser"])
        self.assertIsNotNone(PreferencesNotification.pour(self.eleve).dernier_rappel_revisions)
        # Relancé dans la même heure : rien de plus.
        self.assertEqual(self.passage(_heure_locale(6, 18) + timedelta(minutes=20))[1], [])
        # Autre jour à 18 h : rien.
        self.assertEqual(self.passage(_heure_locale(2, 18))[1], [])

    def test_tous_les_jours(self):
        prefs = PreferencesNotification.pour(self.eleve)
        prefs.jour_revisions, prefs.heure_revisions = PreferencesNotification.TOUS_LES_JOURS, 7
        prefs.save()
        for jour in (0, 3, 5):
            self.assertEqual(self.passage(_heure_locale(jour, 7))[1], ["Cartes à réviser"])

    def test_nouvelles_cartes_a_20h_une_seule_fois(self):
        maintenant = _heure_locale(2, 20)   # tous les jours à 20 h
        nouvelle = self.note()
        nouvelle.partagee_le = maintenant - timedelta(hours=3)
        nouvelle.save(update_fields=["partagee_le"])
        self.assertEqual(self.passage(maintenant - timedelta(hours=1))[1], [])   # 19 h
        r, titres = self.passage(maintenant)
        self.assertEqual(titres, ["Nouvelles cartes"])
        self.assertEqual(r[0]["nouvelles"], 1)
        # Le lendemain à 20 h : déjà annoncée.
        r, titres = self.passage(maintenant + timedelta(days=1))
        self.assertEqual(titres, [])

    def test_simulation_n_envoie_ni_n_enregistre(self):
        with mock.patch("anki_review.notifications.envoyer_push") as envoi:
            r = notifications.envoyer_planifie(simulation=True, maintenant=_heure_locale(6, 18))
        envoi.assert_not_called()
        self.assertEqual(r[0]["statut"], "simulation (rien envoyé)")
        self.assertIsNone(PreferencesNotification.pour(self.eleve).dernier_rappel_revisions)

    def test_preferences_respectees(self):
        prefs = PreferencesNotification.pour(self.eleve)
        prefs.cartes_a_reviser = False
        prefs.save()
        self.assertEqual(self.passage(_heure_locale(6, 18))[1], [])

    def test_force_ignore_le_creneau(self):
        r, titres = self.passage(_heure_locale(1, 9), force=True)
        self.assertEqual(titres, ["Cartes à réviser"])

    def test_prof_abonne_traite_comme_un_eleve_non_abonnes_ignores(self):
        self.abonner(self.prof, 2)
        Card.objects.create(note=self.note_due, etudiant=self.autre)  # élève sans abonnement
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok"):
            r = notifications.envoyer_planifie(maintenant=_heure_locale(6, 20), force=True)
        self.assertEqual({x["etudiant"] for x in r}, {self.eleve, self.prof})
        ligne_prof = next(x for x in r if x["etudiant"] == self.prof)
        self.assertEqual(ligne_prof["nouvelles"], 0)  # ses propres cartes partagées ne comptent pas

    def test_echec_total_ne_marque_pas_le_creneau(self):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="erreur"):
            r = notifications.envoyer_planifie(maintenant=_heure_locale(6, 18))
        self.assertIn("échec de l'envoi", r[0]["statut"])
        self.assertIsNone(PreferencesNotification.pour(self.eleve).dernier_rappel_revisions)

    def test_reglages_jour_heure_enregistres(self):
        self.client.force_login(self.eleve)
        self.client.post(reverse("anki_review:notifications_preferences"), {
            "cartes_a_reviser": "on", "jour_revisions": "7", "heure_revisions": "21",
            "nouvelles_cartes": "on",
        })
        p = PreferencesNotification.pour(self.eleve)
        self.assertEqual((p.jour_revisions, p.heure_revisions), (7, 21))
        # Valeurs hors liste : ignorées.
        self.client.post(reverse("anki_review:notifications_preferences"),
                         {"jour_revisions": "9", "heure_revisions": "3"})
        p.refresh_from_db()
        self.assertEqual((p.jour_revisions, p.heure_revisions), (7, 21))

    def test_commande(self):
        sortie = StringIO()
        call_command("envoyer_notifications", "--simulation", "--force", stdout=sortie)
        texte = sortie.getvalue()
        self.assertIn("eleve-notif", texte)
        self.assertIn("1 à réviser, 0 nouvelles", texte)

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

    def test_charge_anki_badge_sans_grande_icone(self):
        abonnement = self.abonner(self.eleve)
        with mock.patch("pywebpush.webpush", return_value=mock.Mock(status_code=201)) as envoi:
            notifications.envoyer_push(abonnement, {"titre": "T", "corps": "C", "url": "/anki/"})
        charge = json.loads(envoi.call_args.kwargs["data"])
        self.assertIn("transparent-192", charge["icone"])  # l'icône de l'appli Anki s'affiche déjà
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
                      {"endpoint": "https://127.0.0.1/x", "keys": {"p256dh": "a", "auth": "b"}},
                      {"endpoint": "https://fcm.googleapis.com.evil.fr/x", "keys": {"p256dh": "a", "auth": "b"}},
                      {"endpoint": "https://fcm.googleapis.com@evil.fr/x", "keys": {"p256dh": "a", "auth": "b"}},
                      {"endpoint": "https://fcm.googleapis.com:8443/x", "keys": {"p256dh": "a", "auth": "b"}},
                      {"endpoint": "https://fcm.googleapis.com/1", "keys": {"p256dh": "", "auth": "b"}},
                      {"endpoint": "https://fcm.googleapis.com/" + "a" * 2100, "keys": {"p256dh": "a", "auth": "b"}}):
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
            self.assertIn("/anki/connexion/", r["Location"])
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

        # Prof : mêmes bandeau et réglages que les élèves.
        self.client.force_login(self.prof)
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), "notif-invitation")
        page = self.client.get(reverse("anki_review:notifications"))
        for champ in ("cartes_a_reviser", "nouvelles_cartes", "propositions"):
            self.assertContains(page, f'name="{champ}"')
        self.assertContains(page, "les autres professeurs")

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

@override_settings(**CONFIG, NOTIFICATIONS_CODEXO=True)
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
        self.abonner(self.eleve_classe, 10, appli="codexo")  # abonnement pris depuis Codexo

    def exercice(self, titre, ouvert_a=None, theme=None):
        ex = self.Exercise.objects.create(
            theme=theme or self.theme, title=titre, slug=titre.lower().replace(" ", "-"),
            statement="x", function_name="f", solution_code="def f():\n    return 1\n")
        ex.enabled_for_classes.add(ouvert_a or self.classe)
        return ex

    def passage(self, **kw):
        kw.setdefault("maintenant", _heure_locale(2, 10))   # mercredi 10 h : aucun créneau Anki
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_planifie(**kw)
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
        Card.objects.create(note=note, etudiant=self.eleve_classe,
                            prochaine_revision=_heure_locale(0, 0) - timedelta(days=30))
        r, envoi = self.passage(force=True)
        messages_envoyes = [c.args[1] for c in envoi.call_args_list]
        self.assertEqual(len(messages_envoyes), 2)
        anki, codexo = messages_envoyes
        self.assertNotIn("appli", anki)
        self.assertEqual(codexo["appli"], "codexo")
        self.assertEqual(codexo["corps"], "Nouvel exercice : « Nouveau ».")
        self.assertTrue(nouveau.pk)
        self.assertEqual(r[0]["exercices"], 1)
        self.assertIn("Révisions : ", r[0]["statut"])
        self.assertIn("Exercices : ", r[0]["statut"])
        # Annoncé une fois : le passage suivant ne le répète pas.
        r, envoi = self.passage(force=True, maintenant=_heure_locale(2, 12))
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
            r = notifications.envoyer_planifie(force=True, maintenant=_heure_locale(2, 11))
        self.assertIn("échec de l'envoi", r[0]["statut"])
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

        self.client.force_login(self.prof)  # mêmes bandeau et réglage que les élèves
        self.assertContains(self.client.get(reverse("theme_list")), "cx-notif-invitation")
        self.assertContains(self.client.get(reverse("notifications_codexo")), 'name="nouveaux_exercices"')

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


@override_settings(**CONFIG, NOTIFICATIONS_CODEXO=False)
class CodexoDesactiveTests(Base):
    """Tant que NOTIFICATIONS_CODEXO est faux : ni bandeau, ni page, ni lien, ni envoi."""

    def setUp(self):
        from accounts.models import Classe
        from exercises.models import Exercise, Theme
        self.classe = Classe.objects.create(name="PCSI test", slug="pcsi-test")
        self.theme = Theme.objects.create(name="Récursivité", slug="rec-notif")
        self.theme.enabled_for_classes.add(self.classe)
        self.Exercise = Exercise
        self.eleve_classe = User.objects.create_user(
            "eleve-classe", "mdp-test-123", role=User.ELEVE, classe=self.classe)
        self.abonner(self.eleve_classe, 9)

    def test_interface_masquee(self):
        self.client.force_login(self.eleve_classe)
        accueil = self.client.get(reverse("theme_list"))
        self.assertNotContains(accueil, "cx-notif-invitation")
        self.assertNotContains(accueil, reverse("notifications_codexo"))
        self.assertEqual(self.client.get(reverse("notifications_codexo")).status_code, 404)
        self.assertEqual(self.client.post(reverse("notifications_codexo_preferences")).status_code, 404)

    def test_anki_inchange(self):
        self.client.force_login(self.eleve_classe)
        self.assertContains(self.client.get(reverse("anki_review:liste_decks")), "notif-invitation")
        self.assertEqual(self.client.get(reverse("anki_review:notifications")).status_code, 200)

    def test_pas_de_message_codexo_mais_l_etat_avance(self):
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok"):
            notifications.envoyer_planifie(maintenant=_heure_locale(2, 10))  # état de départ
        ex = self.Exercise.objects.create(
            theme=self.theme, title="Nouveau", slug="nouveau", statement="x",
            function_name="f", solution_code="def f():\n    return 1\n")
        ex.enabled_for_classes.add(self.classe)
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            r = notifications.envoyer_planifie(force=True, maintenant=_heure_locale(2, 11))
        envoi.assert_not_called()
        self.assertEqual(r[0]["exercices"], 0)
        self.assertIn(ex.id, PreferencesNotification.pour(self.eleve_classe).exercices_connus)


@override_settings(**CONFIG)
class ServiceWorkerAnkiTests(Base):
    """Service worker propre à Anki (/anki/sw.js), pour tous les comptes."""

    def test_script_servi_sans_connexion(self):
        for url in ("/sw.js", "/anki/sw.js"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn("javascript", r["Content-Type"])
            self.assertIn("notificationclick", r.content.decode())

    def test_service_worker_anki_pour_tous(self):
        for utilisateur in (self.prof, self.eleve):
            self.client.force_login(utilisateur)
            page = self.client.get(reverse("anki_review:notifications")).content.decode()
            self.assertIn("data-sw-anki", page)
            self.assertIn('data-sw="/anki/sw.js"', page)
            self.assertIn('data-scope="/anki/"', page)
        # Codexo garde le service worker de la racine.
        page = self.client.get(reverse("theme_list")).content.decode()
        self.assertNotIn("data-sw-anki", page)

    def _abonner_par_la_vue(self, i, **extra):
        s = _abonnement_navigateur(i)
        s.update(extra)
        return self.client.post(
            reverse("anki_review:notifications_abonner"), json.dumps(s), content_type="application/json"
        )

    def test_abonnement_note_son_appli(self):
        self.client.force_login(self.eleve)
        self._abonner_par_la_vue(1, appli="codexo")
        self._abonner_par_la_vue(2)                 # sans appli : Anki
        self._abonner_par_la_vue(3, appli="pirate")  # valeur inconnue : Anki
        self.assertEqual(
            sorted(AbonnementPush.objects.values_list("appli", flat=True)), ["anki", "anki", "codexo"]
        )

    def test_envoi_limite_aux_abonnements_de_l_appli(self):
        self.abonner(self.eleve, 1, appli="anki")
        self.abonner(self.eleve, 2, appli="codexo")
        with mock.patch("anki_review.notifications.envoyer_push", return_value="ok") as envoi:
            self.assertEqual(notifications.envoyer_message(self.eleve, {"titre": "t", "corps": "c", "url": "/anki/"}), 1)
            self.assertEqual(envoi.call_args.args[0].appli, "anki")
            self.assertEqual(notifications.envoyer_message(
                self.eleve, {"titre": "t", "corps": "c", "url": "/", "appli": "codexo"}), 1)
            self.assertEqual(envoi.call_args.args[0].appli, "codexo")

    def test_retrait_de_l_ancien_abonnement_seulement_s_il_est_anki(self):
        anki = self.abonner(self.eleve, 1, appli="anki")
        codexo = self.abonner(self.eleve, 2, appli="codexo")
        self.client.force_login(self.eleve)
        url = reverse("anki_review:notifications_desabonner")
        r = self.client.post(url, json.dumps({"endpoint": codexo.endpoint, "appli": "anki"}),
                             content_type="application/json")
        self.assertEqual(r.json()["supprimes"], 0)
        r = self.client.post(url, json.dumps({"endpoint": anki.endpoint, "appli": "anki"}),
                             content_type="application/json")
        self.assertEqual(r.json()["supprimes"], 1)
        self.assertEqual(list(AbonnementPush.objects.values_list("appli", flat=True)), ["codexo"])
