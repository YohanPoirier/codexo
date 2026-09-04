from django.db import migrations, models


def enable_everything_for_existing_classes(apps, schema_editor):
    """Préserve le comportement actuel (tout est visible pour tout le monde) au moment
    de la migration : on active explicitement tous les thèmes/exercices EXISTANTS pour
    toutes les classes EXISTANTES à cet instant. Tout thème/exercice créé APRÈS cette
    migration démarre bien invisible par défaut (comportement voulu), puisque cette
    fonction ne s'exécute qu'une seule fois, ici, au moment du déploiement de la migration."""
    Classe = apps.get_model("accounts", "Classe")
    Theme = apps.get_model("exercises", "Theme")
    Exercise = apps.get_model("exercises", "Exercise")

    classes = list(Classe.objects.all())
    if not classes:
        return  # rien à faire s'il n'existe encore aucune classe

    for theme in Theme.objects.all():
        theme.enabled_for_classes.set(classes)
    for exercise in Exercise.objects.all():
        exercise.enabled_for_classes.set(classes)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_classe_user_role_user_classe'),
        ('exercises', '0007_result_tracking_hintreveal'),
    ]

    operations = [
        migrations.AddField(
            model_name='theme',
            name='enabled_for_classes',
            field=models.ManyToManyField(blank=True, related_name='enabled_themes', to='accounts.classe'),
        ),
        migrations.AddField(
            model_name='exercise',
            name='enabled_for_classes',
            field=models.ManyToManyField(blank=True, related_name='enabled_exercises', to='accounts.classe'),
        ),
        migrations.RunPython(enable_everything_for_existing_classes, migrations.RunPython.noop),
    ]
