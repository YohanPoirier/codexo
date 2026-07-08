# Codexo — Plateforme d'exercices Python

Site web permettant aux étudiants de s'entraîner à Python via des exercices
classés par thème, avec correction automatique exécutée directement dans le
navigateur (Pyodide) et sauvegarde des résultats en base de données.

## Stack technique

- **Backend** : Django (comptes, base de données, admin, pages).
- **Base de données** : SQLite (fichier `db.sqlite3`, aucune installation requise).
- **Authentification** : compte email + mot de passe (modèle utilisateur personnalisé).
- **Correction des exercices** : Pyodide (Python compilé en WebAssembly), exécuté
  **côté navigateur** — le serveur n'exécute jamais le code des étudiants, ce qui
  évite tout risque de sécurité lié à l'exécution de code arbitraire côté serveur.

## Lancer le projet en local

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Appliquer les migrations (déjà fait si tu reçois le projet tel quel,
#    mais à refaire si tu supprimes db.sqlite3)
python manage.py migrate

# 3. Charger les thèmes et exercices de démonstration
python manage.py seed_exercises

# 4. Créer un compte administrateur (pour voir les résultats des étudiants)
python manage.py createsuperuser

# 5. Lancer le serveur
python manage.py runserver
```

Le site est alors accessible sur http://127.0.0.1:8000/
Le panel admin (pour voir les résultats de tous les étudiants) est sur
http://127.0.0.1:8000/admin/

## Ajouter des thèmes / exercices

Deux options :
1. **Via l'admin Django** (`/admin/`) : créer un `Theme`, puis des `Exercise` liés.
2. **En modifiant `exercises/management/commands/seed_exercises.py`** puis en
   relançant `python manage.py seed_exercises` (met à jour sans dupliquer).

Chaque exercice a un champ `test_code` : du code Python exécuté après le code
de l'étudiant, qui doit définir une liste `__RESULTS__` de tuples
`(booléen_reussite, message)`. Voir les exemples dans `seed_exercises.py`.

**Limite à connaître** : comme la correction s'exécute côté navigateur, un
étudiant curieux peut techniquement inspecter le code de test via les outils
de développement du navigateur (onglet réseau). Ce n'est pas un défaut de
sécurité (aucune donnée sensible n'est exposée), mais les tests ne doivent pas
être vus comme totalement "secrets".

## Déploiement (Render, Railway, PythonAnywhere...)

Le projet est prêt pour un déploiement simple :
- `requirements.txt` : dépendances (Django, gunicorn, whitenoise pour les fichiers statiques).
- `Procfile` : commande de démarrage utilisée par la plupart des hébergeurs.
- Variables d'environnement à définir en production :
  - `DJANGO_SECRET_KEY` : une clé secrète longue et aléatoire.
  - `DJANGO_DEBUG` : `False`
  - `DJANGO_ALLOWED_HOSTS` : ton nom de domaine (ex: `codexo.onrender.com`)

Exemple pour **Render** :
1. Créer un nouveau "Web Service" à partir de ton dépôt Git.
2. Build command : `pip install -r requirements.txt`
3. Start command : `bash -c "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn codexo.wsgi"`
4. Ajouter les variables d'environnement ci-dessus.
5. Une fois déployé, se connecter en SSH (ou via le shell Render) pour lancer
   `python manage.py seed_exercises` et `python manage.py createsuperuser`.

**Note sur SQLite en production** : SQLite fonctionne très bien pour démarrer,
mais sur certains hébergeurs (Render en particulier), le système de fichiers
n'est pas persistant entre les déploiements — la base serait donc réinitialisée
à chaque mise à jour du code. Si tu veux que les résultats des étudiants
survivent aux déploiements, il faudra passer à PostgreSQL (Render propose une
base gratuite) — dis-le moi si tu veux que je configure ça.
