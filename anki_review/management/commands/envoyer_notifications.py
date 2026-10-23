"""Envoi planifié des notifications (Anki et Codexo) aux utilisateurs abonnés.

À lancer TOUTES LES HEURES par une tâche planifiée du serveur (cron) :

    0 * * * *  cd /home/codexo/codexo && venv/bin/python manage.py envoyer_notifications

À chaque passage, pour chacun selon ses réglages :
- cartes à réviser : au jour et à l'heure qu'il a choisis (7 h – 22 h, tous les jours possible) ;
- nouvelles cartes partagées par un professeur : tous les jours à 20 h, s'il y en a ;
- nouveaux exercices Codexo : dès le passage qui suit leur publication.
Une notification par sujet, rien s'il n'y a rien à dire. Un même créneau n'est pas traité
deux fois à moins de 50 minutes d'écart (protège d'un double lancement).

    --simulation   affiche ce qui serait envoyé, sans rien envoyer ni enregistrer
    --force        ignore le jour et l'heure choisis : tout est calculé maintenant
    --identifiant  ne traite que cet utilisateur (pratique pour un essai)
"""
from django.core.management.base import BaseCommand, CommandError

from anki_review import notifications


class Command(BaseCommand):
    help = "Envoie les notifications planifiées (révisions, nouvelles cartes, nouveaux exercices)."

    def add_arguments(self, parser):
        parser.add_argument("--simulation", action="store_true",
                            help="Calcule et affiche, sans rien envoyer.")
        parser.add_argument("--force", action="store_true",
                            help="Ignore le jour et l'heure choisis.")
        parser.add_argument("--identifiant", help="Ne traiter que cet utilisateur.")

    def handle(self, *args, **options):
        if not notifications.configuration_ok() and not options["simulation"]:
            raise CommandError(
                "Clés d'envoi absentes : renseigne VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY et "
                "VAPID_CONTACT dans le .env (clés : python manage.py generer_cles_vapid)."
            )

        resultats = notifications.envoyer_planifie(
            simulation=options["simulation"],
            force=options["force"],
            identifiant=options["identifiant"],
        )
        if not resultats:
            self.stdout.write("Rien à faire à cette heure.")
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
            f"{len(resultats)} utilisateur(s) traité(s), {envoyes} ont reçu au moins un message."
        ))
