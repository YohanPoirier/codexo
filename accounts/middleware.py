from django.shortcuts import redirect
from django.urls import reverse

from codexo.pwa import PWA_PATHS


class ForcerChangementMotDePasseMiddleware:
    """Redirige systématiquement vers la page de changement de mot de passe tant que
    request.user.doit_changer_mot_de_passe est True (compte importé par CSV, mot de
    passe provisoire = date de naissance) — voir contexte-technique.md, section
    "Refonte de l'authentification".

    S'applique à TOUTE vue authentifiée sans qu'aucune d'elles n'ait besoin d'être
    modifiée : ce middleware s'exécute avant que la vue ne soit appelée. Seules la
    page de changement de mot de passe elle-même et la déconnexion sont exemptées
    (sans quoi on obtiendrait une boucle de redirection infinie).

    Placé juste après AuthenticationMiddleware dans settings.py, pour que
    request.user soit déjà résolu à ce stade.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "doit_changer_mot_de_passe", False)
        ):
            urls_exemptees = {reverse("changer_mot_de_passe"), reverse("logout")}
            # /sw.js et les manifestes ne doivent jamais rediriger (un service worker
            # dont l'adresse redirige est rejeté par le navigateur).
            if request.path not in urls_exemptees and request.path not in PWA_PATHS:
                return redirect("changer_mot_de_passe")
        return self.get_response(request)
