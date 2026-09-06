from django import forms
from .models import DemandeReinitialisation


class DemandeReinitialisationForm(forms.ModelForm):
    """Formulaire public de demande de réinitialisation de mot de passe (voir
    accounts/views.py : demande_mot_de_passe_oublie). Aucune vérification n'est
    faite ici que l'identifiant saisi correspond à un compte réel — c'est un prof
    qui filtre ça à la main en traitant la demande."""

    class Meta:
        model = DemandeReinitialisation
        fields = ["identifiant_saisi", "email_contact"]
        labels = {
            "identifiant_saisi": "Ton identifiant",
            "email_contact": "Une adresse email où te répondre",
        }
