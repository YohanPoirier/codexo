# Migration d'état uniquement (aucune colonne modifiée en base) : renomme en français les
# libellés utilisés par l'admin Django (verbose_name des modèles et des champs) — voir la
# discussion du 06/09/2026 sur l'admin ("éviter l'anglais dans cette page").

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_demandereinitialisation"),
        ("exercises", "0012_demandeaide_reponse_vue"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="exercise",
            options={
                "ordering": ["theme__order", "order"],
                "verbose_name": "exercice",
                "verbose_name_plural": "exercices",
            },
        ),
        migrations.AlterModelOptions(
            name="hint",
            options={
                "ordering": ["order", "id"],
                "verbose_name": "indice",
                "verbose_name_plural": "indices",
            },
        ),
        migrations.AlterModelOptions(
            name="testcase",
            options={
                "ordering": ["order", "id"],
                "verbose_name": "cas de test",
                "verbose_name_plural": "cas de test",
            },
        ),
        migrations.AlterModelOptions(
            name="theme",
            options={
                "ordering": ["order", "name"],
                "verbose_name": "thème",
                "verbose_name_plural": "thèmes",
            },
        ),
        migrations.AlterField(
            model_name="exercise",
            name="enabled_for_classes",
            field=models.ManyToManyField(
                blank=True,
                related_name="enabled_exercises",
                to="accounts.classe",
                verbose_name="classes",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="extra_test_code",
            field=models.TextField(
                blank=True,
                help_text="[Python] Optionnel : code de test supplémentaire, exécuté après les tests habituels. Peut appeler __FN__(...) (remplacé automatiquement par le nom de la fonction de l'étudiant) et doit ajouter ses propres résultats à __RESULTS__ sous la forme (booléen_reussite, message, sortie_console) — voir les exercices existants pour des exemples (ex: vérifier qu'une structure de données n'est pas partagée par erreur, ou qu'une construction du langage précise n'est pas utilisée).",
                verbose_name="code de test supplémentaire",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="function_name",
            field=models.CharField(
                blank=True,
                help_text="[Python] Nom de la fonction que l'étudiant doit écrire (ex: 'triple').",
                max_length=100,
                verbose_name="nom de la fonction",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="kind",
            field=models.CharField(
                choices=[("python", "Python (fonction)"), ("sql", "SQL (requête)")],
                default="python",
                max_length=10,
                verbose_name="type",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="order",
            field=models.PositiveIntegerField(default=0, verbose_name="ordre"),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="require_recursive",
            field=models.BooleanField(
                default=False,
                help_text="[Python] Si coché, on vérifie en plus (analyse statique du code, sans l'exécuter) que la fonction de l'étudiant s'appelle bien elle-même — sinon l'exercice est refusé même si le résultat renvoyé est correct.",
                verbose_name="récursivité exigée",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="solution_code",
            field=models.TextField(
                blank=True,
                help_text="[Python] Code de correction : une implémentation complète et correcte de la fonction. Le résultat attendu de chaque test (ci-dessous) est calculé automatiquement en exécutant ce code.",
                verbose_name="code de correction",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="sql_setup",
            field=models.TextField(
                blank=True,
                help_text="[SQL] Optionnel : instructions SQL (CREATE TABLE + INSERT) propres à CET exercice, en cas de données différentes de celles du thème. Laisser vide pour réutiliser automatiquement le 'sql_setup' défini sur le thème.",
                verbose_name="script SQL",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="sql_solution",
            field=models.TextField(
                blank=True,
                help_text="[SQL] La requête SQL correcte. Le résultat attendu est calculé automatiquement en l'exécutant sur les données de sql_setup, puis comparé à la requête de l'étudiant.",
                verbose_name="solution SQL",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="starter_code",
            field=models.TextField(
                blank=True,
                help_text="Code de départ affiché dans l'éditeur (l'en-tête de la fonction, ou un commentaire SQL).",
                verbose_name="code de départ",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="statement",
            field=models.TextField(
                help_text="Énoncé de l'exercice (Markdown simple accepté).",
                verbose_name="énoncé",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="theme",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="exercises",
                to="exercises.theme",
                verbose_name="thème",
            ),
        ),
        migrations.AlterField(
            model_name="exercise",
            name="title",
            field=models.CharField(max_length=150, verbose_name="titre"),
        ),
        migrations.AlterField(
            model_name="hint",
            name="order",
            field=models.PositiveIntegerField(default=0, verbose_name="ordre"),
        ),
        migrations.AlterField(
            model_name="hint",
            name="text",
            field=models.TextField(
                help_text="Texte de l'indice (Markdown simple accepté, comme pour l'énoncé).",
                verbose_name="texte",
            ),
        ),
        migrations.AlterField(
            model_name="testcase",
            name="args",
            field=models.TextField(
                default="[]",
                help_text="Arguments à passer à la fonction, en syntaxe Python (pas JSON). Ex : [2, 3]  ou  ['bonjour']  ou  [True, None]  ou  [{'a': 1, 'b': 2}]  ou  [[1, 2, 3]].",
                verbose_name="arguments",
            ),
        ),
        migrations.AlterField(
            model_name="testcase",
            name="order",
            field=models.PositiveIntegerField(default=0, verbose_name="ordre"),
        ),
        migrations.AlterField(
            model_name="theme",
            name="enabled_for_classes",
            field=models.ManyToManyField(
                blank=True,
                related_name="enabled_themes",
                to="accounts.classe",
                verbose_name="classes",
            ),
        ),
        migrations.AlterField(
            model_name="theme",
            name="name",
            field=models.CharField(max_length=100, verbose_name="nom"),
        ),
        migrations.AlterField(
            model_name="theme",
            name="order",
            field=models.PositiveIntegerField(default=0, verbose_name="ordre"),
        ),
        migrations.AlterField(
            model_name="theme",
            name="sql_setup",
            field=models.TextField(
                blank=True,
                help_text="[SQL] Base de données partagée par défaut pour tous les exercices SQL de ce thème (instructions CREATE TABLE + INSERT). Un exercice peut définir son propre 'sql_setup' pour utiliser des données différentes ponctuellement, sinon celui du thème est utilisé. Astuce : ajouter des commentaires SQL ('-- texte') après une table ou une colonne pour qu'ils apparaissent dans le résumé de schéma affiché aux étudiants.",
                verbose_name="script SQL",
            ),
        ),
    ]
