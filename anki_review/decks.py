"""Visibilité des paquets et déplacement de cartes d'un paquet à un autre."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Card, Deck, Note, SuggestionDeplacement


def decks_visibles(user, avec_mes_cartes=True):
    """Paquets visibles par cet utilisateur : ceux du prof (officiels, sans
    créateur ou créé par un membre du staff) + les siens propres + tout
    paquet contenant au moins une note partagée (même appartenant à un
    autre étudiant) — nécessaire depuis qu'une note "récupérée" n'est plus
    copiée dans un paquet à soi : elle reste dans son paquet d'origine, qui
    doit donc devenir visible pour qu'on puisse la retrouver dans Édition.
    Un paquet privé sans aucune note partagée reste invisible aux autres,
    comme avant.

    + tout paquet où il a au moins une carte (avec_mes_cartes) : une carte
    récupérée est GARDÉE même si son propriétaire cesse de la partager, et
    son paquet doit donc rester visible, sinon la carte serait conservée
    en base mais introuvable (ni dans l'accueil, ni en révision).
    avec_mes_cartes=False donne les paquets où l'on a le droit D'AJOUTER des cartes
    (formulaires d'ajout, destination d'un déplacement) : on n'y propose pas, pour y
    écrire, le paquet d'un autre qui a cessé de partager."""
    if user.is_staff:
        return Deck.objects.all()
    visibilite = (
        Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=user)
        | Q(notes__partagee_avec_classe=True)
    )
    if avec_mes_cartes:
        visibilite |= Q(notes__cards__etudiant=user)
    return Deck.objects.filter(visibilite).distinct()


def peut_ajouter_dans(user, deck):
    return decks_visibles(user, avec_mes_cartes=False).filter(pk=deck.pk).exists()


def mes_notes(user, deck):
    """Les cartes (notes) de `deck` dont `user` est propriétaire : les seules qu'il peut déplacer."""
    return Note.objects.filter(deck=deck, cree_par=user)


class DeplacementImpossible(Exception):
    pass


@transaction.atomic
def deplacer_mes_cartes(user, source, destination):
    """Déplace les cartes dont `user` est propriétaire de `source` vers `destination`.

    Rien n'est copié ni supprimé : la note change de paquet, donc la progression de tous ceux
    qui l'ont, le partage et la carte miroir (même propriétaire, même paquet) suivent. Les
    cartes qu'il a seulement récupérées chez d'autres restent où elles sont (elles ne sont pas à
    lui). Renvoie le nombre de cartes déplacées."""
    if source.pk == destination.pk:
        raise DeplacementImpossible("Le paquet de destination est le même que celui de départ.")
    if not peut_ajouter_dans(user, destination):
        raise DeplacementImpossible("Tu ne peux pas ajouter de cartes dans ce paquet.")
    ids = list(mes_notes(user, source).values_list("pk", flat=True))
    if not ids:
        raise DeplacementImpossible("Tu n'as aucune carte à toi dans ce paquet.")
    # update() : la note ne change que de paquet (pas de contenu), sans passer par save().
    Note.objects.filter(pk__in=ids).update(deck=destination)
    _apres_depart(user, source)
    return len(ids)


def _apres_depart(user, deck):
    """Ce que devient le paquet que `user` vient de vider de ses cartes.
    - Plus aucune note dedans et il en était le créateur : supprimé (il n'est plus utile).
    - Il en était le créateur, n'y a plus de carte à lui, mais d'autres y en gardent : la
      propriété du paquet passe au plus ancien détenteur, comme pour la suppression d'un paquet.
    - Sinon (paquet d'un autre, paquet officiel…) : on n'y touche."""
    if deck.cree_par_id != user.id:
        return
    if not deck.notes.exists():
        deck.delete()
        return
    if Card.objects.filter(note__deck=deck, etudiant=user).exists():
        return
    suivante = Card.objects.filter(note__deck=deck).order_by("cree_le", "id").first()
    if suivante:
        deck.cree_par = suivante.etudiant
        deck.save(update_fields=["cree_par"])


def proposer_aux_autres(auteur, source, destination):
    """Après le déplacement de `auteur`, propose la même chose aux autres personnes qui ont
    encore des cartes à elles dans `source` — à condition qu'elles puissent ajouter dans
    `destination`. Rien pour un paquet officiel (celui d'un professeur) : on ne propose pas
    de déplacer des cartes officielles, et jamais aux professeurs. Renvoie les suggestions créées."""
    if source.cree_par_id is None or source.cree_par.is_staff:
        return []
    Utilisateur = get_user_model()
    proprietaires = (
        Utilisateur.objects.filter(notes_creees__deck=source, is_active=True, is_staff=False)
        .exclude(pk=auteur.pk).distinct()
    )
    creees = []
    for utilisateur in proprietaires:
        if not peut_ajouter_dans(utilisateur, destination):
            continue
        suggestion, nouvelle = SuggestionDeplacement.objects.get_or_create(
            destinataire=utilisateur, ancien_deck=source, nouveau_deck=destination,
            defaults={"auteur": auteur},
        )
        if nouvelle:
            creees.append(suggestion)
    return creees


def suggestions_en_attente(user):
    """Suggestions encore applicables : le destinataire a toujours des cartes à lui dans
    l'ancien paquet et peut toujours ajouter dans le nouveau. Chacune porte `nb_cartes`."""
    valides = []
    suggestions = SuggestionDeplacement.objects.filter(
        destinataire=user, statut=SuggestionDeplacement.Statut.EN_ATTENTE,
    ).select_related("auteur", "ancien_deck", "nouveau_deck")
    for suggestion in suggestions:
        nb = mes_notes(user, suggestion.ancien_deck).count()
        if nb and peut_ajouter_dans(user, suggestion.nouveau_deck):
            suggestion.nb_cartes = nb
            valides.append(suggestion)
    return valides


@transaction.atomic
def accepter_suggestion(suggestion):
    """Déplace les cartes du destinataire comme la suggestion le propose."""
    # Statut posé AVANT le déplacement : si l'ancien paquet se vide, il est supprimé et la
    # suggestion avec lui (suppression en cascade) — il n'y aurait plus rien à enregistrer après.
    # En cas d'échec du déplacement, la transaction annule aussi ce changement.
    SuggestionDeplacement.objects.filter(pk=suggestion.pk).update(
        statut=SuggestionDeplacement.Statut.ACCEPTEE, traitee_le=timezone.now())
    return deplacer_mes_cartes(suggestion.destinataire, suggestion.ancien_deck, suggestion.nouveau_deck)
