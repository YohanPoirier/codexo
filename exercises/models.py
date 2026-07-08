from django.conf import settings
from django.db import models


class Theme(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Exercise(models.Model):
    theme = models.ForeignKey(Theme, related_name="exercises", on_delete=models.CASCADE)
    title = models.CharField(max_length=150)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=0)
    statement = models.TextField(help_text="Énoncé de l'exercice (Markdown simple accepté).")
    starter_code = models.TextField(
        blank=True, help_text="Code de départ affiché dans l'éditeur (ex: l'en-tête de la fonction)."
    )

    function_name = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Nom de la fonction que l'étudiant doit écrire (ex: 'triple'). "
            "Si rempli, les tests ci-dessous (section 'Test cases') sont utilisés automatiquement."
        ),
    )
    solution_code = models.TextField(
        blank=True,
        help_text=(
            "Code de correction : une implémentation complète et correcte de la fonction. "
            "S'il est rempli, le résultat attendu de chaque test est calculé automatiquement "
            "en exécutant ce code — tu n'as qu'à indiquer les arguments à tester, pas le résultat."
        ),
    )

    test_code = models.TextField(
        blank=True,
        help_text=(
            "Avancé : code Python de correction écrit à la main, exécuté après le code de l'étudiant. "
            "Doit définir une liste __RESULTS__ de tuples (bool_ok, message). "
            "Utilisé uniquement si 'function_name' est vide (ex: pour tester une variable plutôt qu'une fonction)."
        ),
    )

    class Meta:
        ordering = ["theme__order", "order"]
        unique_together = ("theme", "slug")

    def __str__(self):
        return f"{self.theme.name} — {self.title}"

    def build_test_code(self):
        """Renvoie le code de test à exécuter : généré depuis function_name + les TestCase liés
        (avec calcul automatique de l'attendu si solution_code est rempli), sinon test_code écrit à la main."""
        if not self.function_name:
            return self.test_code

        import json as _json

        fn = self.function_name
        cases_payload = [
            {"args": tc.args, "expected": tc.expected}
            for tc in self.test_cases.order_by("order", "id")
        ]
        cases_json = _json.dumps(cases_payload, ensure_ascii=False)
        solution_json = _json.dumps(self.solution_code or "", ensure_ascii=False)

        return (
            "__RESULTS__ = []\n"
            "import json as _json\n"
            f"_cases = _json.loads({cases_json!r})\n"
            f"_solution_src = _json.loads({solution_json!r})\n"
            "_solution_ns = {}\n"
            "if _solution_src:\n"
            "    exec(_solution_src, _solution_ns)\n"
            "for _case in _cases:\n"
            "    _args = _case.get('args', [])\n"
            "    _args_repr = ', '.join(repr(a) for a in _args)\n"
            f"    if _solution_ns and '{fn}' in _solution_ns:\n"
            "        try:\n"
            f"            _attendu = _solution_ns['{fn}'](*_args)\n"
            "        except Exception as e:\n"
            "            __RESULTS__.append((False, f\"Erreur dans le code de correction pour "
            + fn + "({_args_repr}) : {e}\"))\n"
            "            continue\n"
            "    else:\n"
            "        _attendu = _case.get('expected')\n"
            "    try:\n"
            f"        _obtenu = {fn}(*_args)\n"
            "        _ok = _obtenu == _attendu\n"
            "        __RESULTS__.append((_ok, f\""
            + fn + "({_args_repr}) doit valoir {_attendu!r} (obtenu : {_obtenu!r})\"))\n"
            "    except Exception as e:\n"
            "        __RESULTS__.append((False, f\""
            + fn + "({_args_repr}) a levé une erreur : {e}\"))\n"
        )


class TestCase(models.Model):
    """Un cas de test individuel pour un exercice basé sur une fonction."""

    exercise = models.ForeignKey(Exercise, related_name="test_cases", on_delete=models.CASCADE)
    args = models.JSONField(
        default=list,
        help_text="Arguments à passer à la fonction, en JSON. Ex : [2, 3] ou [[1, 2, 3]] pour un seul argument liste.",
    )
    expected = models.JSONField(
        blank=True,
        null=True,
        help_text="Résultat attendu — à remplir seulement si aucun 'code de correction' n'est fourni sur l'exercice.",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise.function_name}({self.args})"


class Result(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="results", on_delete=models.CASCADE)
    exercise = models.ForeignKey(Exercise, related_name="results", on_delete=models.CASCADE)
    submitted_code = models.TextField()
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        status = "réussi" if self.success else "échoué"
        return f"{self.user} — {self.exercise} ({status})"
