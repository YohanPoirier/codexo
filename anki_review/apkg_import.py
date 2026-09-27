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
import io
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

from .models import Card, Deck, Note

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
            import zstandard  # noqa: F401 — juste pour vérifier la présence du module ici
        except ImportError:
            raise ErreurImportApkg(
                "Ce fichier .apkg utilise un format compressé récent (zstd). "
                "Il faut installer le module manquant : pip install zstandard"
            )
        # _decompresser_si_zstd() utilise stream_reader(), qui n'a pas besoin
        # de connaître la taille décompressée à l'avance — contrairement à
        # .decompress() seul, qui échoue sur les frames "récentes" (Anki
        # 2.1.50+, écrites en streaming, sans cette taille dans l'en-tête)
        # avec "could not determine content size in frame header".
        decompresse = _decompresser_si_zstd(archive.read("collection.anki21b"))
        chemin = dossier_tmp / "collection.sqlite"
        chemin.write_bytes(decompresse)
        return chemin

    for nom in ("collection.anki21", "collection.anki2"):
        if nom in noms:
            chemin = dossier_tmp / "collection.sqlite"
            chemin.write_bytes(archive.read(nom))
            return chemin

    raise ErreurImportApkg("Fichier .apkg invalide : aucune base de collection trouvée à l'intérieur.")


_SIGNATURE_ZSTD = b"\x28\xb5\x2f\xfd"


def _decompresser_si_zstd(brut: bytes) -> bytes:
    """Décompresse `brut` s'il commence par la signature zstd, sinon le
    renvoie inchangé. stream_reader() n'a pas besoin de connaître la taille
    décompressée à l'avance (cf. _ouvrir_base_sqlite), donc gère aussi bien
    les frames "récentes" (sans taille dans l'en-tête) que les anciennes."""
    if brut[:4] != _SIGNATURE_ZSTD:
        return brut
    import zstandard
    dctx = zstandard.ZstdDecompressor()
    with dctx.stream_reader(io.BytesIO(brut)) as lecteur:
        return lecteur.read()


def _lire_varint(donnees: bytes, pos: int):
    """Lit un varint Protobuf à partir de `pos` ; renvoie (valeur, nouvelle_pos)."""
    resultat = 0
    decalage = 0
    while True:
        octet = donnees[pos]
        pos += 1
        resultat |= (octet & 0x7F) << decalage
        if not (octet & 0x80):
            return resultat, pos
        decalage += 7


def _lire_nom_media_entry(sous_message: bytes):
    """Extrait le champ 1 (name, string) d'un message Protobuf MediaEntry ;
    les autres champs (size, sha1) sont ignorés — on n'en a pas besoin."""
    pos = 0
    taille_totale = len(sous_message)
    while pos < taille_totale:
        etiquette, pos = _lire_varint(sous_message, pos)
        champ, type_fil = etiquette >> 3, etiquette & 0x7
        if type_fil == 2:  # length-delimited (string/bytes/sous-message)
            taille, pos = _lire_varint(sous_message, pos)
            valeur = sous_message[pos:pos + taille]
            pos += taille
            if champ == 1:
                return valeur.decode("utf-8")
        elif type_fil == 0:  # varint
            _, pos = _lire_varint(sous_message, pos)
        elif type_fil == 1:  # 64 bits fixe
            pos += 8
        elif type_fil == 5:  # 32 bits fixe
            pos += 4
        else:
            return None
    return None


def _lire_media_protobuf(brut: bytes) -> dict:
    """Parse le message Protobuf `MediaEntries` (format récent d'Anki,
    remplace le JSON des versions plus anciennes) : une liste de
    MediaEntry (champ 1, répété), chacun contenant au moins un nom (champ
    1, string) — l'index dans la liste correspond au nom de fichier numéroté
    dans l'archive (0, 1, 2...), exactement comme les clés du JSON legacy."""
    pos = 0
    taille_totale = len(brut)
    noms = []
    while pos < taille_totale:
        etiquette, pos = _lire_varint(brut, pos)
        champ, type_fil = etiquette >> 3, etiquette & 0x7
        if type_fil != 2:
            raise ErreurImportApkg("Format du fichier media (Protobuf) non reconnu.")
        taille, pos = _lire_varint(brut, pos)
        valeur = brut[pos:pos + taille]
        pos += taille
        if champ == 1:
            noms.append(_lire_nom_media_entry(valeur))
    return {str(i): nom for i, nom in enumerate(noms) if nom is not None}


def _lire_media(archive) -> dict:
    """Renvoie {nom_original: contenu_binaire} pour chaque fichier média de
    l'archive, à partir du fichier "media". Ce fichier a deux formats
    possibles selon la version d'Anki ayant fait l'export :
    - ancien : JSON en clair, {"0": "nom.jpg", ...} ;
    - récent : compressé zstd, contenant un message Protobuf MediaEntries
      plutôt que du JSON (cf. _lire_media_protobuf)."""
    if "media" not in archive.namelist():
        return {}
    brut = _decompresser_si_zstd(archive.read("media"))
    try:
        mapping = json.loads(brut.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        mapping = _lire_media_protobuf(brut)
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


def _lire_modeles(curseur, models_brut) -> dict:
    """Renvoie {mid (str): {"name": ...}} (et "type" si disponible), pour
    repérer les notes Cloze par nom ensuite. Sur les schémas anciens,
    col.models contient directement ce JSON ; sur les schémas récents,
    cette colonne est vide et les types de note vivent dans leur propre
    table `notetypes` — leur config (Protobuf) n'est pas décodée ici, donc
    seul le nom est récupéré (suffisant pour la détection Cloze par nom,
    déjà utilisée en complément du champ "type" absent sur ce schéma)."""
    if models_brut:
        try:
            return json.loads(models_brut)
        except json.JSONDecodeError:
            pass
    curseur.execute("SELECT id, name FROM notetypes")
    return {str(ligne["id"]): {"name": ligne["name"]} for ligne in curseur.fetchall()}


def _lire_decks(curseur, decks_brut) -> dict:
    """Renvoie {did (str): {"name": ...}} — même bascule que _lire_modeles :
    col.decks JSON sur les schémas anciens, table `decks` (colonne `name`
    en clair, pas de Protobuf à décoder ici) sur les schémas récents.

    Sur ce schéma récent, un nom de paquet imbriqué ("Physique" >
    "Thermodynamique") est stocké avec le même séparateur \\x1f que les
    champs d'une note, plutôt que "::" comme dans le JSON de l'ancien
    schéma — normalisé ici vers "::" pour que le reste du code (qui ne
    connaît que "::", cf. importer_apkg) n'ait pas à distinguer les deux."""
    if decks_brut:
        try:
            return json.loads(decks_brut)
        except json.JSONDecodeError:
            pass
    curseur.execute("SELECT id, name FROM decks")
    return {
        str(ligne["id"]): {"name": ligne["name"].replace(SEPARATEUR_CHAMPS, "::")}
        for ligne in curseur.fetchall()
    }


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

        modeles = _lire_modeles(curseur, ligne_col["models"])
        decks_anki = _lire_decks(curseur, ligne_col["decks"])

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


def _deviner_matiere(nom_anki: str) -> str:
    """Devine la matière (au sens Deck.Matiere) d'un paquet importé, à
    partir du premier segment de son nom Anki (avant "::") — par exemple
    "Physique::Thermodynamique" -> matière "physique". Comparaison insensible
    à la casse contre la valeur ("physique") ou le libellé ("Physique") de
    chaque choix ; renvoie "" (aucune matière) si rien ne correspond,
    laissant le paquet dans "Sans matière" comme avant cette détection."""
    premier_segment = nom_anki.split("::", 1)[0].strip().lower()
    for valeur, libelle in Deck.Matiere.choices:
        if premier_segment in (valeur.lower(), libelle.lower()):
            return valeur
    return ""


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
            deck = Deck.objects.create(
                nom=nom_propre, slug=slug, cree_par=utilisateur,
                matiere=_deviner_matiere(nom_anki),
            )
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
        carte, _ = Card.objects.get_or_create(note=note, etudiant=utilisateur)
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
