"""
Implémentation SM-2 (variante proche de celle d'Anki), indépendante du
format de fichier. Les données lues/écrites (intervalle, ease factor,
repetitions) sont celles stockées dans le modèle Card — c'est bien le
CODE de l'algorithme qui manquait au simple format .anki2, comme évoqué
en chat : le fichier ne fait que stocker les nombres, pas les calculer.

Boutons -> qualité (échelle 0-5 façon SuperMemo, simplifiée à 4 boutons
comme le fait Anki) :
    Again = 0   Hard = 3   Good = 4   Easy = 5
"""
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone


class Reponse:
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


_QUALITE = {
    Reponse.AGAIN: 0,
    Reponse.HARD: 3,
    Reponse.GOOD: 4,
    Reponse.EASY: 5,
}

EASE_MIN = 1.3
EASE_INITIAL = 2.5


@dataclass
class ResultatSM2:
    intervalle_jours: float
    facteur_facilite: float
    repetitions: int
    file: str


def calculer_prochaine_etape(carte, reponse: str) -> ResultatSM2:
    """
    Calcule le nouvel état SM-2 d'une carte à partir de la réponse donnée
    (Again/Hard/Good/Easy). Ne modifie PAS l'objet `carte` — à l'appelant
    d'appliquer le résultat et de sauvegarder (cf. views.py).
    """
    qualite = _QUALITE[reponse]
    ease = carte.facteur_facilite
    reps = carte.repetitions
    intervalle = carte.intervalle_jours

    if reponse == Reponse.AGAIN:
        # Échec : on repart en apprentissage, l'ease baisse mais reste bornée.
        return ResultatSM2(
            intervalle_jours=1 / 24 / 6,  # ~10 minutes, comme Anki en "learning"
            facteur_facilite=max(EASE_MIN, ease - 0.2),
            repetitions=0,
            file="learning",
        )

    # Ajustement de l'ease factor, formule SM-2 standard
    nouvelle_ease = ease + (0.1 - (5 - qualite) * (0.08 + (5 - qualite) * 0.02))
    nouvelle_ease = max(EASE_MIN, nouvelle_ease)

    if reps == 0:
        nouvel_intervalle = 1
    elif reps == 1:
        nouvel_intervalle = 6
    else:
        nouvel_intervalle = intervalle * nouvelle_ease

    if reponse == Reponse.HARD:
        nouvel_intervalle *= 0.8
    elif reponse == Reponse.EASY:
        nouvel_intervalle *= 1.3

    return ResultatSM2(
        intervalle_jours=round(nouvel_intervalle, 2),
        facteur_facilite=round(nouvelle_ease, 3),
        repetitions=reps + 1,
        file="review",
    )


def appliquer(carte, reponse: str) -> None:
    """Calcule ET applique le résultat sur l'instance Card, sans la sauvegarder."""
    resultat = calculer_prochaine_etape(carte, reponse)
    carte.intervalle_jours = resultat.intervalle_jours
    carte.facteur_facilite = resultat.facteur_facilite
    carte.repetitions = resultat.repetitions
    carte.file = resultat.file
    carte.derniere_revision = timezone.now()
    carte.prochaine_revision = timezone.now() + timedelta(days=resultat.intervalle_jours)
    if reponse == Reponse.AGAIN:
        carte.echecs += 1
