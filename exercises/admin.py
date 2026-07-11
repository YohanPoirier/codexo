from django.contrib import admin
from .models import Theme, Exercise, Result, TestCase, Hint, Abandonment


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


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order")
    inlines = [ExerciseInline]
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "order")}),
        (
            "Base de données SQL partagée",
            {
                "fields": ("sql_setup",),
                "description": (
                    "Instructions SQL (CREATE TABLE + INSERT) utilisées par défaut par tous les "
                    "exercices SQL de ce thème — pratique pour faire plusieurs questions sur le "
                    "même jeu de données, sans le recopier à chaque exercice."
                ),
            },
        ),
    )


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "theme", "kind", "order", "function_name")
    list_filter = ("theme", "kind")
    inlines = [TestCaseInline, HintInline]
    fieldsets = (
        (None, {"fields": ("theme", "title", "slug", "order", "kind")}),
        ("Contenu affiché à l'étudiant", {"fields": ("statement", "starter_code")}),
        (
            "Correction automatique — exercices Python",
            {
                "fields": ("function_name", "solution_code"),
                "description": (
                    "Uniquement si Type = 'Python (fonction)'. Renseigne le nom de la fonction et un "
                    "code de correction complet (une vraie implémentation qui fonctionne). Le résultat "
                    "attendu de chaque test sera calculé automatiquement : ajoute des lignes de test "
                    "ci-dessous avec juste les arguments à essayer, sans écrire le résultat toi-même."
                ),
            },
        ),
        (
            "Correction automatique — exercices SQL",
            {
                "fields": ("sql_setup", "sql_solution"),
                "description": (
                    "Uniquement si Type = 'SQL (requête)'. 'sql_setup' est OPTIONNEL ici : laisse "
                    "vide pour réutiliser automatiquement la base de données définie sur le thème "
                    "— ne remplis ce champ que si CET exercice a besoin de données différentes. "
                    "'sql_solution' est la requête correcte : le résultat attendu est calculé "
                    "automatiquement en l'exécutant, puis comparé à la requête de l'étudiant."
                ),
            },
        ),
    )


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("user", "exercise", "success", "created_at")
    list_filter = ("success", "exercise__theme", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "exercise", "submitted_code", "success", "created_at")


@admin.register(Abandonment)
class AbandonmentAdmin(admin.ModelAdmin):
    list_display = ("user", "exercise", "created_at")
    list_filter = ("exercise__theme", "created_at")
    search_fields = ("user__email",)
    # Pas de readonly_fields : supprimer une ligne ici lève le verrou de 48h manuellement,
    # pratique si un étudiant a un empêchement légitime.
