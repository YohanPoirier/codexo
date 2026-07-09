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
        help_text="Nom de la fonction que l'étudiant doit écrire (ex: 'triple').",
    )
    solution_code = models.TextField(
        help_text=(
            "Code de correction : une implémentation complète et correcte de la fonction. "
            "Le résultat attendu de chaque test (ci-dessous) est calculé automatiquement "
            "en exécutant ce code — tu n'as qu'à indiquer les arguments à tester."
        ),
    )

    class Meta:
        ordering = ["theme__order", "order"]
        unique_together = ("theme", "slug")

    def __str__(self):
        return f"{self.theme.name} — {self.title}"

    def build_test_code(self):
        """Génère le code de test : appelle solution_code pour calculer l'attendu de chaque
        TestCase, puis compare à ce que produit la fonction de l'étudiant."""
        import ast
        import json as _json

        fn = self.function_name
        cases_payload = []
        parse_errors = []

        for tc in self.test_cases.order_by("order", "id"):
            try:
                parsed = ast.literal_eval(tc.args)
                if not isinstance(parsed, (list, tuple)):
                    raise ValueError("les arguments doivent former une liste, ex: [2, 3]")
                cases_payload.append({"args": list(parsed)})
            except Exception as e:
                parse_errors.append(f"Test #{tc.order} : args invalide ({e})")

        cases_json = _json.dumps(cases_payload, ensure_ascii=False)
        errors_json = _json.dumps(parse_errors, ensure_ascii=False)
        solution_json = _json.dumps(self.solution_code or "", ensure_ascii=False)

        return (
            "__RESULTS__ = []\n"
            "import json as _json\n"
            f"_cases = _json.loads({cases_json!r})\n"
            f"_parse_errors = _json.loads({errors_json!r})\n"
            "for _err in _parse_errors:\n"
            "    __RESULTS__.append((False, f\"Erreur de configuration de l'exercice : {_err}\"))\n"
            f"_solution_src = _json.loads({solution_json!r})\n"
            "_solution_ns = {}\n"
            "exec(_solution_src, _solution_ns)\n"
            "for _case in _cases:\n"
            "    _args = _case.get('args', [])\n"
            "    _args_repr = ', '.join(repr(a) for a in _args)\n"
            "    try:\n"
            f"        _attendu = _solution_ns['{fn}'](*_args)\n"
            "    except Exception as e:\n"
            "        __RESULTS__.append((False, f\"Erreur dans le code de correction pour "
            + fn + "({_args_repr}) : {e}\"))\n"
            "        continue\n"
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
    """Un cas de test individuel pour un exercice (toujours basé sur une fonction)."""

    exercise = models.ForeignKey(Exercise, related_name="test_cases", on_delete=models.CASCADE)
    args = models.TextField(
        default="[]",
        help_text=(
            "Arguments à passer à la fonction, en syntaxe Python (pas JSON). "
            "Ex : [2, 3]  ou  ['bonjour']  ou  [True, None]  ou  [{'a': 1, 'b': 2}]  ou  [[1, 2, 3]]."
        ),
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def clean(self):
        import ast
        from django.core.exceptions import ValidationError

        try:
            parsed = ast.literal_eval(self.args)
        except Exception as e:
            raise ValidationError({"args": f"Syntaxe Python invalide : {e}"})
        if not isinstance(parsed, (list, tuple)):
            raise ValidationError({"args": "Les arguments doivent former une liste, ex: [2, 3]"})

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