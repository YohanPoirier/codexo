from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Exercise, TestCase as CasDeTest, Theme


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
