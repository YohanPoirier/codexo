"""Rangement personnel (1/3) : structure. Card.deck (provisoirement facultatif, rempli par la
migration suivante), table des règles de rangement, Note.deck devient le paquet de l'auteur."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anki_review", "0022_suggestiondeplacement"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="deck",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="cartes",
                to="anki_review.deck",
            ),
        ),
        migrations.AlterField(
            model_name="note",
            name="deck",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="notes", to="anki_review.deck",
            ),
        ),
        migrations.CreateModel(
            name="RegleRangement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("destination", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anki_review.deck")),
                ("etudiant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="regles_rangement",
                    to=settings.AUTH_USER_MODEL)),
                ("origine", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anki_review.deck")),
            ],
            options={"unique_together": {("etudiant", "origine")}},
        ),
    ]
