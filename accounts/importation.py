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


def importer_eleves_depuis_lignes(lignes_texte, delimiter=","):
    """Importe des comptes élèves à partir d'un itérable de lignes de texte déjà
    décodées (un fichier ouvert en mode texte, ou un io.StringIO).

    Logique partagée entre la commande de gestion "importer_eleves" (ligne de
    commande, voir accounts/management/commands/importer_eleves.py) et le
    formulaire web (voir accounts/views.py : importer_eleves_view), pour ne pas
    dupliquer deux fois les mêmes règles d'import.

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
        # Anciennement "date_naissance" : la colonne ne sert qu'à fournir le mot de
        # passe provisoire du compte (jamais stockée telle quelle, voir
        # set_password() plus bas), donc renommée pour refléter son vrai usage. Rien
        # n'empêche d'y remettre une date de naissance si c'est la convention
        # choisie côté établissement, mais ce n'est plus imposé par le nom de colonne.
        mot_de_passe_provisoire = (row.get("mot_de_passe") or "").strip()

        if not identifiant or not nom_complet or not classe_nom or not mot_de_passe_provisoire:
            erreurs.append(f"Ligne {numero_ligne} : champ(s) manquant(s), ignorée.")
            continue

        try:
            classe = Classe.objects.get(name=classe_nom)
        except Classe.DoesNotExist:
            erreurs.append(
                f"Ligne {numero_ligne} : classe \"{classe_nom}\" introuvable "
                f"(créer la classe d'abord via l'admin), ligne ignorée."
            )
            continue

        utilisateur, cree = User.objects.get_or_create(
            identifiant=identifiant,
            defaults={
                "display_name": nom_complet,
                "role": User.ELEVE,
                "classe": classe,
                "doit_changer_mot_de_passe": True,
            },
        )
        # Toujours réappliquer ces champs même si le compte existait déjà (relance
        # de l'import après correction du CSV, changement de classe...).
        utilisateur.display_name = nom_complet
        utilisateur.role = User.ELEVE
        utilisateur.classe = classe
        utilisateur.doit_changer_mot_de_passe = True
        utilisateur.set_password(mot_de_passe_provisoire)
        utilisateur.save()

        if cree:
            crees += 1
        else:
            mis_a_jour += 1

    return crees, mis_a_jour, erreurs
