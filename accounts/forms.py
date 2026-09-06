from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache

from .models import DemandeReinitialisation

# Nombre d'échecs de connexion tolérés pour un même identifiant avant blocage
# temporaire, et durée de ce blocage (voir ConnexionThrottleeForm ci-dessous).
NB_TENTATIVES_MAX = 5
DUREE_BLOCAGE_SECONDES = 15 * 60  # 15 minutes


class ConnexionThrottleeForm(AuthenticationForm):
    """AuthenticationForm avec blocage temporaire après plusieurs échecs, pour
    limiter le brute-force sur le formulaire de connexion — devenu un vrai risque
    depuis que le mot de passe provisoire d'un élève importé par CSV est sa date
    de naissance (voir contexte-technique.md, section "Refonte de
    l'authentification") : un espace de recherche assez restreint si on connaît
    déjà l'identifiant d'un élève.

    Le compteur d'échecs est stocké dans le cache Django (CACHES, LocMemCache par
    défaut ici) et clé par identifiant (pas par IP) : après NB_TENTATIVES_MAX
    échecs pour un identifiant donné, toute nouvelle tentative est bloquée
    pendant DUREE_BLOCAGE_SECONDES, qu'elle vienne du même appareil ou non.

    Limite à connaître : LocMemCache n'est PAS partagé entre plusieurs process
    (si le serveur de prod lance gunicorn avec plusieurs workers, chaque worker a
    son propre compteur — le blocage reste utile mais moins strict que si tous
    les workers partageaient le même cache). Pour un blocage strict même à
    plusieurs workers, il faudrait passer à un cache partagé (Redis/Memcached)
    dans CACHES — pas fait ici pour rester simple, à revoir seulement si ça
    s'avère nécessaire en pratique."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "trop_de_tentatives": (
            "Trop de tentatives échouées pour cet identifiant. Réessaie dans "
            "quelques minutes."
        ),
    }

    @staticmethod
    def _cle_cache(identifiant):
        return f"tentatives_connexion:{identifiant}"

    def clean(self):
        identifiant = self.cleaned_data.get(self.username_field.name)
        if identifiant:
            cle = self._cle_cache(identifiant)
            if cache.get(cle, 0) >= NB_TENTATIVES_MAX:
                raise forms.ValidationError(
                    self.error_messages["trop_de_tentatives"],
                    code="trop_de_tentatives",
                )
        try:
            return super().clean()
        except forms.ValidationError:
            if identifiant:
                cle = self._cle_cache(identifiant)
                cache.set(cle, cache.get(cle, 0) + 1, DUREE_BLOCAGE_SECONDES)
            raise

    def get_user(self):
        # Connexion réussie (clean() n'a pas levé d'erreur) : on efface le
        # compteur d'échecs de cet identifiant.
        user = super().get_user()
        identifiant = self.cleaned_data.get(self.username_field.name)
        if user is not None and identifiant:
            cache.delete(self._cle_cache(identifiant))
        return user


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


class ImporterElevesForm(forms.Form):
    """Formulaire web d'import CSV élèves (voir accounts/views.py :
    importer_eleves_view). La validation/l'import proprement dit passe par
    accounts/importation.py, partagé avec la commande de gestion "importer_eleves"
    en ligne de commande — les deux façons de faire l'import donnent donc toujours
    le même résultat."""

    DELIMITER_CHOICES = [
        (",", "Virgule ( , )"),
        (";", "Point-virgule ( ; ) — export Excel en français"),
    ]

    fichier = forms.FileField(
        label="Fichier CSV",
        help_text=(
            "Colonnes attendues, avec en-tête : id, nom_complet, classe, "
            "date_naissance (format JJ/MM/AAAA, ex: 15/03/2007). Les classes "
            "doivent déjà exister dans l'admin (recherche par nom exact)."
        ),
    )
    delimiter = forms.ChoiceField(
        label="Séparateur de colonnes",
        choices=DELIMITER_CHOICES,
        initial=",",
    )
