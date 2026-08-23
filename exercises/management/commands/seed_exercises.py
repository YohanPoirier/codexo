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
            # get_or_create (au lieu de update_or_create) : on ne fixe l'"order" qu'une
            # fois l'instance en main, pour pouvoir passer skip_reorder=True à save() et
            # éviter que Theme.save() ne déclenche un décalage en cascade des AUTRES
            # thèmes — ici on réaffecte déjà explicitement l'ordre de TOUS les thèmes
            # dans cette même boucle, donc ce décalage automatique n'a pas lieu d'être
            # (et produirait un résultat imprévisible s'il se déclenchait à chaque tour).
            theme, _ = Theme.objects.get_or_create(
                slug=theme_data["slug"],
                defaults={"name": theme_data["name"]},
            )
            theme.name = theme_data["name"]
            theme.description = theme_data["description"]
            theme.order = order
            theme.sql_setup = theme_data.get("sql_setup", "")
            theme.save(skip_reorder=True)

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

        # Comptes admin recréés automatiquement à chaque démarrage (local ET
        # production) : utile car le plan gratuit de Render ne persiste pas le
        # système de fichiers/la base de données (voir README). Ce bloc tourne
        # désormais aussi en production (contrairement à avant, où il était limité
        # à DEBUG=True) : il remplace donc le "createsuperuser --noinput" du
        # Procfile, qui ne gérait qu'un seul admin et ne mettait jamais à jour son
        # mot de passe s'il existait déjà.
        #
        # Chaque admin est défini par une paire de variables d'environnement :
        # DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD pour le premier, puis
        # DJANGO_SUPERUSER2_EMAIL / DJANGO_SUPERUSER2_PASSWORD pour le deuxième,
        # DJANGO_SUPERUSER3_... pour le troisième, etc. On s'arrête dès qu'un
        # numéro n'a NI l'email NI le mot de passe définis.
        admin_trouve = False
        numero = 1
        suffixe = ""
        while True:
            admin_email = os.environ.get(f"DJANGO_SUPERUSER{suffixe}_EMAIL")
            admin_password = os.environ.get(f"DJANGO_SUPERUSER{suffixe}_PASSWORD")
            if not admin_email and not admin_password:
                break

            admin_trouve = True
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
                    f"Compte admin {action} : {admin_email}"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"DJANGO_SUPERUSER{suffixe}_EMAIL / DJANGO_SUPERUSER{suffixe}_PASSWORD "
                    "incomplet (une seule des deux variables est définie) : ce compte "
                    "admin n'a pas été créé."
                ))

            numero += 1
            suffixe = str(numero)

        if not admin_trouve:
            self.stdout.write(self.style.WARNING(
                "Aucune variable DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD "
                "définie (vérifie ton fichier .env, ou les variables d'environnement "
                "Render) : aucun compte admin créé automatiquement."
            ))

        self.stdout.write(self.style.SUCCESS("Thèmes et exercices créés avec succès."))
