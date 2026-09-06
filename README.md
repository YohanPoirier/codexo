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

## Déploiement (VPS)

Le site tourne en production sur un VPS Ubuntu : Nginx en reverse proxy devant
Gunicorn, lancé automatiquement au démarrage via un service systemd. Le disque
y est persistant (contrairement à un hébergeur gratuit type Render/Railway) :
`seed_exercises` ne doit donc **pas** être relancé automatiquement à chaque
redémarrage du service — il se lance manuellement, ponctuellement (voir
`deploiement_checklist.md`).

Pour la liste complète des variables d'environnement et la checklist à suivre
à chaque mise à jour de code (`git pull`, migrations, collectstatic, redémarrage
du service), voir **`deploiement_checklist.md`** — c'est la référence à jour.
Cette section-ci ne couvre que la mise en place initiale d'un nouveau serveur.

### Mise en place initiale d'un nouveau VPS (Ubuntu)

1. **Connexion et mise à jour du système**
   ```bash
   ssh ubuntu@<IP_DU_SERVEUR>
   sudo apt update && sudo apt upgrade -y
   sudo reboot
   ```
   (remplace `<IP_DU_SERVEUR>` par l'IP ou le nom de domaine réel du serveur)

2. **Dépendances système**
   ```bash
   sudo apt install git python3-venv python3-pip -y
   ```

3. **Cloner le projet**
   ```bash
   sudo mkdir -p /var/www
   sudo chown ubuntu:ubuntu /var/www
   cd /var/www
   git clone https://github.com/YohanPoirier/codexo.git
   cd codexo
   ```

4. **Environnement virtuel + dépendances Python**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python manage.py check
   ```

5. **Base de données et configuration**
   ```bash
   python manage.py migrate
   ```
   Configurer le `.env` de production (voir `deploiement_checklist.md` pour la
   liste complète des variables), en particulier `DJANGO_ALLOWED_HOSTS` avec
   l'IP ou le nom de domaine du serveur.

   À ce stade, un test rapide doit fonctionner :
   `gunicorn --bind 0.0.0.0:8000 codexo.wsgi:application` (venv activé),
   accessible sur `http://<IP_DU_SERVEUR>:8000/`.

6. **Fichiers statiques + Nginx en reverse proxy**
   ```bash
   sudo apt install nginx
   sudo nano /etc/nginx/sites-available/codexo
   ```
   Contenu :
   ```nginx
   server {
       listen 80;
       server_name <IP_OU_DOMAINE>;

       location /static/ {
           alias /var/www/codexo/staticfiles/;
       }

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   ```bash
   sudo ln -s /etc/nginx/sites-available/codexo /etc/nginx/sites-enabled/codexo
   sudo rm /etc/nginx/sites-enabled/default
   sudo systemctl reload nginx
   python manage.py collectstatic
   ```
   Le site doit maintenant être accessible sur `http://<IP_OU_DOMAINE>/` (port 80).

7. **Démarrage automatique de Gunicorn (service systemd)**
   ```bash
   sudo nano /etc/systemd/system/codexo.service
   ```
   Contenu :
   ```ini
   [Unit]
   Description=Gunicorn pour Codexo
   After=network.target

   [Service]
   User=ubuntu
   Group=www-data
   WorkingDirectory=/var/www/codexo
   Environment="PATH=/var/www/codexo/venv/bin"
   ExecStart=/var/www/codexo/venv/bin/gunicorn \
       --workers 3 \
       --bind 127.0.0.1:8000 \
       codexo.wsgi:application
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now codexo
   ```
   Ce service ne lance que `gunicorn` — pas `migrate`, `collectstatic` ni
   `seed_exercises` au démarrage (voir `deploiement_checklist.md` pour ce qui
   doit être fait manuellement, et à quel moment).

8. **Déploiement du code via GitHub (clé SSH dédiée)**

   Pour pouvoir faire `git pull` depuis le serveur sans mot de passe :
   ```bash
   cd /var/www/codexo
   ssh-keygen -t ed25519 -C "codexo-vps" -f ~/.ssh/codexo_github
   cat ~/.ssh/codexo_github.pub
   ```
   Ajouter cette clé publique dans GitHub : Settings → Deploy keys → Add deploy
   key (pas besoin de "Allow write access").
   ```bash
   git remote set-url origin git@github.com:YohanPoirier/codexo.git
   nano ~/.ssh/config
   ```
   Contenu :
   ```
   Host github.com
       HostName github.com
       User git
       IdentityFile ~/.ssh/codexo_github
       IdentitiesOnly yes
   ```
   ```bash
   chmod 600 ~/.ssh/config
   git fetch origin
   ```

   Une fois cette étape faite, les mises à jour suivantes se font simplement
   avec `git pull` + la checklist de `deploiement_checklist.md`.
