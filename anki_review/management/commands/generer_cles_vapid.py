"""Génère la paire de clés qui identifie le serveur auprès des services de notifications.

À lancer UNE SEULE FOIS, puis à copier dans le .env du serveur :

    python manage.py generer_cles_vapid

Changer les clés plus tard désabonne tous les appareils (chaque élève devrait
réactiver les notifications) : ne pas les régénérer sans raison. La clé privée est
secrète : ne jamais la commiter ni la partager.
"""
import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid


def _b64url(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


class Command(BaseCommand):
    help = "Génère les clés VAPID (notifications push) à copier dans le .env."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        privee = _b64url(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
        publique = _b64url(vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        ))
        self.stdout.write("Copie ces trois lignes dans le fichier .env du serveur :\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={publique}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={privee}")
        self.stdout.write("VAPID_CONTACT=mailto:TON-ADRESSE@exemple.fr")
        self.stdout.write(
            "\n(Remplace l'adresse de contact par la tienne. La clé privée est secrète.)"
        )
