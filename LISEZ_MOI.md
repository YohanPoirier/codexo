# Refonte de l'authentification — fichiers à appliquer

Ce zip contient tous les fichiers modifiés/ajoutés pour la refonte discutée
(suppression de `/signup/`, identifiant de connexion, import CSV élèves, mot de
passe provisoire, changement forcé, mot de passe oublié). Le détail de chaque
décision est aussi dans `contexte-technique.md` du projet Codexo (section
"Refonte de l'authentification").

**Sur mes limites d'accès** : j'ai maintenant pu vérifier directement dans ton
dépôt (source GitHub synchronisée dans le projet Codexo) le contenu exact de
`accounts/migrations/` — voir la section migration ci-dessous, elle est donc
fournie prête à l'emploi, sans manipulation de ta part. Le reste du zip a été
vérifié fichier par fichier (diff minimal à chaque fois), mais fais quand même
un tour de sécurité (voir "À vérifier toi-même" en bas) avant de déployer.

## Fichiers à remplacer tels quels (contenu complet, diff vérifié minimal)

- `accounts/models.py`
- `accounts/admin.py`
- `accounts/forms.py`
- `accounts/views.py`
- `codexo/urls.py`
- `codexo/settings.py` (un seul ajout : la ligne du nouveau middleware dans `MIDDLEWARE`)
- `exercises/views.py` (2 petits changements : tri par `identifiant` au lieu
  d'`email`, et le label affiché dans le mode "par exercice" de `/stats/`)
- `exercises/management/commands/seed_exercises.py` (le compte admin de
  bootstrap et le compte élève de test créés depuis les variables
  d'environnement utilisent maintenant `identifiant` comme clé, sinon ils
  deviendraient injoignables après la migration)
- `templates/base.html` (nav : `is_superuser` → `is_staff` pour les liens
  Administration/Statistiques/Visibilité — **sans ce changement, les profs ne
  verraient plus ces liens** une fois qu'ils ne sont plus superuser ; lien
  d'inscription retiré ; lien vers les demandes de mot de passe ajouté)
- `templates/accounts/login.html` (lien d'inscription remplacé par "mot de
  passe oublié")
- `templates/exercises/stats.html` (le menu déroulant "choisir un étudiant"
  affichait `s.email` en secours, remplacé par `s.identifiant`)

## Fichiers nouveaux à créer

- `accounts/middleware.py`
- `accounts/management/__init__.py` (vide)
- `accounts/management/commands/__init__.py` (vide)
- `accounts/management/commands/importer_eleves.py`
- `accounts/migrations/0003_ajout_identifiant_et_doit_changer_mdp.py` — prête
  à l'emploi telle quelle, voir section migration ci-dessous
- `templates/accounts/changer_mot_de_passe.html`
- `templates/accounts/mot_de_passe_oublie.html`
- `templates/accounts/mot_de_passe_oublie_envoye.html`
- `templates/accounts/demandes_reinitialisation.html`

## Fichier à supprimer

- `templates/accounts/signup.html` — la vue `signup` et la route `/signup/`
  n'existent plus, ce template devient orphelin.

## Migration

J'ai vérifié directement le contenu de `accounts/migrations/` dans ton dépôt
GitHub : ta dernière migration `accounts` est bien
`0002_classe_user_role_user_classe.py` (confirmé aussi par
`exercises/migrations/0009_alter_exercise_enabled_for_classes_and_more.py`,
ta migration la plus récente tous modules confondus, datée du 04/09/2026, qui
en dépend). Le fichier fourni,
`accounts/migrations/0003_ajout_identifiant_et_doit_changer_mdp.py`, a donc
directement la bonne dépendance — aucune correction ni renommage de ta part :

1. Applique d'abord tous les fichiers `.py` listés plus haut (modèles compris).
2. Place `accounts/migrations/0003_ajout_identifiant_et_doit_changer_mdp.py`
   dans ton dossier `accounts/migrations/` (aucune autre étape).
3. `python manage.py migrate`.

La migration de données (dans ce même fichier) reprend ton ancien email comme
identifiant pour tous les comptes déjà existants (dont le tien) — tu pourras
donc continuer à te connecter avec ce qui était ton email, en le tapant dans
le champ "Identifiant".

## Après la migration

1. **Créer le groupe "Professeurs"** (Admin Django → Authentification et
   autorisation → Groupes → Ajouter groupe) avec les permissions add/change/
   view (delete si tu veux) sur `Theme`, `Exercise`, `TestCase`, `Hint`,
   `Classe` — rien sur `User`/`Group`/`Permission`.
2. **Assigner ce groupe** à ton propre compte (et ceux des autres profs) via
   l'admin (champ "Groups" de la fiche utilisateur) — sans quoi les profs
   n'auront plus aucune permission sur les exercices une fois qu'ils ne sont
   plus superuser (garde au moins UN compte superuser réel — le tien via
   `DJANGO_SUPERUSER_EMAIL`/`_PASSWORD`, déjà en place — pour pouvoir créer ce
   groupe et gérer les comptes).
3. **Tester une connexion** avec ton compte existant (identifiant = ton
   ancien email) pour vérifier que la migration de données a bien fonctionné.
4. **Importer un CSV élèves** : `python manage.py importer_eleves chemin/vers/fichier.csv`
   (colonnes attendues avec en-tête : `id`, `nom_complet`, `classe`,
   `date_naissance` au format `JJ/MM/AAAA`, ex: `15/03/2007`). Les classes
   doivent déjà exister dans l'admin avant l'import (recherche par nom exact).
   Utilise `--delimiter ";"` si le CSV vient d'un export Excel français.

## Déploiement VPS (rappel, cf. contexte-technique.md)

Le `Procfile` ne sert à rien sur un VPS — ton service de démarrage (systemd ou
autre) doit lancer `migrate` + `collectstatic` + `gunicorn`, **sans**
`seed_exercises` automatique à chaque redémarrage. Lance `seed_exercises` et
`importer_eleves` toi-même (SSH), ponctuellement.

## À vérifier toi-même

- Cherche dans tout ton dépôt les chaînes `signup`, `EmailLoginView` et
  `is_superuser` (recherche texte simple, ex. VS Code "rechercher dans les
  fichiers") pour repérer une éventuelle référence que j'aurais pu manquer
  (un autre template, un test, etc.).
- Vérifie que `templates/accounts/demandes_reinitialisation.html` et les
  autres nouveaux templates s'intègrent bien visuellement (je me suis basé
  sur le style de `stats.html`/`login.html`, mais je n'ai vu qu'un extrait de
  `static/css/style.css`, pas le fichier complet).
