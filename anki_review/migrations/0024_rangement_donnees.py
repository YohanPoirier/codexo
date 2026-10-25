"""Rangement personnel (2/3) : chacun reçoit ses propres paquets.

Avant : un paquet appartenait à un créateur, et tout le monde y rangeait ses cartes.
Après : chaque carte est rangée dans un paquet À SON DÉTENTEUR. Pour que chacun retrouve
exactement ce qu'il voyait, une carte rangée dans le paquet d'un autre (le professeur, un
camarade) est rangée dans un paquet à soi, de même nom et de même matière, créé au besoin.

- Un paquet sans propriétaire (professeur supprimé, import ancien) est confié au premier
  professeur.
- Pour chaque note, Note.deck devient le paquet de son AUTEUR (là où l'auteur la range).
- Ce paquet à soi reçoit aussi la règle de rangement correspondante (les prochaines cartes du même
  paquet d'origine iront au même endroit).
- Aucune carte, aucune note, aucun paquet n'est supprimé.
- Contrôle final : chaque carte a un paquet qui est à son détenteur, de même nom que l'ancien.
"""
from django.conf import settings
from django.db import migrations


def _slug_unique(Deck, nom):
    from anki_review.slugs import slug_de_base

    base = slug_de_base(nom)
    slug, numero = base, 2
    while Deck.objects.filter(slug=slug).exists():
        slug = f"{base}-{numero}"
        numero += 1
    return slug


def repartir_les_paquets(apps, schema_editor):
    Deck = apps.get_model("anki_review", "Deck")
    Note = apps.get_model("anki_review", "Note")
    Card = apps.get_model("anki_review", "Card")
    Utilisateur = apps.get_model(settings.AUTH_USER_MODEL)

    premier_prof = Utilisateur.objects.filter(is_staff=True).order_by("id").first()
    if premier_prof:
        Deck.objects.filter(cree_par__isnull=True).update(cree_par=premier_prof)

    copies = {}  # (id du paquet d'origine, id du détenteur) -> id du paquet du détenteur

    def paquet_de(deck, utilisateur_id):
        if deck.cree_par_id == utilisateur_id:
            return deck
        cle = (deck.id, utilisateur_id)
        if cle not in copies:
            existant = Deck.objects.filter(
                cree_par_id=utilisateur_id, nom=deck.nom, matiere=deck.matiere
            ).first()
            if existant is None:
                existant = Deck.objects.create(
                    nom=deck.nom, matiere=deck.matiere, description=deck.description,
                    slug=_slug_unique(Deck, deck.nom), cree_par_id=utilisateur_id,
                )
            copies[cle] = existant
        return copies[cle]

    avant = Card.objects.count()
    for carte in Card.objects.select_related("note", "note__deck").order_by("id").iterator():
        if carte.note.deck_id is None:
            continue
        carte.deck = paquet_de(carte.note.deck, carte.etudiant_id)
        carte.save(update_fields=["deck"])

    # Note.deck = paquet de l'auteur, quand l'auteur a la carte.
    for note in Note.objects.exclude(cree_par__isnull=True).select_related("deck").iterator():
        carte = Card.objects.filter(note=note, etudiant_id=note.cree_par_id).first()
        if carte is not None and carte.deck_id and note.deck_id != carte.deck_id:
            note.deck_id = carte.deck_id
            note.save(update_fields=["deck"])

    # Règles de rangement : qui a déjà des cartes d'un autre reçoit, en plus de son paquet à lui,
    # la règle « les cartes de ce paquet d'origine vont dans celui-là » (pour l'avenir seulement).
    Regle = apps.get_model("anki_review", "RegleRangement")
    for carte in Card.objects.select_related("note__deck", "deck").order_by("id").iterator():
        origine = carte.note.deck
        if origine is None or origine.cree_par_id == carte.etudiant_id or origine.id == carte.deck_id:
            continue
        Regle.objects.get_or_create(
            etudiant_id=carte.etudiant_id, origine=origine, defaults={"destination": carte.deck},
        )

    # Contrôles : rien de perdu, tout le monde chez soi.
    assert Card.objects.count() == avant, "nombre de cartes modifié"
    assert not Card.objects.filter(deck__isnull=True).exists(), "carte sans paquet"
    for carte in Card.objects.select_related("deck").iterator():
        assert carte.deck.cree_par_id == carte.etudiant_id, f"carte {carte.id} dans un paquet qui n'est pas à son détenteur"


class Migration(migrations.Migration):

    dependencies = [
        ("anki_review", "0023_rangement_schema"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(repartir_les_paquets, migrations.RunPython.noop)]
