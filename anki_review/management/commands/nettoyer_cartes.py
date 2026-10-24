"""Nettoie le HTML des cartes déjà enregistrées (avant l'arrivée du filtre html_propre).

Par défaut : RAPPORT seulement (rien n'est modifié). Avec --appliquer : réécrit les cartes
(et propositions) dont le HTML change une fois nettoyé.
"""
from django.core.management.base import BaseCommand

from anki_review.html_propre import nettoyer_html
from anki_review.models import Note, PropositionModification


class Command(BaseCommand):
    help = "Nettoie le HTML des cartes existantes (rapport par défaut, --appliquer pour écrire)."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true", help="Enregistre les changements.")

    def handle(self, *args, **options):
        appliquer = options["appliquer"]
        for modele, libelle in ((Note, "carte(s)"), (PropositionModification, "proposition(s)")):
            concernes = 0
            for obj in modele.objects.all().iterator():
                q, r = nettoyer_html(obj.question), nettoyer_html(obj.reponse)
                if (q, r) == (obj.question, obj.reponse):
                    continue
                concernes += 1
                self.stdout.write(f"  {modele.__name__} #{obj.pk} modifiée par le nettoyage")
                if appliquer:
                    # update() : évite les effets de bord de save() (carte réversible, etc.)
                    modele.objects.filter(pk=obj.pk).update(question=q, reponse=r)
            self.stdout.write(f"{concernes} {libelle} concernée(s).")
        if not appliquer:
            self.stdout.write("Rapport seulement : relancer avec --appliquer pour écrire.")
