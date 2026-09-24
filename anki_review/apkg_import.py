"""
Import de paquets .apkg (format Anki) vers nos modèles Deck/Note/Card.

Le flux se fait en DEUX temps, pour permettre à l'utilisateur de choisir
quels paquets/cartes importer plutôt que tout prendre en bloc :
1. analyser_apkg() lit le fichier et renvoie un résumé (paquets, cartes),
   SANS RIEN ÉCRIRE EN BASE — utilisé pour afficher l'écran de sélection.
2. importer_apkg() refait la même lecture (le fichier est ré-ouvert), mais
   n'importe que les notes dont le guid est dans `guids_selectionnes`
   (ou tout, si ce paramètre vaut None).

Structure d'un .apkg (une archive zip) :
- collection.anki21 (SQLite, non compressé) OU collection.anki21b (SQLite
  compressé zstd, versions récentes d'Anki) OU collection.anki2 (très
  ancien schéma) — on essaie les trois, dans cet ordre de préférence.
- un fichier "media" (JSON : {"0": "nom_original.jpg", ...}) associant
  chaque fichier numéroté de l'archive (0, 1, 2...) à son nom d'origine.

Tables SQLite utiles :
- col (une seule ligne) : colonnes "models" (JSON, types de notes) et
  "decks" (JSON, paquets Anki) — présentes même sur les schémas récents,
  gardées pour la compatibilité ascendante par Anki lui-même.
- notes : guid, mid (id du type de note), flds (champs joints par le
  caractère \x1f), tags.
- cards : nid (note liée), did (paquet Anki), et les champs de
  planification SM-2 (ivl, factor, reps, lapses...).

Simplifications volontaires (à affiner une fois testé contre de vrais
fichiers) :
- seules les notes à 2 champs (type "Basique") sont importées ; les notes
  de type Cloze sont comptabilisées et ignorées ;
- la progression SM-2 (intervalle, facilité, répétitions) est reprise,
  mais chaque carte importée est remise "à réviser maintenant" plutôt que
  de recalculer sa date d'échéance exacte (le calcul réel dépend du fuseau
  horaire et de l'heure de rollover configurés dans Anki, difficile à
  reproduire fidèlement sans pouvoir tester contre le fichier réel).
"""
import html
import json
import re
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from .models import Activite, Card, Deck, Note

SEPARATEUR_CHAMPS = "\x1f"


class ErreurImportApkg(Exception):
    """Erreur "attendue" (fichier invalide, format non supporté...) — le
    message est montré tel quel à l'utilisateur, contrairement à une
    exception inattendue qui remonterait une page d'erreur Django."""


def _ouvrir_base_sqlite(archive, dossier_tmp: Path) -> Path:
    """Extrait et renvoie le chemin de la base SQLite de la collection, en
    gérant le cas compressé (zstd, Anki récent) et non compressé."""
    noms = archive.namelist()

    if "collection.anki21b" in noms:
        try:
            import zstandard
        except ImportError:
            raise ErreurImportApkg(
                "Ce fichier .apkg utilise un format compressé récent (zstd). "
                "Il faut installer le module manquant : pip install zstandard"
            )
        brut = archive.read("collection.anki21b")
        decompresse = zstandard.ZstdDecompressor().decompress(brut)
        chemin = dossier_tmp / "collection.sqlite"
        chemin.write_bytes(decompresse)
        return chemin

    for nom in ("collection.anki21", "collection.anki2"):
        if nom in noms:
            chemin = dossier_tmp / "collection.sqlite"
            chemin.write_bytes(archive.read(nom))
            return chemin

    raise ErreurImportApkg("Fichier .apkg invalide : aucune base de collection trouvée à l'intérieur.")


def _lire_media(archive) -> dict:
    """Renvoie {nom_original: contenu_binaire} pour chaque fichier média de
    l'archive, à partir du fichier "media" (JSON {"0": "nom.jpg", ...})."""
    if "media" not in archive.namelist():
        return {}
    mapping = json.loads(archive.read("media").decode("utf-8"))
    resultat = {}
    for numero, nom_original in mapping.items():
        if numero in archive.namelist():
            resultat[nom_original] = archive.read(numero)
    return resultat


_RE_IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"')


def _sauver_medias_references(html_texte: str, medias: dict, medias_deja_sauves: dict) -> str:
    """Pour chaque <img src="..."> du texte dont le nom correspond à un
    fichier média de l'archive, sauvegarde ce fichier dans MEDIA_ROOT (sous
    un nom généré, comme le fait déjà l'éditeur du site) et réécrit la
    balise pour pointer vers ce nouveau nom — medias_deja_sauves évite de
    sauvegarder deux fois la même image si elle apparaît sur plusieurs cartes."""

    def remplacer(m):
        nom_original = m.group(1)
        if nom_original in medias_deja_sauves:
            nouveau_nom = medias_deja_sauves[nom_original]
        elif nom_original in medias:
            extension = "." + nom_original.rsplit(".", 1)[-1].lower() if "." in nom_original else ""
            nouveau_nom = f"{uuid.uuid4().hex}{extension}"
            default_storage.save(f"anki_review/notes/{nouveau_nom}", ContentFile(medias[nom_original]))
            medias_deja_sauves[nom_original] = nouveau_nom
        else:
            return m.group(0)  # référence introuvable dans l'archive : laissée telle quelle
        return m.group(0).replace(f'src="{nom_original}"', f'src="{nouveau_nom}"')

    return _RE_IMG_SRC.sub(remplacer, html_texte)


def _lire_contenu_brut(fichier_django):
    """
    Ouvre le fichier .apkg et renvoie toutes les données lues depuis le
    SQLite, sous une forme simple exploitable aussi bien par analyser_apkg
    (aperçu) que par importer_apkg (import réel) — évite de dupliquer la
    lecture zip/SQLite dans les deux fonctions.

    Renvoie : (lignes_notes, deck_par_note, planning_par_note, decks_anki,
    medias, ids_modeles_cloze), ou lève ErreurImportApkg.
    """
    with tempfile.TemporaryDirectory() as dossier_tmp_str:
        dossier_tmp = Path(dossier_tmp_str)
        try:
            archive = zipfile.ZipFile(fichier_django)
        except zipfile.BadZipFile:
            raise ErreurImportApkg("Ce fichier ne ressemble pas à un .apkg valide (pas une archive zip).")

        chemin_sqlite = _ouvrir_base_sqlite(archive, dossier_tmp)
        medias = _lire_media(archive)

        connexion = sqlite3.connect(str(chemin_sqlite))
        connexion.row_factory = sqlite3.Row
        curseur = connexion.cursor()

        curseur.execute("SELECT models, decks FROM col LIMIT 1")
        ligne_col = curseur.fetchone()
        if ligne_col is None:
            connexion.close()
            raise ErreurImportApkg("Fichier .apkg invalide : table de collection vide.")

        modeles = json.loads(ligne_col["models"])
        decks_anki = json.loads(ligne_col["decks"])

        ids_modeles_cloze = {
            mid for mid, m in modeles.items()
            if "cloze" in m.get("name", "").lower() or m.get("type") == 1
        }

        curseur.execute("SELECT id, guid, mid, flds, tags FROM notes")
        lignes_notes = [dict(l) for l in curseur.fetchall()]

        curseur.execute("SELECT nid, did FROM cards")
        deck_par_note = {}
        for ligne in curseur.fetchall():
            deck_par_note.setdefault(ligne["nid"], ligne["did"])

        curseur.execute("SELECT nid, ivl, factor, reps, lapses FROM cards")
        planning_par_note = {}
        for ligne in curseur.fetchall():
            planning_par_note.setdefault(ligne["nid"], dict(ligne))

        connexion.close()
        return lignes_notes, deck_par_note, planning_par_note, decks_anki, medias, ids_modeles_cloze


def analyser_apkg(fichier_django):
    """
    Lit le fichier et renvoie un résumé SANS RIEN ÉCRIRE EN BASE, pour
    l'écran de sélection : (liste_de_paquets, nb_cloze) où liste_de_paquets
    est une liste de {"nom_deck": ..., "notes": [{"guid":, "titre":}, ...]}.
    """
    lignes_notes, deck_par_note, _planning, decks_anki, _medias, ids_modeles_cloze = \
        _lire_contenu_brut(fichier_django)

    par_deck = {}
    nb_cloze = 0
    for ligne in lignes_notes:
        if str(ligne["mid"]) in ids_modeles_cloze:
            nb_cloze += 1
            continue
        champs = ligne["flds"].split(SEPARATEUR_CHAMPS)
        if len(champs) < 2:
            continue
        did_anki = deck_par_note.get(ligne["id"])
        nom_deck_anki = decks_anki.get(str(did_anki), {}).get("name", "Importé") if did_anki else "Importé"
        titre = html.unescape(strip_tags(champs[0]))[:80]
        par_deck.setdefault(nom_deck_anki, []).append({"guid": ligne["guid"], "titre": titre})

    return [{"nom_deck": k, "notes": v} for k, v in par_deck.items()], nb_cloze


def importer_apkg(fichier_django, utilisateur, guids_selectionnes=None) -> dict:
    """
    Importe le contenu du fichier vers nos modèles, en ne retenant que les
    notes dont le guid figure dans `guids_selectionnes` (toutes, si ce
    paramètre vaut None).

    `utilisateur` devient le propriétaire (cree_par) de tout ce qui est
    importé — comme pour n'importe quelle création de contenu sur le site
    (privé par défaut, à partager explicitement ensuite si besoin).

    Renvoie un résumé : {"decks", "notes_creees", "notes_mises_a_jour",
    "cartes_ignorees_cloze"}. Lève ErreurImportApkg pour toute erreur
    destinée à être montrée telle quelle à l'utilisateur.
    """
    lignes_notes, deck_par_note, planning_par_note, decks_anki, medias, ids_modeles_cloze = \
        _lire_contenu_brut(fichier_django)

    cache_decks = {}

    def _obtenir_deck(nom_anki):
        if nom_anki in cache_decks:
            return cache_decks[nom_anki]
        nom_propre = nom_anki.replace("::", " — ")  # paquets imbriqués Anki -> nom plat
        deck = Deck.objects.filter(nom=nom_propre, cree_par=utilisateur).first()
        if deck is None:
            slug_base = slugify(nom_propre) or "paquet"
            slug = slug_base
            i = 2
            while Deck.objects.filter(slug=slug).exists():
                slug = f"{slug_base}-{i}"
                i += 1
            deck = Deck.objects.create(nom=nom_propre, slug=slug, cree_par=utilisateur)
        cache_decks[nom_anki] = deck
        return deck

    medias_deja_sauves = {}
    nb_notes_creees = 0
    nb_notes_maj = 0
    nb_cloze_ignorees = 0
    decks_touches = set()

    for ligne in lignes_notes:
        mid = str(ligne["mid"])
        if mid in ids_modeles_cloze:
            nb_cloze_ignorees += 1
            continue

        if guids_selectionnes is not None and ligne["guid"] not in guids_selectionnes:
            continue

        champs = ligne["flds"].split(SEPARATEUR_CHAMPS)
        if len(champs) < 2:
            continue
        question = _sauver_medias_references(champs[0], medias, medias_deja_sauves)
        reponse = _sauver_medias_references(champs[1], medias, medias_deja_sauves)

        did_anki = deck_par_note.get(ligne["id"])
        nom_deck_anki = decks_anki.get(str(did_anki), {}).get("name", "Importé") if did_anki else "Importé"
        deck = _obtenir_deck(nom_deck_anki)
        decks_touches.add(deck.id)

        guid = ligne["guid"]
        tags = ligne["tags"].strip()

        note_existante = Note.objects.filter(guid=guid, cree_par=utilisateur).first()
        if note_existante:
            note_existante.question = question
            note_existante.reponse = reponse
            note_existante.tags = tags
            note_existante.deck = deck
            note_existante.save()
            note = note_existante
            nb_notes_maj += 1
        else:
            note = Note.objects.create(
                guid=guid, deck=deck, question=question, reponse=reponse,
                tags=tags, cree_par=utilisateur, partagee_avec_classe=False,
            )
            nb_notes_creees += 1

        planning = planning_par_note.get(ligne["id"])
        carte, carte_creee = Card.objects.get_or_create(note=note, etudiant=utilisateur)
        if carte_creee:
            # Une carte importée depuis un .apkg compte comme un ajout (page Trafic).
            Activite.journaliser(utilisateur, Activite.Type.AJOUT, carte)
        if planning:
            ivl = planning["ivl"] or 0
            carte.intervalle_jours = abs(ivl) if ivl >= 0 else abs(ivl) / 86400
            carte.facteur_facilite = (planning["factor"] or 2500) / 1000
            carte.repetitions = planning["reps"] or 0
            carte.echecs = planning["lapses"] or 0
        carte.prochaine_revision = timezone.now()
        carte.save()

    return {
        "decks": len(decks_touches),
        "notes_creees": nb_notes_creees,
        "notes_mises_a_jour": nb_notes_maj,
        "cartes_ignorees_cloze": nb_cloze_ignorees,
    }
