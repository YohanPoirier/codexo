"""
Convention adoptée pour les images dans les notes : le champ texte
(question/réponse) ne contient QUE le nom du fichier dans la balise
<img src="...">, comme le fait Anki en interne (voir la conversation sur la
compatibilité .apkg) — pas le chemin complet Django (/media/...).

Ce filtre fait l'opération inverse de l'éditeur au moment de l'AFFICHAGE :
il reconstitue l'URL complète pour que le navigateur puisse réellement
charger l'image. Les anciennes notes qui contiennent déjà un chemin complet
("/media/..." ou une URL absolue) sont laissées telles quelles — la regex
ne touche que les src qui ressemblent à un simple nom de fichier.
"""
import re

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

from ..html_propre import nettoyer_html

register = template.Library()

PREFIXE_IMAGES_NOTES = f"{settings.MEDIA_URL}anki_review/notes/"

# Ne réécrit PAS les src qui commencent déjà par "/" (chemin absolu) ou par
# un schéma http(s):// — uniquement les noms de fichiers nus.
_RE_IMG_SRC_NU = re.compile(r'src="(?!https?://|/)([^"]+)"')


@register.filter(name="peut_editer")
def peut_editer(note, user):
    """Modification DIRECTE (appliquée tout de suite) : réservée au
    propriétaire ou au prof. Voir aussi peut_proposer pour les autres."""
    return user.is_staff or note.cree_par_id == user.id


@register.filter(name="peut_proposer")
def peut_proposer(note, user):
    """Pas propriétaire, mais la carte est dans sa révision : peut
    PROPOSER une correction (à valider par le propriétaire), pas modifier
    directement."""
    if user.is_staff or note.cree_par_id == user.id:
        return False
    return note.cards.filter(etudiant=user).exists()


@register.filter(name="compte_notes_de")
def compte_notes_de(notes, user):
    """Nombre de notes, parmi une liste, appartenant à cet utilisateur —
    sert à savoir s'il a des cartes personnelles dans un paquet qu'il ne
    possède pas (pour proposer de les retirer en bloc)."""
    return sum(1 for n in notes if n.cree_par_id == user.id)


@register.filter(name="peut_supprimer")
def peut_supprimer(note, user):
    """Qui peut déclencher "supprimer" : le prof (suppression réelle) ou
    quiconque a cette carte dans sa révision (simple retrait de sa propre
    carte — voir anki_review.views.supprimer_note pour le détail complet,
    notamment le transfert de propriété)."""
    return user.is_staff or note.cards.filter(etudiant=user).exists()


@register.filter(name="peut_editer_deck")
def peut_editer_deck(deck, user):
    """Même principe que peut_editer, pour un Deck plutôt qu'une Note."""
    return user.is_staff or deck.cree_par_id == user.id


@register.filter(name="resoudre_images")
def resoudre_images(html):
    """Reconstitue les URLs d'images à partir des noms de fichiers nus.

    Le HTML est d'abord NETTOYÉ (voir html_propre.py) : les cartes sont saisies par n'importe
    quel utilisateur connecté, élèves compris, et affichées à d'autres (dont les professeurs).
    Ce nettoyage à l'affichage protège aussi les cartes enregistrées avant que Note.save() ne
    nettoie. Seul le résultat nettoyé est marqué sûr."""
    if not html:
        return html
    propre = nettoyer_html(html)
    resultat = _RE_IMG_SRC_NU.sub(
        lambda m: f'src="{PREFIXE_IMAGES_NOTES}{m.group(1)}"', propre
    )
    return mark_safe(resultat)
