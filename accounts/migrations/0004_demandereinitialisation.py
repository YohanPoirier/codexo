from django.db import migrations, models


class Migration(migrations.Migration):

    # Corrige un oubli de la migration précédente : le modèle
    # DemandeReinitialisation (accounts/models.py) est entièrement nouveau et n'a
    # jamais eu de migration créant sa table.
    dependencies = [
        ("accounts", "0003_ajout_identifiant_et_doit_changer_mdp"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemandeReinitialisation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "identifiant_saisi",
                    models.CharField(
                        help_text=(
                            "Tel que saisi par l'élève, pas forcément un "
                            "identifiant existant."
                        ),
                        max_length=150,
                        verbose_name="identifiant saisi",
                    ),
                ),
                (
                    "email_contact",
                    models.EmailField(
                        help_text=(
                            "Adresse à laquelle le prof enverra lui-même le "
                            "nouveau mot de passe."
                        ),
                        max_length=254,
                        verbose_name="email de contact",
                    ),
                ),
                (
                    "date_demande",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="date de la demande"
                    ),
                ),
                ("traite", models.BooleanField(default=False, verbose_name="traité")),
                (
                    "traite_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="traité le"
                    ),
                ),
            ],
            options={
                "verbose_name": "demande de réinitialisation",
                "verbose_name_plural": "demandes de réinitialisation",
                "ordering": ["traite", "-date_demande"],
            },
        ),
    ]
