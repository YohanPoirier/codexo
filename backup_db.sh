#!/bin/bash
# backup_db.sh — Sauvegarde la base SQLite de Codexo, avec rotation.
#
# Usage : ./backup_db.sh (à lancer depuis la racine du projet, ~/codexo)
# Pensé pour être lancé automatiquement par cron (voir instructions en bas de fichier).

set -euo pipefail

# Chemin vers la base SQLite en production, relatif à la racine du projet
# (~/codexo). Correspond à DATA_DIR dans settings.py (par défaut <projet>/data,
# sauf si DJANGO_DATA_DIR est défini différemment dans ton .env).
DB_PATH="data/db.sqlite3"

# Dossier où stocker les sauvegardes (en dehors du dossier du projet, pour ne
# jamais risquer de l'effacer par erreur avec un `git clean` ou similaire).
BACKUP_DIR="../backups_codexo"

# Nombre de jours de sauvegardes à conserver (les plus anciennes sont supprimées
# automatiquement).
JOURS_A_CONSERVER=30
# ------------------------------------------------------------------------------

mkdir -p "$BACKUP_DIR"

HORODATAGE=$(date +%Y-%m-%d_%H-%M-%S)
DESTINATION="$BACKUP_DIR/db_${HORODATAGE}.sqlite3"

# Sauvegarde via le module Python "sqlite3" (méthode .backup(), équivalente à la
# commande ".backup" de l'outil en ligne de commande sqlite3) : sûre même si la
# base est en cours d'écriture par Gunicorn au moment de la sauvegarde.
# Volontairement fait en Python plutôt qu'avec la commande "sqlite3" : ce module
# est déjà intégré à Python (utilisé par Django lui-même), donc aucune
# installation supplémentaire ni droits root ne sont nécessaires — contrairement
# à l'outil en ligne de commande "sqlite3", qui doit être installé séparément via
# "sudo apt install sqlite3" (pas toujours possible selon les droits sur le VPS).
python3 -c "
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
with destination:
    source.backup(destination)
destination.close()
source.close()
" "$DB_PATH" "$DESTINATION"

# Compression pour économiser de la place (une base Codexo reste petite, mais
# autant prendre l'habitude).
gzip "$DESTINATION"

echo "Sauvegarde créée : ${DESTINATION}.gz"

# Rotation : supprime les sauvegardes plus vieilles que JOURS_A_CONSERVER jours.
find "$BACKUP_DIR" -name "db_*.sqlite3.gz" -mtime "+${JOURS_A_CONSERVER}" -delete

echo "Sauvegardes actuelles :"
ls -lh "$BACKUP_DIR"

# --- Mise en place de l'automatisation (à faire une seule fois) --------------
# 1. Rends le script exécutable :
#      chmod +x backup_db.sh
# 2. Ouvre l'éditeur de tâches cron :
#      crontab -e
# 3. Ajoute une ligne pour lancer la sauvegarde tous les jours à 3h du matin
#    (attention : cron ne connaît pas ton dossier courant, donc on utilise "cd"
#    pour se placer dans ~/codexo avant de lancer le script, vu que DB_PATH et
#    BACKUP_DIR sont des chemins relatifs) :
#      0 3 * * * cd /home/codexo/codexo && ./backup_db.sh >> ../backups_codexo/backup.log 2>&1
# ------------------------------------------------------------------------------
