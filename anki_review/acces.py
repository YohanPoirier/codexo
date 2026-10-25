"""Connexion propre à Anki.

La page de connexion de Codexo (/login/) est hors du périmètre (scope) de l'appli Anki
installée (/anki/) : sur Android, passer par elle affiche un bandeau de navigateur, et la
page montre le logo de Codexo. Anki a donc sa propre page, /anki/connexion/, dans son
périmètre et à son nom ; les vues d'Anki y renvoient les visiteurs non connectés.
"""
from django.contrib.auth.decorators import login_required as _login_required
from django.urls import reverse_lazy

from accounts.views import IdentifiantLoginView

URL_CONNEXION = reverse_lazy("anki_review:connexion")


def login_required(vue):
    """Comme django.contrib.auth.decorators.login_required, mais vers la connexion d'Anki."""
    return _login_required(vue, login_url=URL_CONNEXION)


class ConnexionAnkiView(IdentifiantLoginView):
    """Connexion d'Anki : mêmes règles que celle de Codexo (limitation des essais, changement
    de mot de passe imposé) ; sans adresse « next », on arrive sur la liste des paquets."""

    template_name = "anki_review/connexion.html"
    next_page = reverse_lazy("anki_review:liste_decks")
