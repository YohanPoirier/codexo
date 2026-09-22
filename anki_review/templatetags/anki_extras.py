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

register = template.Library()

PREFIXE_IMAGES_NOTES = f"{settings.MEDIA_URL}anki_review/notes/"

# Ne réécrit PAS les src qui commencent déjà par "/" (chemin absolu) ou par
# un schéma http(s):// — uniquement les noms de fichiers nus.
_RE_IMG_SRC_NU = re.compile(r'src="(?!https?://|/)([^"]+)"')


@register.filter(name="peut_editer")
def peut_editer(note, user):
    """Le prof peut tout modifier ; un étudiant ne peut modifier que ses
    propres notes. Utilisé dans les templates pour n'afficher l'icône
    modifier que là où l'action est vraiment permise."""
    return user.is_staff or note.cree_par_id == user.id


@register.filter(name="compte_notes_de")
def compte_notes_de(notes, user):
    """Nombre de notes, parmi une liste, appartenant à cet utilisateur —
    sert à savoir s'il a des cartes personnelles dans un paquet qu'il ne
    possède pas (pour proposer de les retirer en bloc)."""
    return sum(1 for n in notes if n.cree_par_id == user.id)


@register.filter(name="peut_supprimer")
def peut_supprimer(note, user):
    """Suppression réservée au propriétaire de la note, sans exception
    prof — voir _peut_supprimer_note côté vue pour le pourquoi."""
    return note.cree_par_id == user.id


@register.filter(name="peut_editer_deck")
def peut_editer_deck(deck, user):
    """Même principe que peut_editer, pour un Deck plutôt qu'une Note."""
    return user.is_staff or deck.cree_par_id == user.id


@register.filter(name="resoudre_images")
def resoudre_images(html):
    """Reconstitue les URLs d'images à partir des noms de fichiers nus.
    Le résultat est marqué safe : ce filtre s'applique à du contenu déjà
    considéré comme HTML de confiance (saisi par un enseignant), au même
    titre que l'usage de |safe déjà fait sur ces champs ailleurs."""
    if not html:
        return html
    resultat = _RE_IMG_SRC_NU.sub(
        lambda m: f'src="{PREFIXE_IMAGES_NOTES}{m.group(1)}"', html
    )
    return mark_safe(resultat)
