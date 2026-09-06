from django.apps import AppConfig


class ExercisesConfig(AppConfig):
    name = 'exercises'
    # Sans ce réglage, l'admin Django affiche l'app sous son nom de code anglais
    # ("Exercises") en tête de page — incohérent avec le reste de l'admin, en français.
    verbose_name = "Exercices"

    def ready(self):
        from . import signals  # noqa: F401
