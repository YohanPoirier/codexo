"""Nettoyage du HTML des cartes (question / réponse).

Les cartes contiennent du HTML saisi par n'importe quel utilisateur connecté (élèves compris),
puis partagé à la classe et affiché aux professeurs. Sans nettoyage, une carte contenant
<img onerror="…"> ou <script> s'exécutait dans la session de celui qui la regarde.

Le filtre garde ce que produisent l'éditeur du site et les éditeurs d'Anki (PC et web) :
gras, italique, souligné, listes, centrage, couleurs, images, tableaux, liens… et supprime le
reste (scripts, gestionnaires d'événements comme onerror/onclick, iframe, svg, adresses
javascript:, styles dangereux).
"""
import re

import bleach
from bleach.css_sanitizer import CSSSanitizer

# Images acceptées pour une carte (éditeur du site ET import .apkg) : jamais de SVG ni de HTML,
# qui peuvent contenir du code exécuté quand le fichier est ouvert depuis /media/.
EXTENSIONS_IMAGE_AUTORISEES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

BALISES_AUTORISEES = [
    "b", "strong", "i", "em", "u", "br", "p", "div", "span", "font", "sub", "sup",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th", "code", "pre", "hr",
    "img", "a",
]

ATTRIBUTS_AUTORISES = {
    "*": ["style"],  # filtré propriété par propriété (voir PROPRIETES_CSS_AUTORISEES)
    "img": ["src", "alt", "width", "height"],
    "a": ["href"],
    "font": ["color", "size"],
    # Centrage « à l'ancienne » d'Anki : <div align="center"> (valeur sans danger).
    "div": ["align"],
    "p": ["align"],
    "table": ["align"],
    "hr": ["align"],
    "td": ["colspan", "rowspan", "align"],
    "th": ["colspan", "rowspan", "align"],
}

PROTOCOLES_AUTORISES = ["http", "https", "mailto"]

# « text-align » : le bouton « Centrer » de l'éditeur produit <div style="text-align: center">.
# Les couleurs viennent des éditeurs d'Anki.
PROPRIETES_CSS_AUTORISEES = [
    "text-align", "color", "background-color", "font-weight", "font-style", "text-decoration",
]

_CSS = CSSSanitizer(allowed_css_properties=PROPRIETES_CSS_AUTORISEES)

# bleach garde le TEXTE des balises qu'il retire : sans cette étape, le contenu d'un <script>
# ou d'un <style> resterait visible sur la carte.
_RE_BLOCS_ACTIFS = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def nettoyer_html(html):
    """HTML de carte débarrassé de tout ce qui pourrait exécuter du code. Idempotent
    (nettoyer deux fois donne le même résultat) ; une valeur vide est renvoyée telle quelle."""
    if not html:
        return html or ""
    html = _RE_BLOCS_ACTIFS.sub("", html)
    return bleach.clean(
        html,
        tags=BALISES_AUTORISEES,
        attributes=ATTRIBUTS_AUTORISES,
        protocols=PROTOCOLES_AUTORISES,
        css_sanitizer=_CSS,
        strip=True,
        strip_comments=True,
    )
