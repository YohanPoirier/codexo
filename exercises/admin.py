from django.contrib import admin

from codexo.admin_mixins import SimplifieIndicationCtrlMixin

from .models import Theme, Exercise, TestCase, Hint


class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0
    fields = ("title", "slug", "order")


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 1
    fields = ("args", "order")


class HintInline(admin.TabularInline):
    model = Hint
    extra = 1
    fields = ("text", "order")


# SimplifieIndicationCtrlMixin : voir codexo/admin_mixins.py (mutualisé avec accounts/admin.py,
# où le même souci — le rappel "sur un Mac" hors-sujet — a été retrouvé sur d'autres champs).


@admin.register(Theme)
class ThemeAdmin(SimplifieIndicationCtrlMixin, admin.ModelAdmin):
    CHAMPS_AVEC_INDICATION_CTRL_SIMPLIFIEE = ("enabled_for_classes",)

    list_display = ("name", "slug", "order")
    inlines = [ExerciseInline]
    filter_horizontal = ("enabled_for_classes",)
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "order")}),
        (
            "Base de données SQL partagée",
            {
                "fields": ("sql_setup",),
                "description": (
                    "Instructions SQL (CREATE TABLE + INSERT) utilisées par défaut par tous les "
                    "exercices SQL de ce thème."
                ),
            },
        ),
        (
            "Visibilité par classe",
            {
                "fields": ("enabled_for_classes",),
                "description": (
                    "Classes pour lesquelles ce thème (et donc tous ses exercices) est visible. "
                    "Vide par défaut = invisible pour tout le monde. Réglage habituellement fait "
                    "depuis la page /stats/visibilite/, ce champ sert surtout de secours."
                ),
            },
        ),
    )


@admin.register(Exercise)
class ExerciseAdmin(SimplifieIndicationCtrlMixin, admin.ModelAdmin):
    CHAMPS_AVEC_INDICATION_CTRL_SIMPLIFIEE = ("enabled_for_classes",)

    list_display = ("title", "theme", "kind", "order", "function_name")
    list_filter = ("theme", "kind")
    # Ordre naturel (Python avant SQL, il y a plus d'exercices Python) : "Cas de test"
    # s'affiche quand même juste après "Correction automatique — exercices Python" grâce
    # au template admin personnalisé (voir templates/admin/exercises/exercise/change_form.html),
    # qui déplace précisément cet inline — Django ne permet normalement pas d'intercaler un
    # inline entre deux fieldsets, seulement de les faire tous suivre après tous les autres.
    inlines = [TestCaseInline, HintInline]
    filter_horizontal = ("enabled_for_classes",)
    fieldsets = (
        (None, {"fields": ("theme", "title", "slug", "order", "kind")}),
        ("Contenu affiché à l'étudiant", {"fields": ("statement", "starter_code")}),
        (
            "Visibilité par classe",
            {
                "fields": ("enabled_for_classes",),
                "description": (
                    "Classes pour lesquelles CET exercice précis est visible (en plus du thème, qui "
                    "doit lui aussi être visible). Vide par défaut = invisible pour tout le monde. "
                    "Réglage habituellement fait depuis la page /stats/visibilite/, ce champ sert "
                    "surtout de secours."
                ),
            },
        ),
        (
            "Correction automatique — exercices Python",
            {
                "fields": (
                    "function_name", "solution_code", "require_recursive", "extra_test_code",
                ),
                "description": (
                    "Uniquement si Type = 'Python (fonction)'. Renseigner le nom de la fonction et "
                    "le code de correction ci-dessous, puis ajouter les cas de test (juste en "
                    "dessous) avec les arguments à essayer. Les deux derniers champs sont "
                    "optionnels (voir leur propre description)."
                ),
            },
        ),
        (
            "Correction automatique — exercices SQL",
            {
                "fields": ("sql_setup", "sql_solution"),
                "description": (
                    "Uniquement si Type = 'SQL (requête)'. Le champ sql_setup est optionnel ici : "
                    "laisser vide pour réutiliser automatiquement la base de données définie sur le "
                    "thème, et ne le remplir que si cet exercice a besoin de données différentes. "
                    "Le champ sql_solution est la requête correcte : le résultat attendu est calculé "
                    "automatiquement en l'exécutant, puis comparé à la requête de l'étudiant."
                ),
            },
        ),
    )

# Result, Abandonment et HintReveal ne sont plus enregistrés ici : leurs données restent en
# base et alimentent la page /stats/, mais elles n'ont plus besoin d'être gérées à la main
# depuis l'admin (pas de create/edit/delete pertinent pour ces journaux de suivi).
