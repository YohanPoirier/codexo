from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anki_review", "0021_corriger_slugs_paquets"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SuggestionDeplacement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("statut", models.CharField(
                    choices=[("en_attente", "En attente"), ("acceptee", "Acceptée"), ("refusee", "Refusée")],
                    default="en_attente", max_length=12)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("traitee_le", models.DateTimeField(blank=True, null=True)),
                ("ancien_deck", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anki_review.deck")),
                ("auteur", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                    to=settings.AUTH_USER_MODEL)),
                ("destinataire", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="suggestions_deplacement",
                    to=settings.AUTH_USER_MODEL)),
                ("nouveau_deck", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="+", to="anki_review.deck")),
            ],
            options={
                "ordering": ["-cree_le"],
                "unique_together": {("destinataire", "ancien_deck", "nouveau_deck")},
            },
        ),
    ]
