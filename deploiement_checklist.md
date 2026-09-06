# Déploiement Codexo — checklist rapide

## Configuration de l'environnement (`.env` sur le VPS)

Variables à définir (jamais commitées dans git, voir `.env.example` pour le modèle) :

- `DJANGO_SECRET_KEY` : une clé aléatoire, différente de celle codée en dur dans
  `settings.py` (visible sur GitHub, donc jamais à utiliser telle quelle en
  prod). À générer avec :
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `DJANGO_DEBUG` : `False` en production.
- `DJANGO_ALLOWED_HOSTS` : le(s) nom(s) de domaine du site, séparés par une
  virgule si plusieurs, sans `https://` ni `/` final (ex: `codexo.mondomaine.fr`).
- `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` : ton compte admin.
- `DJANGO_SUPERUSER2_EMAIL` / `DJANGO_SUPERUSER2_PASSWORD` : le compte admin de
  ton collègue.

Optionnelles :

- `DJANGO_TEST_STUDENT_EMAIL` / `DJANGO_TEST_STUDENT_PASSWORD` : un compte
  élève de test, recréé à chaque `seed_exercises` si défini.
- `DJANGO_DATA_DIR` : dossier où vit la base SQLite (par défaut `data/` dans
  le projet) — à ne changer que si tu veux la stocker ailleurs.
- `DATABASE_URL` : uniquement si vous passez un jour à PostgreSQL plutôt que
  SQLite (sinon SQLite est utilisé automatiquement par défaut).

## À chaque mise à jour de code
1. `git pull`
2. `pip install -r requirements.txt` (si les dépendances ont changé)
3. `python manage.py migrate`
4. `python manage.py collectstatic --noinput`
5. Redémarrer le service (`systemctl restart <nom-du-service>`)

## Ponctuel (PAS à chaque déploiement)
- `python manage.py seed_exercises` : au tout premier déploiement, puis
  seulement après une grosse mise à jour d'`exercises_data.json`. Crée/met à
  jour aussi automatiquement : les comptes superutilisateurs (depuis le
  `.env`), les 3 classes fixes (PCSI/MPSI/PSI), et le groupe "Professeurs"
  avec ses permissions — plus besoin de les créer à la main dans l'admin.

## Avant d'inscrire un prof
- Rien à préparer : le groupe "Professeurs" existe déjà (créé par
  `seed_exercises`) → juste l'assigner au compte créé dans l'admin.

## Avant d'importer des élèves
- Rien à préparer : les 3 classes existent déjà (créées par `seed_exercises`).
- `python manage.py importer_eleves fichier.csv` (ou le formulaire web
  `/importer-eleves/`).
