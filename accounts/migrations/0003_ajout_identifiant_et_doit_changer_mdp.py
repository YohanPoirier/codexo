from django.db import migrations, models


def backfill_identifiant(apps, schema_editor):
    """Reprend l'ancien email (déjà unique) comme identifiant de connexion pour tous
    les comptes existants, pour ne pas les rendre inutilisables après la migration
    (notamment ton propre compte prof)."""
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        if not user.identifiant:
            user.identifiant = user.email
            user.save(update_fields=["identifiant"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    # Vérifié directement dans ton dépôt : ta dernière migration accounts est bien
    # 0002_classe_user_role_user_classe (confirmé aussi par
    # exercises/migrations/0009_alter_exercise_enabled_for_classes_and_more.py, qui
    # en dépend et qui est ta migration la plus récente, datée du 04/09/2026).
    dependencies = [
        ("accounts", "0002_classe_user_role_user_classe"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                null=True,
                verbose_name="adresse email",
                help_text="Facultatif. Les comptes élèves importés par CSV n'en ont pas.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="identifiant",
            field=models.CharField(
                max_length=150,
                null=True,
                unique=True,
                verbose_name="identifiant",
                help_text=(
                    "Identifiant de connexion. Pour un élève, correspond typiquement "
                    "au 'id' fourni dans le CSV d'import."
                ),
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="doit_changer_mot_de_passe",
            field=models.BooleanField(
                default=False,
                verbose_name="doit changer son mot de passe",
                help_text=(
                    "Coché automatiquement pour les comptes importés par CSV (mot de "
                    "passe provisoire = date de naissance)."
                ),
            ),
        ),
        migrations.RunPython(backfill_identifiant, noop_reverse),
    ]
