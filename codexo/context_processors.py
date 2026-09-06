from accounts.models import DemandeReinitialisation
from exercises.models import DemandeAide


def notifications(request):
    """Ajoute au contexte de CHAQUE template (voir TEMPLATES/OPTIONS/context_processors dans
    settings.py) de quoi afficher les petits témoins de notification du menu du haut
    (templates/base.html) : un simple booléen "il y a du nouveau", pas un compte exact
    (choix du 06/09/2026 — un point coloré plutôt qu'un chiffre).

    - Élève : une réponse de prof pas encore vue sur une demande d'aide (voir reponse_vue,
      éteint en ouvrant /mes-demandes-aide/).
    - Prof : au moins une demande d'aide ou une demande de mot de passe en attente (champ
      "traite" déjà existant sur les deux modèles, pas besoin de champ dédié ici).

    Seulement 1 ou 2 requêtes .exists() (rapides, indexées sur une clé étrangère/booléen),
    et uniquement pour un utilisateur connecté — rien n'est fait pour les visiteurs anonymes."""
    if not request.user.is_authenticated:
        return {}

    if request.user.is_staff:
        a_demandes_aide_en_attente = DemandeAide.objects.filter(traite=False).exists()
        a_demandes_reinitialisation_en_attente = DemandeReinitialisation.objects.filter(
            traite=False
        ).exists()
        return {
            "a_demandes_aide_en_attente": a_demandes_aide_en_attente,
            "a_demandes_reinitialisation_en_attente": a_demandes_reinitialisation_en_attente,
            "a_notification_espace_prof": (
                a_demandes_aide_en_attente or a_demandes_reinitialisation_en_attente
            ),
        }

    a_reponse_aide_non_lue = DemandeAide.objects.filter(
        eleve=request.user, traite=True, reponse_vue=False
    ).exists()
    return {"a_reponse_aide_non_lue": a_reponse_aide_non_lue}
