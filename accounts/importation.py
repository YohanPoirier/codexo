import csv

from .models import Classe, User

COLONNES_ATTENDUES = {"id", "nom_complet", "classe", "mot_de_passe"}


class ColonnesManquantes(Exception):
    """Levée quand l'en-tête du CSV n'a pas les colonnes attendues."""

    def __init__(self, colonnes_manquantes, colonnes_trouvees):
        self.colonnes_manquantes = colonnes_manquantes
        self.colonnes_trouvees = colonnes_trouvees
        super().__init__(
            f"Colonnes manquantes dans le CSV : {', '.join(sorted(colonnes_manquantes))} "
            f"(colonnes trouvées : {', '.join(colonnes_trouvees) or 'aucune'})"
        )


class ErreurEncodage(Exception):
    """Levée quand le fichier n'est lisible ni en UTF-8 ni en Windows-1252."""


def lire_csv_texte(octets):
    """Décode le contenu d'un fichier CSV.

    UTF-8 d'abord (avec ou sans BOM, comme l'export « CSV UTF-8 » d'Excel), puis Windows-1252 :
    c'est l'encodage du simple « CSV (séparateur : point-virgule) » d'Excel en français, dès
    qu'un nom contient un accent. Sans cette seconde chance, ces fichiers plantaient."""
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            return octets.decode(encodage)
        except UnicodeDecodeError:
            continue
    raise ErreurEncodage(
        "Impossible de lire le fichier : enregistre-le au format « CSV UTF-8 » depuis ton tableur."
    )


def importer_eleves_depuis_lignes(lignes_texte, delimiter=","):
    """Importe des comptes élèves à partir d'un itérable de lignes de texte déjà
    décodées (un fichier ouvert en mode texte, ou un io.StringIO).

    Logique partagée entre la commande de gestion "importer_eleves" (ligne de
    commande, voir accounts/management/commands/importer_eleves.py) et le
    formulaire web (voir accounts/views.py : importer_eleves_view), pour ne pas
    dupliquer deux fois les mêmes règles d'import.

    Règles :
    - identifiant inconnu : le compte est créé (rôle élève, classe du fichier), avec le mot de
      passe provisoire de la colonne « mot_de_passe » et l'obligation de le changer ;
    - élève déjà inscrit : seuls son nom et sa classe sont mis à jour (changement de classe
      en début d'année, correction d'un nom). Son mot de passe n'est PAS touché, et son
      historique (résultats, cartes) reste attaché au compte ;
    - compte professeur, administrateur ou staff : jamais modifié (ligne ignorée avec un
      message). Sans cette règle, un fichier contenant son identifiant en remplaçait le mot
      de passe et le rôle.

    Retourne (crees, mis_a_jour, erreurs).
    Lève ColonnesManquantes si l'en-tête du CSV n'a pas les colonnes attendues.
    """
    reader = csv.DictReader(lignes_texte, delimiter=delimiter)
    colonnes_manquantes = COLONNES_ATTENDUES - set(reader.fieldnames or [])
    if colonnes_manquantes:
        raise ColonnesManquantes(colonnes_manquantes, reader.fieldnames or [])

    crees = 0
    mis_a_jour = 0
    erreurs = []

    for numero_ligne, row in enumerate(reader, start=2):  # ligne 1 = en-tête
        identifiant = (row.get("id") or "").strip()
        nom_complet = (row.get("nom_complet") or "").strip()
        classe_nom = (row.get("classe") or "").strip()
        # La colonne ne sert qu'à fournir le mot de passe provisoire d'un compte NOUVEAU
        # (jamais stockée telle quelle, voir set_password() plus bas). Rien n'empêche d'y
        # mettre une date de naissance si c'est la convention choisie côté établissement.
        mot_de_passe_provisoire = (row.get("mot_de_passe") or "").strip()

        if not identifiant or not nom_complet or not classe_nom:
            erreurs.append(f"Ligne {numero_ligne} : champ(s) manquant(s), ignorée.")
            continue

        existant = User.objects.filter(identifiant=identifiant).first()

        if existant is not None and (
            existant.is_staff or existant.is_superuser or existant.role == User.PROF
        ):
            erreurs.append(
                f"Ligne {numero_ligne} : « {identifiant} » est un compte professeur ou "
                f"administrateur, il n'est jamais modifié par l'import, ligne ignorée."
            )
            continue

        if existant is None and not mot_de_passe_provisoire:
            erreurs.append(
                f"Ligne {numero_ligne} : mot de passe provisoire manquant pour le nouveau "
                f"compte « {identifiant} », ignorée."
            )
            continue

        try:
            classe = Classe.objects.get(name=classe_nom)
        except Classe.DoesNotExist:
            erreurs.append(
                f"Ligne {numero_ligne} : classe \"{classe_nom}\" introuvable "
                f"(créer la classe d'abord via l'admin), ligne ignorée."
            )
            continue

        if existant is None:
            utilisateur = User(
                identifiant=identifiant,
                display_name=nom_complet,
                role=User.ELEVE,
                classe=classe,
                doit_changer_mot_de_passe=True,
            )
            utilisateur.set_password(mot_de_passe_provisoire)
            utilisateur.save()
            crees += 1
        else:
            # Élève déjà inscrit : nom et classe seulement (mot de passe intact).
            existant.display_name = nom_complet
            existant.classe = classe
            existant.save(update_fields=["display_name", "classe"])
            mis_a_jour += 1

    return crees, mis_a_jour, erreurs
