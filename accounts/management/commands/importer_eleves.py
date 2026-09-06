from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.importation import ColonnesManquantes, importer_eleves_depuis_lignes


class Command(BaseCommand):
    help = (
        "Importe des comptes élèves depuis un fichier CSV (colonnes attendues, avec "
        "en-tête : id, nom_complet, classe, date_naissance). Le mot de passe "
        "provisoire de chaque compte est sa date de naissance telle qu'écrite dans "
        "le CSV (ex: 15/03/2007) ; le compte est marqué 'doit changer son mot de "
        "passe' et sera redirigé vers le changement de mot de passe dès sa première "
        "connexion. Peut être relancé sans dupliquer (get_or_create par identifiant). "
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

        # encoding="utf-8-sig" : tolère le BOM ajouté par Excel en tête de fichier
        # lors d'un export CSV, sans quoi la première colonne ("id") ne serait pas
        # reconnue (elle apparaîtrait comme "﻿id").
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            try:
                crees, mis_a_jour, erreurs = importer_eleves_depuis_lignes(
                    f, delimiter=options["delimiter"]
                )
            except ColonnesManquantes as exc:
                raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {crees} compte(s) créé(s), {mis_a_jour} mis à jour."
        ))
        for erreur in erreurs:
            self.stdout.write(self.style.WARNING(erreur))
