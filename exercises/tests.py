from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .models import Exercise, TestCase as CasDeTest, Theme


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
