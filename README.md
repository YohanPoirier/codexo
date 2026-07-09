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
- **Configuration locale** : fichier `.env` (via `python-dotenv`), jamais commité.

## Lancer le projet en local

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Créer ta config locale à partir du modèle fourni
cp .env.example .env
# (modifie .env si tu veux personnaliser l'email/mot de passe admin local)

# 3. Appliquer les migrations (déjà fait si tu reçois le projet tel quel,
#    mais à refaire si tu supprimes db.sqlite3)
python manage.py migrate

# 4. Charger les thèmes/exercices de démo + créer automatiquement le compte
#    admin local défini dans .env (DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD)
python manage.py seed_exercises

# 5. Lancer le serveur
python manage.py runserver
```

Le site est alors accessible sur http://127.0.0.1:8000/
Le panel admin est sur http://127.0.0.1:8000/admin/ (aussi accessible via le lien
"Administration" dans le menu du site, visible uniquement pour les superusers).

**Identifiants admin locaux par défaut** (modifiables dans `.env`) :
`admin@codexo.local` / `admin123`

## Ajouter des thèmes / exercices

Deux options :
1. **Via l'admin Django** (`/admin/`) : créer un `Theme`, puis des `Exercise` liés,
   avec leurs `TestCase` (bouton "Add another Test case" en bas de la fiche exercice).
2. **En modifiant `exercises/management/commands/seed_exercises.py`** puis en
   relançant `python manage.py seed_exercises` (met à jour sans dupliquer).

### Format d'un exercice

Chaque exercice repose **toujours** sur une fonction à écrire par l'étudiant :

- `function_name` : le nom exact de la fonction attendue (ex: `triple`).
- `solution_code` : une implémentation complète et correcte de cette fonction.
  Le résultat attendu de chaque test est calculé **automatiquement** en exécutant
  ce code — tu n'as jamais à écrire le résultat toi-même.
- Chaque `TestCase` ne contient qu'un champ `args` : les arguments à tester,
  en **syntaxe Python native** (pas JSON strict) : guillemets simples ou doubles,
  `True`/`False`/`None`, dictionnaires, tuples, listes imbriquées... tout est accepté.
  Exemples valides : `[2, 3]` · `['bonjour']` · `[{'nom': 'Ana', 'score': 12}]` · `[True, None]`

**Limite à connaître** : comme la correction s'exécute côté navigateur, un
étudiant curieux peut techniquement inspecter le `solution_code` via les outils
de développement du navigateur (onglet réseau/Network). Ce n'est pas un défaut
de sécurité (aucune donnée sensible n'est exposée), mais les corrigés ne doivent
pas être vus comme totalement "secrets".

## Versionnement (Git)

Le projet est déjà initialisé avec Git (`git log --oneline` pour voir l'historique).
Flux de travail habituel après une modification :
```bash
git add -A
git commit -m "Description du changement"
git push
```
Le `.env` local n'est **jamais** poussé sur GitHub (exclu via `.gitignore`) —
seul `.env.example` (un modèle sans vrai secret) est versionné.

## Déploiement (Render, ou autre hébergeur Python)

Le projet est prêt pour un déploiement simple :
- `requirements.txt` : dépendances (Django, gunicorn, whitenoise, python-dotenv).
- `Procfile` : commande de démarrage (lue automatiquement par certains hébergeurs
  comme Railway/PythonAnywhere ; sur Render, il faut la recopier manuellement
  dans le champ "Start Command" de l'interface — voir plus bas).

### Variables d'environnement à définir en production

- `DJANGO_SECRET_KEY` : une clé secrète longue et aléatoire (jamais celle du `.env` local).
- `DJANGO_DEBUG` : `False`
- `DJANGO_ALLOWED_HOSTS` : ton nom de domaine (ex: `codexo-xxxx.onrender.com`),
  sans `https://` ni `/` final.
- `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` : identifiants de ton
  compte admin de production. Recréé automatiquement à chaque démarrage du
  service (utile si le plan gratuit ne persiste pas la base de données, ou si
  tu n'as pas accès à un Shell pour lancer `createsuperuser` toi-même).

### Exemple pour Render (plan gratuit)

1. Créer un nouveau "Web Service" à partir de ton dépôt GitHub.
2. Build command : `pip install -r requirements.txt`
3. Start command (à coller manuellement, le champ ne peut pas rester vide sur Render) :
   ```
   bash -c "python manage.py migrate && python manage.py collectstatic --noinput && python manage.py seed_exercises && (python manage.py createsuperuser --noinput || true) && gunicorn codexo.wsgi"
   ```
4. Ajouter les 5 variables d'environnement listées ci-dessus dans la section "Environment".
5. Déployer — le compte admin et les exercices de démo sont créés automatiquement
   au premier démarrage, sans avoir besoin d'un accès Shell.

## Limite connue : persistance des données sur le plan gratuit Render

Sur le plan gratuit de Render, le système de fichiers **n'est pas persistant** :
le service se met en veille après ~15 minutes d'inactivité, et redémarre ensuite
avec un disque vierge. Résultat :
- ✅ **Protégés** (recréés automatiquement à chaque démarrage) : le compte admin
  et les thèmes/exercices définis dans `seed_exercises.py`.
- ❌ **Non protégés** : les comptes étudiants et leurs résultats créés en production,
  qui disparaissent au prochain redémarrage.

**Solution actuellement retenue** : créer les exercices en local, exporter avec
`python manage.py dumpdata exercises --indent 2 > exercises_export.json`, et les
intégrer "en dur" dans `seed_exercises.py` plutôt que de les créer directement en
production. Une vraie persistance des comptes/résultats étudiants nécessiterait
PostgreSQL (Render en propose une base gratuite, mais avec une durée de vie
limitée dans le temps) — non mis en place pour l'instant, à réévaluer si le
site passe en usage réel avec une classe.
