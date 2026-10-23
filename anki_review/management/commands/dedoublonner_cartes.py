"""Repère (et, sur demande, fusionne) les cartes d'étudiants qui sont des copies de cartes
du professeur.

Cas typique : un étudiant a importé un export des cartes du professeur avant que l'import ne
reconnaisse les cartes existantes ; il en a gardé des copies privées, dans des paquets à son
nom, qui apparaissent à côté des originales dans Édition.

Une carte d'étudiant est une copie d'une carte du professeur quand elle a le même identifiant
(guid) — ou, à défaut, exactement la même question et la même réponse.

    python manage.py dedoublonner_cartes                 # rapport seulement, rien n'est modifié
    python manage.py dedoublonner_cartes --identifiant X # limité à un étudiant
    python manage.py dedoublonner_cartes --appliquer     # fusionne

Fusion : la progression de l'étudiant (intervalle, répétitions, échéance…) est reportée sur la
carte du professeur, puis la copie est supprimée, ainsi que les paquets d'étudiants qui
restent vides. Si l'étudiant a déjà une carte sur l'originale, on garde la plus avancée.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from anki_review.models import Card, Deck, Note

CHAMPS_PROGRESSION = (
    "file", "intervalle_jours", "facteur_facilite", "repetitions", "echecs",
    "prochaine_revision", "derniere_revision", "suspendue",
)


def trouver_doublons(identifiant=None):
    """Liste de (copie d'étudiant, note du professeur, raison)."""
    officielles = Note.objects.filter(Q(cree_par__isnull=True) | Q(cree_par__is_staff=True))
    par_guid, par_contenu = {}, {}
    for note in officielles.order_by("id"):
        par_guid.setdefault(note.guid, note)
        par_contenu.setdefault((note.question.strip(), note.reponse.strip()), note)

    copies = Note.objects.filter(cree_par__isnull=False, cree_par__is_staff=False).select_related(
        "cree_par", "deck"
    )
    if identifiant:
        copies = copies.filter(cree_par__identifiant=identifiant)

    resultats = []
    for copie in copies.order_by("cree_par_id", "id"):
        officielle = par_guid.get(copie.guid)
        raison = "même identifiant"
        if officielle is None:
            officielle = par_contenu.get((copie.question.strip(), copie.reponse.strip()))
            raison = "même contenu"
        if officielle is not None:
            resultats.append((copie, officielle, raison))
    return resultats


def _plus_avancee(a, b):
    return a if (a.repetitions, a.intervalle_jours) >= (b.repetitions, b.intervalle_jours) else b


def fusionner(copie, officielle):
    """Reporte les cartes (progressions) de `copie` sur `officielle`, puis supprime `copie`."""
    for carte in list(copie.cards.all()):
        existante = Card.objects.filter(note=officielle, etudiant=carte.etudiant).first()
        if existante is None:
            carte.note = officielle
            carte.save(update_fields=["note"])
            continue
        if _plus_avancee(carte, existante) is carte:
            for champ in CHAMPS_PROGRESSION:
                setattr(existante, champ, getattr(carte, champ))
            existante.save()
    # Les cartes déjà déplacées ne sont plus rattachées à la copie : seule la copie disparaît.
    copie.delete()


class Command(BaseCommand):
    help = "Repère (et avec --appliquer, fusionne) les copies étudiantes de cartes du professeur."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true", help="Fusionner réellement (sinon : rapport seul).")
        parser.add_argument("--identifiant", help="Se limiter à un étudiant (son identifiant).")

    def handle(self, *args, appliquer=False, identifiant=None, **options):
        doublons = trouver_doublons(identifiant)
        if not doublons:
            self.stdout.write("Aucun doublon trouvé.")
            return

        par_etudiant = defaultdict(list)
        for copie, officielle, raison in doublons:
            par_etudiant[copie.cree_par].append((copie, officielle, raison))

        for etudiant, lignes in par_etudiant.items():
            decks = sorted({c.deck.nom for c, _, _ in lignes})
            self.stdout.write(
                f"{etudiant} : {len(lignes)} copie(s) dans {len(decks)} paquet(s) ({', '.join(decks[:5])}"
                f"{'…' if len(decks) > 5 else ''})"
            )
        self.stdout.write(f"Total : {len(doublons)} copie(s) pour {len(par_etudiant)} étudiant(s).")

        if not appliquer:
            self.stdout.write("Rapport seul — rien n'a été modifié. Relancer avec --appliquer pour fusionner.")
            return

        decks_touches = {copie.deck_id for copie, _, _ in doublons}
        with transaction.atomic():
            for copie, officielle, _ in doublons:
                fusionner(copie, officielle)
            vides = Deck.objects.filter(id__in=decks_touches, notes__isnull=True).exclude(
                Q(cree_par__isnull=True) | Q(cree_par__is_staff=True)
            )
            nb_vides = vides.count()
            vides.delete()
        self.stdout.write(self.style.SUCCESS(
            f"{len(doublons)} copie(s) fusionnée(s), {nb_vides} paquet(s) d'étudiant vide(s) supprimé(s)."
        ))
