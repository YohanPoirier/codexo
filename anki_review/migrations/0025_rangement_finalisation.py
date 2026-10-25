"""Rangement personnel (3/3) : Card.deck devient obligatoire ; les suggestions de déplacement
disparaissent (chacun range chez soi, il n'y a plus de paquet commun à reconstituer)."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [("anki_review", "0024_rangement_donnees")]

    operations = [
        migrations.AlterField(
            model_name="card",
            name="deck",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="cartes", to="anki_review.deck",
            ),
        ),
        migrations.DeleteModel(name="SuggestionDeplacement"),
    ]
