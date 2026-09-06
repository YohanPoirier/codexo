"""Mêmes règles de validation que les 4 validateurs standard de Django (import direct,
aucune logique de validation réécrite), seul le texte d'AIDE affiché dans l'admin est
modifié : Django dit "Votre mot de passe..." (vouvoiement), remplacé ici par une
formulation impersonnelle ("Le mot de passe...") pour rester cohérent avec le ton utilisé
partout ailleurs dans l'admin (voir la discussion du 06/09/2026). Les messages d'erreur
affichés en cas de mot de passe invalide ne sont PAS concernés : ils sont déjà impersonnels
("Ce mot de passe est trop court...") et n'ont donc pas besoin d'être modifiés.

Utilisé à la place des validateurs Django dans AUTH_PASSWORD_VALIDATORS (voir settings.py).
"""

from django.contrib.auth import password_validation as _django_password_validation


class MinimumLengthValidator(_django_password_validation.MinimumLengthValidator):
    def get_help_text(self):
        return f"Le mot de passe doit contenir au minimum {self.min_length} caractères."


class UserAttributeSimilarityValidator(_django_password_validation.UserAttributeSimilarityValidator):
    def get_help_text(self):
        return (
            "Le mot de passe ne peut pas trop ressembler aux autres informations "
            "personnelles du compte."
        )


class CommonPasswordValidator(_django_password_validation.CommonPasswordValidator):
    def get_help_text(self):
        return "Le mot de passe ne peut pas être un mot de passe couramment utilisé."


class NumericPasswordValidator(_django_password_validation.NumericPasswordValidator):
    def get_help_text(self):
        return "Le mot de passe ne peut pas être entièrement numérique."
