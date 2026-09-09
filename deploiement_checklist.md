# Déploiement Codexo — checklist rapide

## Configuration de l'environnement (`.env` sur le VPS)

Variables à définir (jamais commitées dans git, voir `.env.example` pour le modèle) :

* `DJANGO\_SECRET\_KEY` : une clé aléatoire, différente de celle codée en dur dans
`settings.py` (visible sur GitHub, donc jamais à utiliser telle quelle en
prod). À générer avec :
`python -c "from django.core.management.utils import get\_random\_secret\_key; print(get\_random\_secret\_key())"`
* `DJANGO\_DEBUG` : `False` en production.
* `DJANGO\_ALLOWED\_HOSTS` : le(s) nom(s) de domaine du site, séparés par une
virgule si plusieurs, sans `https://` ni `/` final (ex: `codexo.mondomaine.fr`).
* `DJANGO\_SUPERUSER\_EMAIL` / `DJANGO\_SUPERUSER\_PASSWORD` : ton compte admin.
* `DJANGO\_SUPERUSER2\_EMAIL` / `DJANGO\_SUPERUSER2\_PASSWORD` : le compte admin de
ton collègue.

Optionnelles :

* `DJANGO\_TEST\_STUDENT\_EMAIL` / `DJANGO\_TEST\_STUDENT\_PASSWORD` : un compte
élève de test, recréé à chaque `seed\_exercises` si défini.
* `DJANGO\_DATA\_DIR` : dossier où vit la base SQLite (par défaut `data/` dans
le projet) — à ne changer que si tu veux la stocker ailleurs.
* `DATABASE\_URL` : uniquement si vous passez un jour à PostgreSQL plutôt que
SQLite (sinon SQLite est utilisé automatiquement par défaut).

## À chaque mise à jour de code

1. `git pull`
2. `pip install -r requirements.txt` (si les dépendances ont changé)
3. `python manage.py migrate`
4. `python manage.py collectstatic --noinput`
5. Redémarrer le service (`systemctl restart <nom-du-service>`)

## Ponctuel (PAS à chaque déploiement)

* `python manage.py seed\_exercises` : au tout premier déploiement, puis
seulement après une grosse mise à jour d'`exercises\_data.json`. Crée/met à
jour aussi automatiquement : les comptes superutilisateurs (depuis le
`.env`), les 3 classes fixes (PCSI/MPSI/PSI), et le groupe "Professeurs"
avec ses permissions — plus besoin de les créer à la main dans l'admin.

## Avant d'inscrire un prof

* Rien à préparer : le groupe "Professeurs" existe déjà (créé par
`seed\_exercises`) → juste l'assigner au compte créé dans l'admin.

## Avant d'importer des élèves

* Rien à préparer : les 3 classes existent déjà (créées par `seed\_exercises`).
* `python manage.py importer\_eleves fichier.csv` (ou le formulaire web
`/importer-eleves/`).

