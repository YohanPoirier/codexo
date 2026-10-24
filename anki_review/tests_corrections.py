"""Corrections issues de la revue du code (octobre 2026)."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Classe, User
from exercises.models import Exercise, Theme

from .models import Card, Deck, Note, PropositionModification

CONFIG = dict(
    PAS_A_PAS_ELEVES=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)


def eleve(nom):
    u = User.objects.create_user(nom, "mdp-test-solide-1", role=User.ELEVE)
    u.a_vu_intro_pas_a_pas = True
    u.save()
    return u


@override_settings(**CONFIG)
class RevisionTests(TestCase):
    def setUp(self):
        self.eleve = eleve("e-rev")
        self.deck = Deck.objects.create(nom="Optique", slug="optique")
        self.client.force_login(self.eleve)
        self.url = reverse("anki_review:reviser", args=["optique"])

    def _carte(self, q="Q"):
        note = Note.objects.create(deck=self.deck, question=q, reponse="R")
        return Card.objects.get(note=note, etudiant=self.eleve) if Card.objects.filter(
            note=note, etudiant=self.eleve).exists() else Card.objects.create(note=note, etudiant=self.eleve)

    def test_reponse_envoyee_deux_fois_ne_compte_qu_une_fois(self):
        carte = self._carte()
        version = carte.prochaine_revision.isoformat()
        donnees = {"carte_id": carte.id, "reponse": "good", "version": version}
        self.client.post(self.url, donnees)
        carte.refresh_from_db()
        apres_une = (carte.repetitions, carte.intervalle_jours, carte.prochaine_revision)
        self.client.post(self.url, donnees)  # double appui / requête rejouée
        carte.refresh_from_db()
        self.assertEqual((carte.repetitions, carte.intervalle_jours, carte.prochaine_revision), apres_une)

    def test_reponse_sans_version_toujours_acceptee(self):
        carte = self._carte()
        self.client.post(self.url, {"carte_id": carte.id, "reponse": "good"})
        carte.refresh_from_db()
        self.assertEqual(carte.repetitions, 1)

    def test_page_de_revision_porte_la_version(self):
        carte = self._carte()
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="version"', html)
        self.assertIn(carte.prochaine_revision.isoformat(), html)

    def test_recharger_la_page_ne_fait_pas_avancer_la_file_d_apprentissage(self):
        rate = self._carte("rate")
        self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        avant = self.client.session["anki_file_apprentissage"]
        for _ in range(4):
            self.client.get(self.url)
        self.assertEqual(self.client.session["anki_file_apprentissage"], avant)

    def test_repondre_a_une_carte_ordinaire_fait_avancer_les_cartes_ratees(self):
        rate = self._carte("rate")
        autre = self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        self.client.post(self.url, {"carte_id": autre.id, "reponse": "good"})
        entree = next(e for e in self.client.session["anki_file_apprentissage"] if e["id"] == rate.id)
        self.assertEqual(entree["n"], 1)

    def test_restantes_ne_compte_pas_deux_fois_une_carte_ratee_et_echue(self):
        rate = self._carte("rate")
        self._carte("autre")
        self.client.post(self.url, {"carte_id": rate.id, "reponse": "again"})
        Card.objects.filter(pk=rate.pk).update(prochaine_revision=timezone.now())  # échue ET en file
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["restantes"], 2)


@override_settings(**CONFIG)
class PropositionDejaTraiteeTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user("prof-t", "mdp-test-solide-1", role=User.PROF)
        self.auteur = eleve("e-prop")
        deck = Deck.objects.create(nom="D", slug="d", cree_par=self.prof)
        self.note = Note.objects.create(deck=deck, question="actuelle", reponse="R", cree_par=self.prof)
        self.prop = PropositionModification.objects.create(
            note=self.note, auteur=self.auteur, question="ancienne proposition", reponse="R", tags="")
        self.client.force_login(self.prof)

    def test_proposition_refusee_ne_peut_plus_etre_acceptee(self):
        self.client.post(reverse("anki_review:refuser_proposition", args=[self.prop.id]))
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        self.note.refresh_from_db()
        self.prop.refresh_from_db()
        self.assertEqual(self.note.question, "actuelle")
        self.assertEqual(self.prop.statut, PropositionModification.Statut.REFUSEE)

    def test_proposition_acceptee_ne_s_applique_qu_une_fois(self):
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        Note.objects.filter(pk=self.note.pk).update(question="modifiée depuis")
        self.client.post(reverse("anki_review:accepter_proposition", args=[self.prop.id]))
        self.note.refresh_from_db()
        self.assertEqual(self.note.question, "modifiée depuis")


@override_settings(**CONFIG)
class ExercicesMasquesEtEnvoisTests(TestCase):
    def setUp(self):
        pcsi = Classe.objects.create(name="PCSI", slug="pcsi")
        psi = Classe.objects.create(name="PSI", slug="psi")
        self.theme = Theme.objects.create(name="T", slug="t")
        self.theme.enabled_for_classes.set([pcsi, psi])
        self.ex = Exercise.objects.create(
            theme=self.theme, title="E", slug="e", statement="x", function_name="f",
            solution_code="def f():\n    return 1\n")
        self.ex.enabled_for_classes.set([psi])  # réservé aux PSI
        self.pcsi = eleve("e-pcsi")
        self.pcsi.classe = pcsi
        self.pcsi.save()
        self.psi = eleve("e-psi")
        self.psi.classe = psi
        self.psi.save()

    def test_exercice_masque_ni_tests_ni_corrige(self):
        self.client.force_login(self.pcsi)
        self.assertEqual(self.client.get(reverse("exercise_tests", args=[self.ex.id])).status_code, 404)
        r = self.client.post(reverse("submit_result", args=[self.ex.id]),
                             {"code": "x", "success": "1"})
        self.assertEqual(r.status_code, 404)

    def test_exercice_ouvert_a_la_classe_fonctionne(self):
        self.client.force_login(self.psi)
        self.assertEqual(self.client.get(reverse("exercise_tests", args=[self.ex.id])).status_code, 200)

    def test_envois_mal_formes_donnent_400_et_pas_500(self):
        self.client.force_login(self.psi)
        url = reverse("submit_result", args=[self.ex.id])
        for corps in ("pas du json", "[1, 2]", '{"time_seconds": "abc"}', '{"code": 5}'):
            r = self.client.post(url, corps, content_type="application/json")
            self.assertEqual(r.status_code, 400, corps)
        r = self.client.post(url, {"code": "x", "time_seconds": "abc"})
        self.assertEqual(r.status_code, 400)
        ok = self.client.post(url, '{"code": "x", "success": true, "time_seconds": 3}',
                              content_type="application/json")
        self.assertEqual(ok.status_code, 200)


class RoleEtAccesTests(TestCase):
    def test_professeur_repasse_eleve_perd_is_staff(self):
        prof = User.objects.create_user("prof-r", "mdp-test-solide-1", role=User.PROF)
        self.assertTrue(prof.is_staff)
        prof.role = User.ELEVE
        prof.save()
        prof.refresh_from_db()
        self.assertFalse(prof.is_staff)

    def test_compte_technique_staff_sans_role_prof_garde_is_staff(self):
        technique = User.objects.create_user("tech-r", "mdp-test-solide-1", is_staff=True)
        technique.display_name = "Technique"
        technique.save()
        technique.refresh_from_db()
        self.assertTrue(technique.is_staff)

    def test_superuser_garde_ses_droits(self):
        admin = User.objects.create_superuser("adm-r", "mdp-test-solide-1")
        admin.role = User.ELEVE
        admin.save()
        admin.refresh_from_db()
        self.assertTrue(admin.is_staff and admin.is_superuser)


@override_settings(PAS_A_PAS_ELEVES=True, **{k: v for k, v in CONFIG.items() if k != "PAS_A_PAS_ELEVES"})
class IntroNeBloquePasAnkiTests(TestCase):
    def test_appli_anki_non_redirigee_vers_la_presentation(self):
        u = User.objects.create_user("e-intro", "mdp-test-solide-1", role=User.ELEVE)
        self.client.force_login(u)  # n'a pas encore vu la présentation
        reponse = self.client.get(reverse("anki_review:liste_decks"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.client.get(reverse("theme_list")).status_code, 302)  # le site, si
