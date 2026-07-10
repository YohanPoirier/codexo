import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from exercises.models import Theme, Exercise, TestCase, Hint
from accounts.models import User
import os

DATA_FILE = Path(settings.BASE_DIR) / "exercises_data.json"


class Command(BaseCommand):
    help = "Remplit la base avec les thèmes/exercices définis dans exercises_data.json."

    def handle(self, *args, **options):
        if not DATA_FILE.exists():
            raise CommandError(f"Fichier introuvable : {DATA_FILE}")

        with open(DATA_FILE, encoding="utf-8") as f:
            DATA = json.load(f)

        for order, theme_data in enumerate(DATA):
            theme, _ = Theme.objects.update_or_create(
                slug=theme_data["slug"],
                defaults={
                    "name": theme_data["name"],
                    "description": theme_data["description"],
                    "order": order,
                    "sql_setup": theme_data.get("sql_setup", ""),
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
                        "kind": ex_data.get("kind", "python"),
                        "starter_code": ex_data["starter_code"],
                        "function_name": ex_data.get("function_name", ""),
                        "solution_code": ex_data.get("solution_code", ""),
                        "sql_setup": ex_data.get("sql_setup", ""),
                        "sql_solution": ex_data.get("sql_solution", ""),
                    },
                )
                exercise.test_cases.all().delete()
                for i, args_source in enumerate(ex_data.get("test_cases", [])):
                    TestCase.objects.create(
                        exercise=exercise,
                        args=args_source,
                        order=i,
                    )
                exercise.hints.all().delete()
                for i, hint_text in enumerate(ex_data.get("hints", [])):
                    Hint.objects.create(
                        exercise=exercise,
                        text=hint_text,
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
