from django.core.management.base import BaseCommand
from exercises.models import Theme, Exercise, TestCase


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
                    "Crée une variable `resultat` qui contient la somme de 15 et 27."
                ),
                "starter_code": "resultat = 0\n",
                "test_code": (
                    "__RESULTS__ = []\n"
                    "try:\n"
                    "    ok = resultat == 42\n"
                    "except NameError:\n"
                    "    ok = False\n"
                    "__RESULTS__.append((ok, f'resultat doit valoir 42 (obtenu : {resultat if \"resultat\" in dir() else \"non défini\"})'))\n"
                ),
            },
            {
                "title": "Conversion en chaîne",
                "slug": "conversion-chaine",
                "statement": (
                    "Crée une variable `phrase` qui contient exactement le texte :\n"
                    "\"J'ai 12 pommes\"\n"
                    "en utilisant une variable `nombre = 12` convertie en texte avec str()."
                ),
                "starter_code": "nombre = 12\nphrase = \"\"\n",
                "test_code": (
                    "__RESULTS__ = []\n"
                    "attendu = \"J'ai 12 pommes\"\n"
                    "ok = phrase == attendu\n"
                    "__RESULTS__.append((ok, f'phrase attendue : {attendu!r} (obtenu : {phrase!r})'))\n"
                ),
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
                        "function_name": ex_data.get("function_name", ""),
                        "solution_code": ex_data.get("solution_code", ""),
                        "test_code": ex_data.get("test_code", ""),
                    },
                )
                exercise.test_cases.all().delete()
                for i, case in enumerate(ex_data.get("test_cases", [])):
                    TestCase.objects.create(
                        exercise=exercise,
                        args=case["args"],
                        expected=case.get("expected"),
                        order=i,
                    )
        self.stdout.write(self.style.SUCCESS("Thèmes et exercices créés avec succès."))
