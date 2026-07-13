from django.conf import settings
from django.db import models


class Theme(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    sql_setup = models.TextField(
        blank=True,
        help_text=(
            "[SQL] Base de données partagée par défaut pour tous les exercices SQL de ce thème "
            "(instructions CREATE TABLE + INSERT). Un exercice peut définir son propre 'sql_setup' "
            "pour utiliser des données différentes ponctuellement, sinon celui du thème est utilisé. "
            "Astuce : ajoute des commentaires SQL ('-- texte') après une table ou une colonne pour "
            "qu'ils apparaissent dans le résumé de schéma affiché aux étudiants."
        ),
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @property
    def schema_summary(self):
        """Résumé auto-généré (tables/colonnes/extrait de données) de la base SQL
        partagée de ce thème, pour affichage aux étudiants. Voir schema_utils.py."""
        from .schema_utils import summarize_sql_setup
        return summarize_sql_setup(self.sql_setup)


class Exercise(models.Model):
    PYTHON = "python"
    SQL = "sql"
    KIND_CHOICES = [
        (PYTHON, "Python (fonction)"),
        (SQL, "SQL (requête)"),
    ]

    theme = models.ForeignKey(Theme, related_name="exercises", on_delete=models.CASCADE)
    title = models.CharField(max_length=150)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=0)
    statement = models.TextField(help_text="Énoncé de l'exercice (Markdown simple accepté).")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=PYTHON)
    starter_code = models.TextField(
        blank=True,
        help_text="Code de départ affiché dans l'éditeur (l'en-tête de la fonction, ou un commentaire SQL).",
    )

    # --- Champs pour les exercices Python (kind=PYTHON) ---
    function_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="[Python] Nom de la fonction que l'étudiant doit écrire (ex: 'triple').",
    )
    solution_code = models.TextField(
        blank=True,
        help_text=(
            "[Python] Code de correction : une implémentation complète et correcte de la fonction. "
            "Le résultat attendu de chaque test (ci-dessous) est calculé automatiquement "
            "en exécutant ce code — tu n'as qu'à indiquer les arguments à tester."
        ),
    )

    # --- Champs pour les exercices SQL (kind=SQL) ---
    sql_setup = models.TextField(
        blank=True,
        help_text=(
            "[SQL] Optionnel : instructions SQL (CREATE TABLE + INSERT) propres à CET exercice, "
            "si tu veux des données différentes de celles du thème. Laisse vide pour réutiliser "
            "automatiquement le 'sql_setup' défini sur le thème."
        ),
    )
    sql_solution = models.TextField(
        blank=True,
        help_text=(
            "[SQL] La requête SQL correcte. Le résultat attendu est calculé automatiquement en "
            "l'exécutant sur les données de sql_setup, puis comparé à la requête de l'étudiant."
        ),
    )

    class Meta:
        ordering = ["theme__order", "order"]
        unique_together = ("theme", "slug")

    def __str__(self):
        return f"{self.theme.name} — {self.title}"

    @property
    def effective_sql_setup(self):
        """Le sql_setup à utiliser : celui de l'exercice s'il est défini, sinon celui du thème."""
        return self.sql_setup or self.theme.sql_setup

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.kind == self.PYTHON:
            if not self.function_name or not self.solution_code:
                raise ValidationError(
                    "Un exercice Python doit avoir un 'function_name' et un 'solution_code'."
                )
        elif self.kind == self.SQL:
            if not self.effective_sql_setup:
                raise ValidationError(
                    "Un exercice SQL doit avoir un 'sql_setup' (sur l'exercice ou sur son thème) "
                    "et une 'sql_solution'."
                )
            if not self.sql_solution:
                raise ValidationError("Un exercice SQL doit avoir une 'sql_solution'.")

    def build_test_code(self):
        if self.kind == self.SQL:
            return self._build_sql_test_code()
        return self._build_python_test_code()

    def _build_python_test_code(self):
        """Génère le code de test pour un exercice Python : appelle solution_code pour calculer
        l'attendu de chaque TestCase, puis compare à ce que produit la fonction de l'étudiant.

        Chaque entrée de __RESULTS__ est un triplet (ok, message, prints) : 'prints' contient
        tout ce que l'étudiant a affiché avec print() pendant CET appel précis, pour l'aider à
        se débugger (affiché ensuite dans un menu déroulant côté interface)."""
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

        template = '''__RESULTS__ = []
import json as _json, io as _io, contextlib as _contextlib
_cases = _json.loads(%(cases_json)r)
_parse_errors = _json.loads(%(errors_json)r)
for _err in _parse_errors:
    __RESULTS__.append((False, f"Erreur de configuration de l'exercice : {_err}", ""))
_solution_src = _json.loads(%(solution_json)r)
_solution_ns = {}
exec(_solution_src, _solution_ns)
for _case in _cases:
    _args = _case.get('args', [])
    _args_repr = ', '.join(repr(a) for a in _args)
    try:
        _attendu = _solution_ns['__FN__'](*_args)
    except Exception as e:
        __RESULTS__.append((False, f"Erreur dans le code de correction pour __FN__({_args_repr}) : {e}", ""))
        continue
    _out = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(_out):
            _obtenu = __FN__(*_args)
        _ok = _obtenu == _attendu
        __RESULTS__.append((_ok, f"__FN__({_args_repr}) doit valoir {_attendu!r} (obtenu : {_obtenu!r})", _out.getvalue()))
    except Exception as e:
        __RESULTS__.append((False, f"__FN__({_args_repr}) a levé une erreur : {e}", _out.getvalue()))
''' % {"cases_json": cases_json, "errors_json": errors_json, "solution_json": solution_json}

        return template.replace("__FN__", fn)

    def _build_sql_test_code(self):
        """Génère le code de test pour un exercice SQL : crée une base en mémoire depuis sql_setup,
        exécute sql_solution pour obtenir l'attendu, puis exécute la requête de l'étudiant
        (disponible dans __STUDENT_SQL__, texte brut non exécuté comme du Python) et compare.

        IMPORTANT : la comparaison NE trie PAS les lignes avant de comparer (contrairement à une
        version précédente qui faisait sorted(...) des deux côtés). Trier annulerait tout exercice
        portant sur ORDER BY, puisqu'une requête sans ORDER BY (ou avec le mauvais tri) donnerait
        alors le même résultat "trié" qu'une requête correcte. On compare donc les lignes dans
        l'ordre exact renvoyé par SQLite.

        Limite à connaître : pour une requête SANS ORDER BY, l'ordre des lignes n'est pas garanti
        par la norme SQL. En pratique, SQLite renvoie les lignes d'une requête simple (SELECT/WHERE
        sans jointure ni tri) dans l'ordre d'insertion, donc ça ne pose pas de problème ici — mais
        si un exercice sans ORDER BY se met à échouer de façon inexpliquée pour une requête
        pourtant correcte, c'est la première piste à vérifier."""
        import json as _json

        setup_json = _json.dumps(self.effective_sql_setup or "", ensure_ascii=False)
        solution_json = _json.dumps(self.sql_solution or "", ensure_ascii=False)

        return (
            "__RESULTS__ = []\n"
            "import sqlite3, json as _json\n"
            f"_setup_sql = _json.loads({setup_json!r})\n"
            f"_solution_sql = _json.loads({solution_json!r})\n"
            "\n"
            "def _run_query(sql_text):\n"
            "    _conn = sqlite3.connect(':memory:')\n"
            "    try:\n"
            "        _conn.executescript(_setup_sql)\n"
            "        _cur = _conn.cursor()\n"
            "        _cur.execute(sql_text)\n"
            "        _cols = [d[0] for d in _cur.description] if _cur.description else []\n"
            "        _rows = _cur.fetchall()\n"
            "        return _cols, _rows\n"
            "    finally:\n"
            "        _conn.close()\n"
            "\n"
            "try:\n"
            "    _attendu_cols, _attendu_rows = _run_query(_solution_sql)\n"
            "except Exception as e:\n"
            "    __RESULTS__.append((False, f\"Erreur dans la requête de correction : {e}\"))\n"
            "else:\n"
            "    try:\n"
            "        _obtenu_cols, _obtenu_rows = _run_query(__STUDENT_SQL__)\n"
            "    except Exception as e:\n"
            "        __RESULTS__.append((False, f\"Erreur dans ta requête SQL : {e}\"))\n"
            "    else:\n"
            "        # Comparaison SANS tri : l'ordre des lignes renvoyées compte, ce qui permet\n"
            "        # de vérifier un ORDER BY (voir docstring de cette méthode)\n"
            "        _ok = list(map(str, _obtenu_rows)) == list(map(str, _attendu_rows))\n"
            "        _msg = (\n"
            "            f\"{len(_attendu_rows)} ligne(s) attendue(s), {len(_obtenu_rows)} obtenue(s). \"\n"
            "            f\"Attendu (colonnes {_attendu_cols}) : {_attendu_rows[:5]}"
            "{'...' if len(_attendu_rows) > 5 else ''} | \"\n"
            "            f\"Obtenu (colonnes {_obtenu_cols}) : {_obtenu_rows[:5]}"
            "{'...' if len(_obtenu_rows) > 5 else ''}\"\n"
            "        )\n"
            "        __RESULTS__.append((_ok, _msg))\n"
        )


class Hint(models.Model):
    """Un indice optionnel pour un exercice, révélé progressivement à l'étudiant qui le demande
    (bouton "Voir un indice" côté interface, un indice à la fois, dans l'ordre)."""

    exercise = models.ForeignKey(Exercise, related_name="hints", on_delete=models.CASCADE)
    text = models.TextField(
        help_text="Texte de l'indice (Markdown simple accepté, comme pour l'énoncé).",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise.title} — indice #{self.order}"


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


class Abandonment(models.Model):
    """Enregistre qu'un étudiant a choisi d'abandonner un exercice pour voir la solution.
    Utilisé pour verrouiller une nouvelle tentative pendant 48h (voir ABANDON_LOCK_DURATION
    dans exercises/views.py) : le temps de digérer la solution plutôt que de la recopier
    immédiatement pour valider l'exercice sans l'avoir vraiment compris."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="abandonments", on_delete=models.CASCADE)
    exercise = models.ForeignKey(Exercise, related_name="abandonments", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} a abandonné {self.exercise} le {self.created_at:%d/%m/%Y %H:%M}"


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
