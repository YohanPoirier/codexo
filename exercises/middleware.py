from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


class IntroPasAPasMiddleware:
    """Une fois le mode pas à pas ouvert aux élèves (settings.PAS_A_PAS_ELEVES), chaque élève
    est redirigé UNE fois vers la page qui le présente, à sa première visite d'une page du site.
    Le bouton « J'ai compris » (vue intro_pas_a_pas) coche user.a_vu_intro_pas_a_pas et le
    renvoie vers la page qu'il demandait.

    Seules les pages ordinaires (GET) sont concernées : ni les appels d'API, ni les envois de
    formulaire, ni l'admin. Le changement de mot de passe obligatoire reste prioritaire
    (ForcerChangementMotDePasseMiddleware, placé avant celui-ci). Les profs et admins ne sont
    pas redirigés : ils peuvent voir la page à son adresse.
    """

    PREFIXES_EXEMPTES = ("/api/", "/admin/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            settings.PAS_A_PAS_ELEVES
            and request.method == "GET"
            and user is not None
            and user.is_authenticated
            and not user.is_staff
            and not getattr(user, "a_vu_intro_pas_a_pas", True)
            and not request.path.startswith(self.PREFIXES_EXEMPTES)
        ):
            intro = reverse("intro_pas_a_pas")
            if request.path not in {intro, reverse("logout"), reverse("changer_mot_de_passe")}:
                return redirect(intro + "?" + urlencode({"next": request.get_full_path()}))
        return self.get_response(request)
