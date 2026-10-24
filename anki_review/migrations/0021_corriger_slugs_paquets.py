"""Rattrapage : donne une adresse correcte aux paquets dont le slug est vide ou réservé.

Sans effet (aucune ligne modifiée) s'il n'y en a pas. Seule l'adresse du paquet change : ses
cartes et la progression des élèves ne sont pas touchées.

La logique est volontairement recopiée ici (et non importée depuis anki_review/slugs.py) :
une migration doit garder le même comportement même si ce module évolue plus tard.
"""
from django.db import migrations
from django.utils.text import slugify

RESERVES = {
    "trafic", "edition", "paquets", "ajouter", "cartes", "uploader-image",
    "matiere", "import-export", "propositions", "notifications",
}


def corriger_slugs(apps, schema_editor):
    Deck = apps.get_model("anki_review", "Deck")
    pris = set(Deck.objects.values_list("slug", flat=True))
    for deck in Deck.objects.order_by("id"):
        if deck.slug and deck.slug not in RESERVES:
            continue
        base = slugify(deck.nom or "")[:40].strip("-") or "paquet"
        if base in RESERVES:
            base = f"{base}-paquet"
        slug, numero = base, 2
        while slug in pris:
            slug = f"{base}-{numero}"
            numero += 1
        pris.add(slug)
        deck.slug = slug
        deck.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("anki_review", "0020_planification_notifications"),
    ]

    operations = [
        migrations.RunPython(corriger_slugs, migrations.RunPython.noop),
    ]
