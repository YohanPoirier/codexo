import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Classe',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(unique=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.CharField(choices=[('prof', 'Professeur'), ('eleve', 'Élève')], default='eleve', max_length=10),
        ),
        migrations.AddField(
            model_name='user',
            name='classe',
            field=models.ForeignKey(blank=True, help_text="Uniquement pour les élèves : la classe à laquelle ils appartiennent.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='eleves', to='accounts.classe'),
        ),
    ]
