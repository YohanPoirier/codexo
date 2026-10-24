"""Nettoie le HTML des cartes déjà enregistrées (avant l'arrivée du filtre html_propre).

Par défaut : RAPPORT seulement (rien n'est modifié). Avec --appliquer : réécrit les cartes
(et propositions) dont le HTML change une fois nettoyé.
"""
import difflib
import re

from django.core.management.base import BaseCommand

from anki_review.html_propre import nettoyer_html
from anki_review.models import Note, PropositionModification


class Command(BaseCommand):
    help = "Nettoie le HTML des cartes existantes (rapport par défaut, --appliquer pour écrire)."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true", help="Enregistre les changements.")
        parser.add_argument(
            "--detail", action="store_true",
            help="Affiche, pour chaque carte, ce que le nettoyage retire ou ajoute.",
        )

    def handle(self, *args, **options):
        appliquer = options["appliquer"]
        for modele, libelle in ((Note, "carte(s)"), (PropositionModification, "proposition(s)")):
            concernes = cosmetiques = 0
            for obj in modele.objects.all().iterator():
                q, r = nettoyer_html(obj.question), nettoyer_html(obj.reponse)
                if (q, r) == (obj.question, obj.reponse):
                    continue
                concernes += 1
                if appliquer:
                    # update() : évite les effets de bord de save() (carte réversible, etc.)
                    modele.objects.filter(pk=obj.pk).update(question=q, reponse=r)
                if self._normaliser(obj.question) == self._normaliser(q) and \
                        self._normaliser(obj.reponse) == self._normaliser(r):
                    cosmetiques += 1  # même affichage : fins de ligne, < écrit &lt;, « ; » final
                    continue
                self.stdout.write(f"  {modele.__name__} #{obj.pk} : CHANGEMENT DE CONTENU")
                if options["detail"]:
                    for champ, avant, apres in (("question", obj.question, q), ("réponse", obj.reponse, r)):
                        if avant != apres:
                            self.stdout.write(f"      {champ} : {self._difference(avant, apres)}")
            self.stdout.write(
                f"{concernes} {libelle} concernée(s), dont {cosmetiques} sans aucun effet visible "
                f"(fins de ligne, « < » écrit « &lt; », « ; » final) et {concernes - cosmetiques} "
                f"avec un vrai changement de contenu."
            )
        if not appliquer:
            self.stdout.write("Rapport seulement : relancer avec --appliquer pour écrire.")

    @staticmethod
    def _normaliser(html):
        """Forme de comparaison qui ignore les différences sans effet à l'affichage."""
        return (
            html.replace("\r\n", "\n").replace("&lt;", "<").replace("&gt;", ">")
            .replace(";\"", "\"")
        )

    @staticmethod
    def _difference(avant, apres):
        """Résumé lisible : fragments retirés (-) et ajoutés (+), balise par balise."""
        morceaux = lambda t: re.findall(r"<[^>]*>|[^<]+", t)
        a, b = morceaux(avant), morceaux(apres)
        sortie = []
        for ligne in difflib.ndiff(a, b):
            if ligne[:2] in ("- ", "+ "):
                texte = ligne[2:].replace("\r", "\\r").replace("\n", "\\n")
                sortie.append(f"{ligne[0]}{texte[:80]}")
        return " | ".join(sortie) or "(différence de mise en forme)"
