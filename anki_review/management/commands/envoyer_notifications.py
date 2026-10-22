"""Envoi hebdomadaire des notifications d'Anki aux élèves abonnés.

À lancer une fois par semaine par une tâche planifiée du serveur (cron), par exemple
le dimanche à 18 h :

    0 18 * * 0  cd /home/codexo/codexo && venv/bin/python manage.py envoyer_notifications

Au plus deux messages par élève, séparés : Anki (cartes à réviser et/ou nouvelles cartes
partagées par un professeur) et Codexo (nouveaux exercices), selon ses réglages ; rien
n'est envoyé s'il n'y a rien à dire. Un élève déjà traité
depuis moins de 6 jours est ignoré (protège d'un double lancement).

    --simulation   affiche ce qui serait envoyé, sans rien envoyer ni enregistrer
    --force        ignore le délai de 6 jours
    --identifiant  ne traite que cet élève (pratique pour un essai)
"""
from django.core.management.base import BaseCommand, CommandError

from anki_review import notifications


class Command(BaseCommand):
    help = "Envoie les notifications hebdomadaires d'Anki (cartes à réviser, nouvelles cartes)."

    def add_arguments(self, parser):
        parser.add_argument("--simulation", action="store_true",
                            help="Calcule et affiche, sans rien envoyer.")
        parser.add_argument("--force", action="store_true",
                            help="Ignore le délai minimal entre deux passages.")
        parser.add_argument("--identifiant", help="Ne traiter que cet élève.")

    def handle(self, *args, **options):
        if not notifications.configuration_ok() and not options["simulation"]:
            raise CommandError(
                "Clés d'envoi absentes : renseigne VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY et "
                "VAPID_CONTACT dans le .env (clés : python manage.py generer_cles_vapid)."
            )

        resultats = notifications.envoyer_hebdomadaire(
            simulation=options["simulation"],
            force=options["force"],
            identifiant=options["identifiant"],
        )
        if not resultats:
            self.stdout.write("Aucun élève abonné aux notifications.")
            return

        envoyes = 0
        for r in resultats:
            detail = (
                f"{r['a_reviser']} à réviser, {r['nouvelles']} nouvelles, "
                f"{r['exercices']} exercices"
            )
            self.stdout.write(f"{r['etudiant']} : {r['statut']} ({detail})")
            if r["envoyes"]:
                envoyes += 1
        self.stdout.write(self.style.SUCCESS(
            f"{len(resultats)} élève(s) traité(s), {envoyes} reçu(s) un message."
        ))
