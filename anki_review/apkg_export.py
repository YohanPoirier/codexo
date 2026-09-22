"""
Export d'une sélection de notes vers un fichier .apkg, importable dans
Anki — les notes peuvent appartenir à plusieurs paquets différents, chacun
devient son propre paquet Anki à l'intérieur du même fichier .apkg.

Choix technique : on s'appuie sur la bibliothèque `genanki` plutôt que de
reconstruire à la main le schéma SQLite interne d'Anki — plus fiable sans
pouvoir tester contre un vrai import Anki en direct.

Simplification volontaire (symétrique à l'import) : seul le CONTENU est
exporté fidèlement (question, réponse, images, LaTeX, tags, guid) ; la
progression SM-2 n'est pas transférée — les cartes repartent "neuves" côté
Anki, comme n'importe quelle nouvelle carte importée.
"""
import re
import tempfile
from pathlib import Path

import genanki

from django.conf import settings

from .models import Deck

# Id de modèle FIXE et arbitraire (ne jamais changer une fois des fichiers
# exportés en circulation : Anki s'en sert pour reconnaître le type de note
# d'un import à l'autre — on l'a vérifié : changer de modèle pour une carte
# déjà importée bloque sa mise à jour côté Anki, sauf à activer "Fusionner
# les types de notes" à chaque import). UN SEUL modèle, toujours à 3
# champs : le Titre vaut le titre saisi, ou la question en repli s'il n'y
# en a pas (cf. Note.titre_affichage) — comme pour n'importe quel paquet
# Anki classique où le premier champ sert à la fois d'aperçu-liste et de
# contenu de révision, ce n'est pas une "duplication" au sens où Anki
# l'entend, juste son fonctionnement standard.
_ID_MODELE_BASIQUE = 1968100421

MODELE_BASIQUE = genanki.Model(
    _ID_MODELE_BASIQUE,
    "Basique (export du site)",
    # Titre en premier champ : c'est lui qu'Anki utilise par défaut comme
    # "sort field", affiché dans le navigateur de cartes (desktop et
    # AnkiDroid) — jamais montré pendant la révision elle-même, puisque les
    # templates ci-dessous ne le référencent pas.
    fields=[{"name": "Titre"}, {"name": "Front"}, {"name": "Back"}],
    templates=[{
        "name": "Carte 1",
        "qfmt": "{{Front}}",
        "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
    }],
)

_RE_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"')


def _id_stable(texte: str) -> int:
    """Anki attend un identifiant numérique pour chaque paquet exporté —
    on en dérive un de façon stable à partir du slug, pour que ré-exporter
    le même paquet plus tard produise le même id."""
    return abs(hash(texte)) % (2**31)


def _nom_paquet_anki(deck) -> str:
    """Nom du paquet côté Anki — imbriqué sous sa matière avec la syntaxe
    "::" (paquets imbriqués Anki), comme Physique::Optique ; à plat si le
    paquet n'a pas de matière."""
    if deck.matiere:
        libelle_matiere = dict(Deck.Matiere.choices).get(deck.matiere, deck.matiere)
        return f"{libelle_matiere}::{deck.nom}"
    return deck.nom


def exporter_notes_apkg(notes) -> bytes:
    """
    Construit le contenu binaire d'un .apkg à partir de `notes` (déjà
    filtrées par l'appelant selon ce que l'utilisateur a le droit de voir
    — cf. la vue). Les notes de paquets différents deviennent chacune leur
    propre paquet Anki à l'intérieur du même fichier.

    Renvoie les octets du fichier .apkg prêt à être proposé en
    téléchargement.
    """
    paquets_anki = {}  # deck_id -> genanki.Deck
    chemins_media = []
    medias_deja_ajoutes = set()

    for note in notes:
        deck = note.deck
        if deck.id not in paquets_anki:
            paquets_anki[deck.id] = genanki.Deck(_id_stable(deck.slug), _nom_paquet_anki(deck))

        for champ in (note.question, note.reponse):
            for nom_fichier in _RE_IMG_SRC.findall(champ):
                if nom_fichier in medias_deja_ajoutes:
                    continue
                chemin = Path(settings.MEDIA_ROOT) / "anki_review" / "notes" / nom_fichier
                if chemin.exists():
                    chemins_media.append(str(chemin))
                    medias_deja_ajoutes.add(nom_fichier)

        note_anki = genanki.Note(
            model=MODELE_BASIQUE,
            fields=[note.titre_affichage(), note.question, note.reponse],
            guid=note.guid,
            tags=note.tags.split() if note.tags else [],
        )
        paquets_anki[deck.id].add_note(note_anki)

    package = genanki.Package(list(paquets_anki.values()))
    package.media_files = chemins_media

    with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as f:
        chemin_temp = f.name
    try:
        package.write_to_file(chemin_temp)
        return Path(chemin_temp).read_bytes()
    finally:
        Path(chemin_temp).unlink(missing_ok=True)
