from django.core.management.base import BaseCommand

from exercises.export_utils import export_exercises_to_json, DATA_FILE


class Command(BaseCommand):
    help = (
        "Exporte les thèmes/exercices actuellement en base vers exercises_data.json, "
        "pour pouvoir committer ce fichier et le partager (Git). "
        "Note : normalement inutile au quotidien, l'export se fait déjà automatiquement "
        "à chaque sauvegarde dans l'admin. Utile surtout pour forcer une resynchronisation."
    )

    def handle(self, *args, **options):
        count = export_exercises_to_json()
        self.stdout.write(self.style.SUCCESS(
            f"{count} thème(s) exportés vers {DATA_FILE.name}. "
            f"Pense à faire 'git add {DATA_FILE.name} && git commit && git push'."
        ))
