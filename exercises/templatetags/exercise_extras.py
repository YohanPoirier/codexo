import textwrap

import bleach
import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Balises autorisées après rendu Markdown — tout le reste est retiré.
ALLOWED_TAGS = [
    "p", "br", "strong", "em", "code", "pre",
    "ul", "ol", "li", "a", "blockquote", "h3", "h4",
]
ALLOWED_ATTRS = {"a": ["href", "title", "rel"]}


@register.filter
def render_statement(text):
    # Retire l'indentation commune en début de lignes : sans ça, un simple
    # copier-coller avec des espaces au début transforme accidentellement
    # tout le paragraphe en bloc de code (comportement natif de Markdown).
    text = textwrap.dedent(text).strip()
    html = md.markdown(text, extensions=["fenced_code"])
    clean_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return mark_safe(clean_html)


@register.filter
def get_item(dictionary, key):
    """Permet d'accéder à dictionnaire[clé] dans un template quand la clé est une variable
    (ex: {{ locked_retry_at|get_item:exercise.id }}) — Django ne supporte pas nativement
    ce genre d'accès dynamique via la notation par point."""
    return dictionary.get(key)


@register.filter
def duree_lisible(total_seconds):
    """Convertit un nombre de secondes (ex: Result.time_seconds sommé) en texte lisible,
    pour la page de stats. Ex : 45 -> "45 s", 125 -> "2 min 05 s", 3700 -> "1 h 01 min"."""
    try:
        total_seconds = int(total_seconds or 0)
    except (TypeError, ValueError):
        return "0 s"

    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {seconds:02d} s"
    return f"{seconds} s"
