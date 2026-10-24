from django.test import TestCase

from .models import Exercise, TestCase as CasDeTest, Theme


class ArgumentsNonPartagesTests(TestCase):
    """Le corrigé et la fonction de l'élève doivent recevoir chacun leur PROPRE copie des
    arguments : sinon, un corrigé qui modifie sa liste « en place » fausse le test."""

    def _resultats(self, solution, code_eleve, args="[[1, 2, 3]]"):
        theme = Theme.objects.create(name="T", slug="t")
        exo = Exercise.objects.create(
            theme=theme, title="E", slug="e", statement="x", function_name="f", solution_code=solution)
        CasDeTest.objects.create(exercise=exo, args=args, order=1)
        espace = {}
        exec(code_eleve + "\n" + exo.build_test_code(), espace)
        return espace["__RESULTS__"]

    def test_corrige_qui_modifie_son_argument_ne_penalise_pas_un_eleve_correct(self):
        solution = "def f(l):\n    l.append(0)\n    return l[:]\n"
        eleve_correct = "def f(l):\n    return l + [0]\n"
        (ok, _msg, _prints), = self._resultats(solution, eleve_correct)
        self.assertTrue(ok)

    def test_corrige_qui_modifie_son_argument_ne_valide_pas_un_eleve_faux(self):
        solution = "def f(l):\n    l.append(0)\n    return l[:]\n"
        eleve_faux = "def f(l):\n    return l\n"  # oublie d'ajouter 0
        (ok, _msg, _prints), = self._resultats(solution, eleve_faux)
        self.assertFalse(ok)

    def test_eleve_qui_modifie_son_argument_ne_change_pas_l_attendu_affiche(self):
        solution = "def f(l):\n    return sorted(l)\n"
        eleve = "def f(l):\n    l.sort()\n    return l\n"
        (ok, msg, _prints), = self._resultats(solution, eleve, args="[[3, 1, 2]]")
        self.assertTrue(ok)
        self.assertIn("f([3, 1, 2])", msg)
