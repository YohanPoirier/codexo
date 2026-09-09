#!/bin/bash
# backup_db.sh — Sauvegarde la base SQLite de Codexo, avec rotation.
#
# Usage : ./backup_db.sh
# Pensé pour être lancé automatiquement par cron (voir instructions en bas de fichier).

set -euo pipefail

# Chemin vers la base SQLite en production.
DB_PATH="/data/db.sqlite3"

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

# La commande ".backup" de sqlite3 (et non un simple cp) : sûre même si la base
# est en cours d'écriture par Gunicorn au moment de la sauvegarde.
sqlite3 "$DB_PATH" ".backup '$DESTINATION'"

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
# 3. Ajoute une ligne pour lancer la sauvegarde tous les jours à 3h du matin :
#      0 3 * * * /chemin/vers/backup_db.sh >> /chemin/vers/backups_codexo/backup.log 2>&1
# ------------------------------------------------------------------------------
