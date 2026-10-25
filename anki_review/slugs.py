"""Adresse (slug) d'un paquet : /anki/<slug>/.

Deux pièges évités ici :
- un nom sans lettre ni chiffre (« ??? », un emoji) donnerait un slug vide, et la page
  d'accueil d'Anki plantait (adresse impossible à construire) ;
- un nom comme « Trafic » donnerait /anki/trafic/, qui est déjà l'adresse d'une autre page :
  le paquet devenait inaccessible (la route générique « paquet à réviser » est en dernier).
"""
from django.utils.text import slugify

# Premiers segments des adresses fixes d'anki_review/urls.py : un paquet ne doit jamais en
# porter un comme slug. Un test compare cette liste aux routes réelles pour ne rien oublier.
SLUGS_RESERVES = frozenset({
    "trafic", "edition", "paquets", "ajouter", "cartes", "uploader-image",
    "matiere", "import-export", "propositions", "notifications", "deplacements",
})

SLUG_PAR_DEFAUT = "paquet"
LONGUEUR_BASE_MAX = 40  # SlugField : 50 caractères au total, il faut de la place pour « -12 »


def slug_de_base(nom):
    """Slug sans numéro de doublon : jamais vide, jamais réservé."""
    base = slugify(nom or "")[:LONGUEUR_BASE_MAX].strip("-") or SLUG_PAR_DEFAUT
    if base in SLUGS_RESERVES:
        base = f"{base}-{SLUG_PAR_DEFAUT}"
    return base


def slug_unique(nom, exclure_pk=None):
    """Slug de base, suivi de -2, -3… tant qu'un autre paquet le porte déjà."""
    from .models import Deck

    base = slug_de_base(nom)
    slug, numero = base, 2
    while Deck.objects.filter(slug=slug).exclude(pk=exclure_pk).exists():
        slug = f"{base}-{numero}"
        numero += 1
    return slug
