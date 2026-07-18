import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('exercises', '0006_abandonment'),
    ]

    operations = [
        migrations.AddField(
            model_name='result',
            name='is_attempt',
            field=models.BooleanField(default=False, help_text='True uniquement si cette ligne vient d\'un clic sur "Vérifier" (une vraie tentative de résolution). False pour les sauvegardes automatiques (départ de page) ou manuelles (bouton disquette), qui créent aussi une ligne Result mais ne comptent pas comme un essai.'),
        ),
        migrations.AddField(
            model_name='result',
            name='time_seconds',
            field=models.PositiveIntegerField(default=0, help_text='Temps écoulé (en secondes), mesuré côté navigateur, depuis le dernier enregistrement pour cet exercice (ou depuis le chargement de la page si c\'est le premier). Sommer ce champ sur toutes les lignes Result d\'un couple (user, exercise) donne le temps total passé, même si l\'étudiant a quitté puis repris l\'exercice plusieurs fois.'),
        ),
        migrations.CreateModel(
            name='HintReveal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('hint', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reveals', to='exercises.hint')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hint_reveals', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='hintreveal',
            unique_together={('user', 'hint')},
        ),
    ]
