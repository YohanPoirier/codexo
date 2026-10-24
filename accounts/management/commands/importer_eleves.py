import io
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.importation import (
    ColonnesManquantes, ErreurEncodage, importer_eleves_depuis_lignes, lire_csv_texte,
)


class Command(BaseCommand):
    help = (
        "Importe des comptes élèves depuis un fichier CSV (colonnes attendues, avec "
        "en-tête : id, nom_complet, classe, mot_de_passe). Le mot de passe "
        "provisoire de chaque compte est la valeur telle qu'écrite dans la colonne "
        "mot_de_passe du CSV ; le compte est marqué 'doit changer son mot de passe' "
        "et sera redirigé vers le changement de mot de passe dès sa première "
        "connexion. Peut être relancé sans dupliquer : un élève déjà inscrit voit "
        "seulement son nom et sa classe mis à jour (son mot de passe n'est pas touché) ; "
        "un compte professeur ou administrateur n'est jamais modifié. "
        "Un formulaire web équivalent existe aussi, voir /importer-eleves/ (réservé "
        "aux profs, lien dans le menu déroulant \"Espace prof\")."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Chemin du fichier CSV à importer.")
        parser.add_argument(
            "--delimiter", type=str, default=",",
            help=(
                "Séparateur de colonnes du CSV (par défaut ','; utiliser ';' si le "
                "fichier vient d'un export Excel en français)."
            ),
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        if not csv_path.exists():
            raise CommandError(f"Fichier introuvable : {csv_path}")

        # UTF-8 (avec ou sans BOM d'Excel) puis Windows-1252 : voir lire_csv_texte.
        try:
            texte = lire_csv_texte(csv_path.read_bytes())
            crees, mis_a_jour, erreurs = importer_eleves_depuis_lignes(
                io.StringIO(texte, newline=""), delimiter=options["delimiter"]
            )
        except (ColonnesManquantes, ErreurEncodage) as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {crees} compte(s) créé(s), {mis_a_jour} mis à jour."
        ))
        for erreur in erreurs:
            self.stdout.write(self.style.WARNING(erreur))
