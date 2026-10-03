import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from exercises.models import Theme, Exercise, TestCase, Hint
from accounts.models import Classe, User
import os

DATA_FILE = Path(settings.DATA_DIR) / "exercises_data.json"

# Classes fixes de l'établissement : contrairement aux élèves (qui changent chaque
# année, importés par CSV), les classes elles-mêmes ne changent jamais — codées en
# dur ici plutôt que créées à la main dans l'admin (voir contexte-technique.md).
CLASSES_FIXES = [
    {"slug": "pcsi", "name": "PCSI"},
    {"slug": "mpsi", "name": "MPSI"},
    {"slug": "psi", "name": "PSI"},
]

# Permissions du groupe "Professeurs" (voir plus bas) : {modèle: [codenames]}.
# Classe est volontairement en lecture seule (view) : les 3 classes ci-dessus
# sont fixes et gérées automatiquement par ce script, un prof n'a pas besoin
# d'en ajouter/supprimer depuis l'admin. Rien sur User/Group/Permission.
PERMISSIONS_PROFESSEURS = {
    Theme: ["add", "change", "view", "delete"],
    Exercise: ["add", "change", "view", "delete"],
    TestCase: ["add", "change", "view", "delete"],
    Hint: ["add", "change", "view", "delete"],
    Classe: ["view"],
}


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
                        "require_recursive": ex_data.get("require_recursive", False),
                        "extra_test_code": ex_data.get("extra_test_code", ""),
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

        # Classes fixes (voir CLASSES_FIXES en haut du fichier), créées/mises à jour
        # à chaque lancement comme les thèmes/exercices ci-dessus.
        for classe_data in CLASSES_FIXES:
            classe, _ = Classe.objects.get_or_create(
                slug=classe_data["slug"],
                defaults={"name": classe_data["name"]},
            )
            classe.name = classe_data["name"]
            classe.save()
        self.stdout.write(self.style.SUCCESS(
            "Classes fixes créées/à jour : " + ", ".join(c["name"] for c in CLASSES_FIXES)
        ))

        # Groupe "Professeurs" (voir PERMISSIONS_PROFESSEURS en haut du fichier) :
        # permissions.set() remplace la liste existante à chaque lancement, donc un
        # changement de PERMISSIONS_PROFESSEURS dans le code se répercute tout seul
        # au prochain seed_exercises — pas besoin de retoucher l'admin à la main.
        # Fonctionne uniquement parce que ce script tourne APRÈS "migrate" (jamais
        # dans la même commande) : les Permission de Django ne sont créées qu'à la
        # toute fin de "migrate" (signal post_migrate), donc elles existent déjà en
        # base quand seed_exercises est lancé séparément.
        groupe_profs, _ = Group.objects.get_or_create(name="Professeurs")
        permissions = []
        for model, codenames in PERMISSIONS_PROFESSEURS.items():
            content_type = ContentType.objects.get_for_model(model)
            for codename in codenames:
                permissions.append(Permission.objects.get(
                    content_type=content_type,
                    codename=f"{codename}_{model._meta.model_name}",
                ))
        groupe_profs.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS(
            f"Groupe \"Professeurs\" créé/à jour ({len(permissions)} permissions)."
        ))

        # Comptes admin (re)créés/mis à jour par ce bloc à chaque exécution de la
        # commande (elle est idempotente : la relancer ne duplique rien, ça remet
        # juste ces comptes à l'état défini par les variables d'environnement). Ce
        # bloc tourne aussi bien en local qu'en production, et remplace le
        # "createsuperuser --noinput" que ferait un Procfile, qui ne gérait qu'un
        # seul admin et ne mettait jamais à jour son mot de passe s'il existait déjà.
        #
        # Sur le VPS de prod, cette commande n'est PAS relancée automatiquement à
        # chaque redémarrage du service — seulement ponctuellement, à la main (voir
        # deploiement_checklist.md).
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
                # Depuis la refonte du 06/09/2026 (voir contexte-technique.md),
                # "identifiant" est le vrai USERNAME_FIELD (email n'est plus unique
                # ni obligatoire) : on l'utilise donc comme clé de recherche/connexion
                # pour ce compte de bootstrap, en reprenant l'email comme valeur (ça
                # reste un identifiant lisible et pratique pour un compte admin).
                admin, created = User.objects.get_or_create(
                    identifiant=admin_email,
                    defaults={"email": admin_email, "is_staff": True, "is_superuser": True},
                )
                admin.email = admin_email
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
                "du serveur) : aucun compte admin créé automatiquement."
            ))

        # Compte élève de test, (re)créé/mis à jour au même titre que les admins
        # ci-dessus, pour les mêmes raisons (voir commentaire plus haut).
        # Contrairement aux admins, ce compte n'a NI is_staff NI is_superuser : un
        # élève normal, juste pratique pour tester rapidement le parcours étudiant
        # sans repasser par le formulaire d'inscription à chaque redémarrage.
        #
        # Optionnel : si DJANGO_TEST_STUDENT_EMAIL / DJANGO_TEST_STUDENT_PASSWORD
        # ne sont pas définies, ce bloc ne fait simplement rien (pas de warning,
        # contrairement aux admins : un compte élève de test n'est pas obligatoire).
        student_email = os.environ.get("DJANGO_TEST_STUDENT_EMAIL")
        student_password = os.environ.get("DJANGO_TEST_STUDENT_PASSWORD")
        if student_email and student_password:
            # Même remarque que pour les admins ci-dessus : "identifiant" (et non
            # plus "email") est désormais le vrai USERNAME_FIELD.
            student, created = User.objects.get_or_create(
                identifiant=student_email,
                defaults={"email": student_email, "display_name": "Élève test"},
            )
            student.email = student_email
            student.set_password(student_password)
            student.save()
            action = "créé" if created else "mis à jour"
            self.stdout.write(self.style.SUCCESS(
                f"Compte élève de test {action} : {student_email}"
            ))

        self.stdout.write(self.style.SUCCESS("Thèmes et exercices créés avec succès."))
