from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .models import Exercise, StepperUsage, TestCase as CasDeTest, Theme


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class StepCallsTests(TestCase):
    """Mode pas à pas (admins) : la vue exercise_tests fournit un appel par cas de test,
    mais seulement aux superusers, et seulement pour les exercices Python."""

    @classmethod
    def setUpTestData(cls):
        cls.theme = Theme.objects.create(name="Thème de test", slug="theme-test")
        cls.exercise = Exercise.objects.create(
            theme=cls.theme,
            title="Puissance",
            slug="puissance",
            statement="Calculer a puissance n.",
            function_name="puissance",
            solution_code="def puissance(a, n):\n    return a ** n\n",
        )
        CasDeTest.objects.create(exercise=cls.exercise, args="[2, 3]", order=1)
        CasDeTest.objects.create(exercise=cls.exercise, args="['x', None]", order=2)
        CasDeTest.objects.create(exercise=cls.exercise, args="pas du python", order=3)  # ignoré
        CasDeTest.objects.create(exercise=cls.exercise, args="5", order=4)  # pas une liste : ignoré

        cls.sql_exercise = Exercise.objects.create(
            theme=cls.theme, title="Requête", slug="requete", statement="x", kind=Exercise.SQL
        )

        cls.admin = User.objects.create_superuser("admin-test", "mdp-test-123")
        cls.prof = User.objects.create_user("prof-test", "mdp-test-123", role=User.PROF)
        cls.eleve = User.objects.create_user("eleve-test", "mdp-test-123", role=User.ELEVE)

    def get_json(self, user, exercise):
        self.client.force_login(user)
        response = self.client.get(reverse("exercise_tests", args=[exercise.id]))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_superuser_recoit_un_appel_par_cas_valide(self):
        data = self.get_json(self.admin, self.exercise)
        self.assertEqual(data["step_calls"], ["puissance(2, 3)", "puissance('x', None)"])

    def test_prof_et_eleve_ne_recoivent_pas_step_calls(self):
        for user in (self.prof, self.eleve):
            with self.subTest(user=user.identifiant):
                self.assertNotIn("step_calls", self.get_json(user, self.exercise))

    def test_exercice_sql_sans_step_calls_meme_pour_superuser(self):
        self.assertNotIn("step_calls", self.get_json(self.admin, self.sql_exercise))

    def test_le_reste_de_la_reponse_est_inchange(self):
        data = self.get_json(self.eleve, self.exercise)
        self.assertEqual(set(data), {"starter_code", "test_code", "solution_code"})

    def test_page_superuser(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("exercise_stepper", args=[self.theme.slug, self.exercise.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="stepper-code"')

    def test_page_refusee_aux_autres(self):
        url = reverse("exercise_stepper", args=[self.theme.slug, self.exercise.slug])
        for user in (self.prof, self.eleve):
            self.client.force_login(user)
            self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_page_sql_et_inconnu_404(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("exercise_stepper", args=[self.theme.slug, self.sql_exercise.slug]))
        self.assertEqual(r.status_code, 404)
        r = self.client.get(reverse("exercise_stepper", args=[self.theme.slug, "inconnu"]))
        self.assertEqual(r.status_code, 404)

    def test_bouton_sur_la_page_exercice(self):
        url = reverse("exercise_detail", args=[self.theme.slug, self.exercise.slug])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), 'id="stepper-btn"')
        self.client.force_login(self.eleve)
        self.assertNotContains(self.client.get(url), 'id="stepper-btn"')


class ErreurPendantUnTestTests(TestCase):
    """Une erreur levée par la fonction de l'étudiant pendant un test indique son type et la
    ligne du code de l'étudiant (comme dans exercise.js : code de l'élève puis code de test,
    exécutés dans le même espace de noms)."""

    def lancer(self, code_etudiant):
        theme = Theme.objects.create(name="T", slug="t")
        exercise = Exercise.objects.create(
            theme=theme, title="Ex", slug="ex", statement="x", function_name="f",
            solution_code="def f(n):\n    return n\n",
        )
        CasDeTest.objects.create(exercise=exercise, args="[3]", order=1)
        ns = {"__RESULTS__": [], "__STUDENT_CODE__": code_etudiant}
        exec(code_etudiant, ns)
        exec(exercise.build_test_code(), ns)
        return ns["__RESULTS__"]

    def test_type_et_ligne_dans_le_code_de_l_etudiant(self):
        code = "def aide(L, i):\n    return L[i]\n\ndef f(n):\n    L = [1, 2]\n    return aide(L, n)\n"
        (ok, msg, _), = self.lancer(code)
        self.assertFalse(ok)
        self.assertEqual(msg, "f(3) a levé une erreur : IndexError: list index out of range (ligne 2)")

    def test_erreur_sans_message(self):
        (ok, msg, _), = self.lancer("def f(n):\n    raise StopIteration\n")
        self.assertEqual(msg, "f(3) a levé une erreur : StopIteration (ligne 2)")

    def test_resultat_correct_inchange(self):
        (ok, msg, _), = self.lancer("def f(n):\n    return n\n")
        self.assertTrue(ok)


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PasAPasTraficTests(TestCase):
    """Les clics Avancer/Reculer envoyés par la page pas à pas sont additionnés, par jour et
    par élève, dans la colonne « Pas à pas » de la page Trafic (le staff n'y est pas compté)."""

    @classmethod
    def setUpTestData(cls):
        theme = Theme.objects.create(name="T", slug="t")
        cls.exercise = Exercise.objects.create(
            theme=theme, title="Ex", slug="ex", statement="x", function_name="f",
            solution_code="def f(n):\n    return n\n",
        )
        cls.eleve = User.objects.create_user("eleve-pap", "mdp-test-123", role=User.ELEVE)
        cls.prof = User.objects.create_user("prof-pap", "mdp-test-123", role=User.PROF)

    def envoyer(self, user, steps):
        self.client.force_login(user)
        return self.client.post(reverse("stepper_usage", args=[self.exercise.id]), {"steps": steps})

    def test_envois_additionnes_dans_trafic(self):
        self.assertEqual(self.envoyer(self.eleve, "7").status_code, 200)
        self.assertEqual(self.envoyer(self.eleve, "5").status_code, 200)
        self.client.force_login(self.prof)
        r = self.client.get(reverse("trafic"))
        self.assertContains(r, "<strong>12</strong> étapes de pas à pas", html=False)
        self.assertContains(r, ">Pas à pas</th>")

    def test_valeurs_invalides_refusees(self):
        for valeur in ("", "abc", "0", "-3"):
            with self.subTest(valeur=valeur):
                self.assertEqual(self.envoyer(self.eleve, valeur).status_code, 400)
        self.assertEqual(StepperUsage.objects.count(), 0)

    def test_get_refuse_et_anonyme_redirige(self):
        self.client.force_login(self.eleve)
        self.assertEqual(self.client.get(reverse("stepper_usage", args=[self.exercise.id])).status_code, 405)
        self.client.logout()
        r = self.client.post(reverse("stepper_usage", args=[self.exercise.id]), {"steps": "3"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StepperUsage.objects.count(), 0)


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class OuvertureAuxElevesTests(TestCase):
    """Réglage PAS_A_PAS_ELEVES : ouvre le pas à pas aux élèves et leur montre UNE fois la page
    de présentation. Désactivé, rien ne change pour eux."""

    @classmethod
    def setUpTestData(cls):
        cls.theme = Theme.objects.create(name="T", slug="t")
        cls.exercise = Exercise.objects.create(
            theme=cls.theme, title="Ex", slug="ex", statement="x", function_name="f",
            solution_code="def f(n):\n    return n\n",
        )
        CasDeTest.objects.create(exercise=cls.exercise, args="[3]", order=1)
        cls.eleve = User.objects.create_user("eleve-ouv", "mdp-test-123", role=User.ELEVE)
        cls.prof = User.objects.create_user("prof-ouv", "mdp-test-123", role=User.PROF)

    def url_stepper(self):
        return reverse("exercise_stepper", args=[self.theme.slug, self.exercise.slug])

    def test_ferme_par_defaut(self):
        self.client.force_login(self.eleve)
        self.assertEqual(self.client.get(reverse("theme_list")).status_code, 200)  # pas de redirection
        self.assertEqual(self.client.get(self.url_stepper()).status_code, 302)
        data = self.client.get(reverse("exercise_tests", args=[self.exercise.id])).json()
        self.assertNotIn("step_calls", data)

    @override_settings(PAS_A_PAS_ELEVES=True)
    def test_ouvert_presentation_une_seule_fois(self):
        self.client.force_login(self.eleve)
        r = self.client.get(reverse("guide"))
        self.assertRedirects(r, reverse("intro_pas_a_pas") + "?next=%2Fguide%2F", fetch_redirect_response=False)
        # Ni les appels d'API ni les envois de formulaire ne sont redirigés.
        self.assertEqual(self.client.get(reverse("exercise_tests", args=[self.exercise.id])).status_code, 200)
        r = self.client.post(reverse("intro_pas_a_pas"), {"next": "/guide/"})
        self.assertRedirects(r, "/guide/", fetch_redirect_response=False)
        self.eleve.refresh_from_db()
        self.assertTrue(self.eleve.a_vu_intro_pas_a_pas)
        self.assertEqual(self.client.get(reverse("guide")).status_code, 200)
        self.assertEqual(self.client.get(self.url_stepper()).status_code, 200)
        data = self.client.get(reverse("exercise_tests", args=[self.exercise.id])).json()
        self.assertEqual(data["step_calls"], ["f(3)"])

    @override_settings(PAS_A_PAS_ELEVES=True)
    def test_suite_externe_ignoree(self):
        self.client.force_login(self.eleve)
        r = self.client.post(reverse("intro_pas_a_pas"), {"next": "https://exemple.com/"})
        self.assertRedirects(r, reverse("theme_list"), fetch_redirect_response=False)

    def test_guide_sans_section_pas_a_pas_si_ferme(self):
        self.client.force_login(self.eleve)
        r = self.client.get(reverse("guide"))
        self.assertNotContains(r, "Le mode pas à pas")
        self.assertNotContains(r, "Progression")

    @override_settings(PAS_A_PAS_ELEVES=True)
    def test_guide_avec_lien_si_ouvert(self):
        self.eleve.a_vu_intro_pas_a_pas = True
        self.eleve.save()
        self.client.force_login(self.eleve)
        r = self.client.get(reverse("guide"))
        self.assertContains(r, "Le mode pas à pas")
        self.assertContains(r, 'href="%s"' % reverse("intro_pas_a_pas"))

    @override_settings(PAS_A_PAS_ELEVES=True)
    def test_staff_non_redirige(self):
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(reverse("guide")).status_code, 200)
