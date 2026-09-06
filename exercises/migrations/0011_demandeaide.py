import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exercises", "0010_exercise_extra_test_code_exercise_require_recursive"),
    ]

    operations = [
        migrations.CreateModel(
            name="DemandeAide",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code_soumis", models.TextField()),
                ("commentaire", models.TextField(blank=True)),
                ("date_demande", models.DateTimeField(auto_now_add=True)),
                ("traite", models.BooleanField(default=False)),
                ("reponse", models.TextField(blank=True)),
                ("traite_le", models.DateTimeField(blank=True, null=True)),
                (
                    "eleve",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demandes_aide",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "exercise",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demandes_aide",
                        to="exercises.exercise",
                    ),
                ),
                (
                    "traite_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="demandes_aide_traitees",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-date_demande"],
            },
        ),
    ]
