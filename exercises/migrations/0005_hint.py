from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('exercises', '0004_theme_sql_setup_alter_exercise_sql_setup'),
    ]

    operations = [
        migrations.CreateModel(
            name='Hint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField(help_text="Texte de l'indice (Markdown simple accepté, comme pour l'énoncé).")),
                ('order', models.PositiveIntegerField(default=0)),
                ('exercise', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hints', to='exercises.exercise')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
    ]
