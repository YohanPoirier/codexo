import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Classe, User


class Command(BaseCommand):
    help = (
        "Importe des comptes élèves depuis un fichier CSV (colonnes attendues, avec "
        "en-tête : id, nom_complet, classe, date_naissance). Le mot de passe "
        "provisoire de chaque compte est sa date de naissance telle qu'écrite dans "
        "le CSV (ex: 15/03/2007) ; le compte est marqué 'doit changer son mot de "
        "passe' et sera redirigé vers le changement de mot de passe dès sa première "
        "connexion. Peut être relancé sans dupliquer (get_or_create par identifiant)."
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

        colonnes_attendues = {"id", "nom_complet", "classe", "date_naissance"}

        crees = 0
        mis_a_jour = 0
        erreurs = []

        # encoding="utf-8-sig" : tolère le BOM ajouté par Excel en tête de fichier
        # lors d'un export CSV, sans quoi la première colonne ("id") ne serait pas
        # reconnue (elle apparaîtrait comme "﻿id").
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=options["delimiter"])
            colonnes_manquantes = colonnes_attendues - set(reader.fieldnames or [])
            if colonnes_manquantes:
                raise CommandError(
                    f"Colonnes manquantes dans le CSV : {', '.join(sorted(colonnes_manquantes))} "
                    f"(colonnes trouvées : {', '.join(reader.fieldnames or [])})"
                )

            for numero_ligne, row in enumerate(reader, start=2):  # ligne 1 = en-tête
                identifiant = (row.get("id") or "").strip()
                nom_complet = (row.get("nom_complet") or "").strip()
                classe_nom = (row.get("classe") or "").strip()
                date_naissance = (row.get("date_naissance") or "").strip()

                if not identifiant or not nom_complet or not classe_nom or not date_naissance:
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
                # Toujours réappliquer ces champs même si le compte existait déjà
                # (relance de l'import après correction du CSV, changement de classe...).
                utilisateur.display_name = nom_complet
                utilisateur.role = User.ELEVE
                utilisateur.classe = classe
                utilisateur.doit_changer_mot_de_passe = True
                utilisateur.set_password(date_naissance)
                utilisateur.save()

                if cree:
                    crees += 1
                else:
                    mis_a_jour += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {crees} compte(s) créé(s), {mis_a_jour} mis à jour."
        ))
        for erreur in erreurs:
            self.stdout.write(self.style.WARNING(erreur))
