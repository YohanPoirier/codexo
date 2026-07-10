import json
from pathlib import Path

from django.conf import settings

DATA_FILE = Path(settings.BASE_DIR) / "exercises_data.json"


def export_exercises_to_json():
    """Écrit l'état actuel de la base (Theme/Exercise/TestCase/Hint) dans exercises_data.json."""
    from exercises.models import Theme  # import tardif pour éviter les imports circulaires

    data = []
    for theme in Theme.objects.order_by("order"):
        theme_entry = {
            "name": theme.name,
            "slug": theme.slug,
            "description": theme.description,
            "sql_setup": theme.sql_setup,
            "exercises": [],
        }
        for ex in theme.exercises.order_by("order"):
            theme_entry["exercises"].append({
                "title": ex.title,
                "slug": ex.slug,
                "statement": ex.statement,
                "kind": ex.kind,
                "starter_code": ex.starter_code,
                "function_name": ex.function_name,
                "solution_code": ex.solution_code,
                "sql_setup": ex.sql_setup,
                "sql_solution": ex.sql_solution,
                "test_cases": [tc.args for tc in ex.test_cases.order_by("order")],
                "hints": [h.text for h in ex.hints.order_by("order")],
            })
        data.append(theme_entry)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return len(data)
