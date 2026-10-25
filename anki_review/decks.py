"""Paquets personnels et rangement des cartes.

Principe : le CONTENU d'une carte (la Note) est unique et partagé ; son RANGEMENT est personnel.
Chacun a ses propres paquets, que personne d'autre ne voit, et range dans ceux-ci les cartes
qu'il a (Card.deck). Quand on récupère des cartes d'un autre, on les range dans un paquet à soi :
celui de même nom que l'original (créé si besoin), un paquet existant, ou celui qu'une règle de
rangement (« se souvenir de ce choix ») désigne.

Note.deck est le paquet de l'AUTEUR de la note : il sert de provenance (clé des règles) et au
professeur pour modérer. Il suit le rangement de l'auteur.
"""
from django.db import transaction
from django.db.models import Q

from .models import Card, Deck, Note, RegleRangement
from .slugs import slug_unique

NOM_PAQUET_SANS_ORIGINE = "Cartes récupérées"


def mes_paquets(user):
    """Les paquets de cet utilisateur : les seuls dans lesquels il révise et range ses cartes."""
    return Deck.objects.filter(cree_par=user)


def paquets_a_moderer():
    """Pour le professeur : les paquets où des auteurs ont leurs cartes (Note.deck) et les siens."""
    return Deck.objects.filter(Q(notes__isnull=False) | Q(cree_par__is_staff=True)).distinct()


def notes_du_paquet(user, deck):
    """Les notes que `user` a rangées dans son paquet `deck`."""
    return Note.objects.filter(cards__etudiant=user, cards__deck=deck).distinct()


def mes_notes(user, deck):
    """Les cartes du paquet dont `user` est l'auteur (propriétaire)."""
    return notes_du_paquet(user, deck).filter(cree_par=user)


# ----------------------------------------------------------------------------- création de paquets


def creer_paquet(user, nom, matiere="", description=""):
    return Deck.objects.create(
        nom=nom, slug=slug_unique(nom), matiere=matiere, description=description, cree_par=user,
    )


def paquet_de_meme_nom(user, origine, creer=True):
    """Le paquet à moi qui porte le nom (et la matière) du paquet `origine` ; créé s'il n'existe
    pas encore (creer=True), sinon None."""
    deck = mes_paquets(user).filter(nom=origine.nom, matiere=origine.matiere).first()
    if deck is None and creer:
        deck = creer_paquet(user, origine.nom, matiere=origine.matiere)
    return deck


def _paquet_sans_origine(user):
    deck = mes_paquets(user).filter(nom=NOM_PAQUET_SANS_ORIGINE).first()
    return deck or creer_paquet(user, NOM_PAQUET_SANS_ORIGINE)


# ----------------------------------------------------------------------------- règles de rangement


def regle_pour(user, origine):
    """La règle de `user` pour les cartes venant du paquet `origine`, ou None."""
    if origine is None:
        return None
    return RegleRangement.objects.filter(etudiant=user, origine=origine).select_related("destination").first()


def paquet_par_defaut(user, note):
    """Où ranger `note` chez `user` sans lui poser la question : le paquet que sa règle désigne,
    sinon son propre paquet d'origine si c'est le sien, sinon un paquet à lui de même nom."""
    origine = note.deck
    if origine is None:
        return _paquet_sans_origine(user)
    regle = regle_pour(user, origine)
    if regle:
        return regle.destination
    if origine.cree_par_id == user.id:
        return origine
    return paquet_de_meme_nom(user, origine)


def regle_destination(user, notes):
    """Si une seule règle couvre toutes ces notes (même paquet d'origine, une règle posée),
    renvoie le paquet de destination ; sinon None (il faudra demander)."""
    destinations = set()
    for note in notes:
        regle = regle_pour(user, note.deck)
        if regle is None:
            return None
        destinations.add(regle.destination_id)
    if len(destinations) != 1:
        return None
    return regle.destination


def retenir_choix(user, notes, destination):
    """Pose (ou remplace) la règle « cartes de ce paquet d'origine → destination » pour chaque
    paquet d'origine des notes. Sans effet sur ce qui est déjà rangé."""
    origines = {n.deck_id: n.deck for n in notes if n.deck_id and n.deck.cree_par_id != user.id}
    for origine in origines.values():
        RegleRangement.objects.update_or_create(
            etudiant=user, origine=origine, defaults={"destination": destination},
        )


def oublier_regle(user, regle_id):
    RegleRangement.objects.filter(etudiant=user, pk=regle_id).delete()


# ----------------------------------------------------------------------------- rangement


@transaction.atomic
def ranger(user, notes, destination, souvenir=False):
    """Range les cartes `notes` dans `destination` (un paquet à `user`) : une carte déjà à lui
    est déplacée, une carte qu'il n'avait pas lui est ajoutée. Renvoie (cartes_creees,
    cartes_deplacees). Pour les notes dont il est l'auteur, Note.deck suit le rangement."""
    creees, deplacees = [], 0
    for note in notes:
        carte = Card.objects.filter(note=note, etudiant=user).first()
        if carte is None:
            creees.append(Card.objects.create(note=note, etudiant=user, deck=destination))
            continue
        if carte.deck_id != destination.id:
            carte.deck = destination
            carte.save(update_fields=["deck"])
            deplacees += 1
        if note.cree_par_id == user.id and note.deck_id != destination.id:
            Note.objects.filter(pk=note.pk).update(deck=destination)
    if souvenir:
        retenir_choix(user, notes, destination)
    return creees, deplacees


class DeplacementImpossible(Exception):
    pass


def changer_de_paquet(user, notes, destination):
    """Range dans mon paquet `destination` celles de ces notes que j'ai déjà (jamais d'ajout).
    Pour les notes dont je suis l'auteur, Note.deck suit."""
    if destination.cree_par_id != user.id:
        raise DeplacementImpossible("Tu ne peux ranger tes cartes que dans tes propres paquets.")
    for note in notes:
        Card.objects.filter(note=note, etudiant=user).update(deck=destination)
        if note.cree_par_id == user.id:
            Note.objects.filter(pk=note.pk).update(deck=destination)
            note.deck = destination


@transaction.atomic
def deplacer_mes_cartes(user, source, destination):
    """Déplace d'un coup toutes MES cartes du paquet `source` vers mon paquet `destination`
    (avec leur progression). Pour celles dont je suis l'auteur, Note.deck suit. Renvoie leur
    nombre. Le paquet de départ est conservé, même vide."""
    if source.pk == destination.pk:
        raise DeplacementImpossible("Le paquet de destination est le même que celui de départ.")
    if source.cree_par_id != user.id or destination.cree_par_id != user.id:
        raise DeplacementImpossible("Tu ne peux déplacer des cartes qu'entre tes propres paquets.")
    ids = list(Card.objects.filter(etudiant=user, deck=source).values_list("note_id", flat=True))
    if not ids:
        raise DeplacementImpossible("Tu n'as aucune carte dans ce paquet.")
    Card.objects.filter(etudiant=user, deck=source).update(deck=destination)
    Note.objects.filter(pk__in=ids, cree_par=user).update(deck=destination)
    return len(ids)
