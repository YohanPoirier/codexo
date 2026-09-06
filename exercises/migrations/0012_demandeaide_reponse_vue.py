from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exercises", "0011_demandeaide"),
    ]

    operations = [
        migrations.AddField(
            model_name="demandeaide",
            name="reponse_vue",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True dès que l'élève a ouvert sa page \"Mes demandes d'aide\" après que "
                    "la réponse a été envoyée (voir mes_demandes_aide dans views.py). Sert "
                    "uniquement au petit témoin de notification dans le menu du haut — n'a "
                    "aucun effet sur l'affichage de la réponse elle-même, toujours visible."
                ),
            ),
        ),
    ]
