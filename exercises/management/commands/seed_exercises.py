from django.conf import settings
from django.core.management.base import BaseCommand
from exercises.models import Theme, Exercise, TestCase
from accounts.models import User
import os


DATA = [
    {
        "name": "Variables & types",
        "slug": "variables-types",
        "description": "Manipuler des nombres, des chaînes et des booléens.",
        "exercises": [
            {
                "title": "Addition simple",
                "slug": "addition-simple",
                "statement": (
                    "Écris une fonction `addition(a, b)` qui renvoie la somme de a et b."
                ),
                "starter_code": "def addition(a, b):\n    pass\n",
                "function_name": "addition",
                "solution_code": "def addition(a, b):\n    return a + b\n",
                "test_cases": [
                    {"args": [15, 27]},
                    {"args": [0, 0]},
                    {"args": [-5, 5]},
                ],
            },
            {
                "title": "Conversion en chaîne",
                "slug": "conversion-chaine",
                "statement": (
                    "Écris une fonction `phrase(nombre)` qui renvoie le texte "
                    "\"J'ai {nombre} pommes\" (en remplaçant {nombre} par la valeur reçue), "
                    "en utilisant str() pour convertir le nombre en texte."
                ),
                "starter_code": "def phrase(nombre):\n    pass\n",
                "function_name": "phrase",
                "solution_code": "def phrase(nombre):\n    return \"J'ai \" + str(nombre) + \" pommes\"\n",
                "test_cases": [
                    {"args": [12]},
                    {"args": [0]},
                    {"args": [1]},
                ],
            },
        ],
    },
    {
        "name": "Conditions",
        "slug": "conditions",
        "description": "Utiliser if / elif / else pour prendre des décisions.",
        "exercises": [
            {
                "title": "Pair ou impair",
                "slug": "pair-impair",
                "statement": (
                    "Écris une fonction `parite(n)` qui renvoie la chaîne \"pair\" si n est pair, "
                    "sinon \"impair\"."
                ),
                "starter_code": "def parite(n):\n    pass\n",
                "function_name": "parite",
                "solution_code": "def parite(n):\n    return 'pair' if n % 2 == 0 else 'impair'\n",
                "test_cases": [
                    {"args": [4]},
                    {"args": [7]},
                    {"args": [0]},
                    {"args": [-3]},
                ],
            },
        ],
    },
    {
        "name": "Boucles",
        "slug": "boucles",
        "description": "Répéter des actions avec for et while.",
        "exercises": [
            {
                "title": "Somme de 1 à n",
                "slug": "somme-1-a-n",
                "statement": (
                    "Écris une fonction `somme(n)` qui renvoie la somme des entiers de 1 à n inclus."
                ),
                "starter_code": "def somme(n):\n    pass\n",
                "function_name": "somme",
                "solution_code": "def somme(n):\n    total = 0\n    for i in range(1, n + 1):\n        total += i\n    return total\n",
                "test_cases": [
                    {"args": [5]},
                    {"args": [1]},
                    {"args": [10]},
                    {"args": [0]},
                ],
            },
        ],
    },
    {
        "name": "Listes",
        "slug": "listes",
        "description": "Créer, parcourir et transformer des listes.",
        "exercises": [
            {
                "title": "Doubler chaque élément",
                "slug": "doubler-elements",
                "statement": (
                    "Écris une fonction `doubler(liste)` qui renvoie une nouvelle liste où "
                    "chaque élément est multiplié par 2."
                ),
                "starter_code": "def doubler(liste):\n    pass\n",
                "function_name": "doubler",
                "solution_code": "def doubler(liste):\n    return [x * 2 for x in liste]\n",
                "test_cases": [
                    {"args": [[1, 2, 3]]},
                    {"args": [[]]},
                    {"args": [[0, -1]]},
                ],
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Remplit la base avec des thèmes et exercices de démonstration."

    def handle(self, *args, **options):
        for order, theme_data in enumerate(DATA):
            theme, _ = Theme.objects.update_or_create(
                slug=theme_data["slug"],
                defaults={
                    "name": theme_data["name"],
                    "description": theme_data["description"],
                    "order": order,
                },
            )
            for ex_order, ex_data in enumerate(theme_data["exercises"]):
                exercise, _ = Exercise.objects.update_or_create(
                    theme=theme,
                    slug=ex_data["slug"],
                    defaults={
                        "title": ex_data["title"],
                        "order": ex_order,
                        "statement": ex_data["statement"],
                        "starter_code": ex_data["starter_code"],
                        "function_name": ex_data["function_name"],
                        "solution_code": ex_data["solution_code"],
                    },
                )
                exercise.test_cases.all().delete()
                for i, case in enumerate(ex_data.get("test_cases", [])):
                    TestCase.objects.create(
                        exercise=exercise,
                        args=repr(case["args"]),
                        order=i,
                    )
        if settings.DEBUG:
            admin_email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
            admin_password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
            if admin_email and admin_password:
                admin, created = User.objects.get_or_create(
                    email=admin_email,
                    defaults={"is_staff": True, "is_superuser": True},
                )
                admin.is_staff = True
                admin.is_superuser = True
                admin.set_password(admin_password)
                admin.save()
                action = "créé" if created else "mis à jour"
                self.stdout.write(self.style.SUCCESS(
                    f"Compte admin local {action} : {admin_email}"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    "DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD non définis "
                    "(vérifie ton fichier .env) : compte admin non créé automatiquement."
                ))

        self.stdout.write(self.style.SUCCESS("Thèmes et exercices créés avec succès."))