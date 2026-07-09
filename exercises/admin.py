from django.contrib import admin
from .models import Theme, Exercise, Result, TestCase


class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0
    fields = ("title", "slug", "order")


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 1
    fields = ("args", "order")


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order")
    inlines = [ExerciseInline]


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "theme", "order", "function_name")
    list_filter = ("theme",)
    inlines = [TestCaseInline]
    fieldsets = (
        (None, {"fields": ("theme", "title", "slug", "order")}),
        ("Contenu affiché à l'étudiant", {"fields": ("statement", "starter_code")}),
        (
            "Correction automatique",
            {
                "fields": ("function_name", "solution_code"),
                "description": (
                    "Renseigne le nom de la fonction et un code de correction complet (une vraie "
                    "implémentation qui fonctionne). Le résultat attendu de chaque test sera calculé "
                    "automatiquement à partir de ce code : ajoute des lignes de test ci-dessous avec "
                    "juste les arguments à essayer, sans avoir à écrire le résultat toi-même."
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