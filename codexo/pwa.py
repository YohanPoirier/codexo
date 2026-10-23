"""PWA : manifestes (Codexo et Anki) et service worker.

Le site peut être installé comme une appli (icône sur l'écran d'accueil, plein écran).
Codexo et Anki sont deux « applis » distinctes, chacune avec son manifeste, son icône
et son périmètre (scope) : Codexo couvre tout le site, Anki seulement /anki/.

Ces vues sont publiques (pas de login_required) : le navigateur les réclame sans
cookie de session. Les middlewares qui redirigent les utilisateurs connectés
(changement de mot de passe obligatoire, page d'intro du pas à pas) les exemptent
via PWA_PATHS : un service worker dont l'adresse redirige est refusé par le navigateur.
"""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

# Adresses à ne jamais rediriger (cf. accounts/middleware.py et exercises/middleware.py).
PWA_PATHS = frozenset({"/sw.js", "/anki/sw.js", "/manifest.webmanifest", "/anki.webmanifest"})

COULEUR_FOND = "#f6f2e9"  # --paper de style.css


def _icones(chemin_192, chemin_512):
    return [
        {"src": static(chemin_192), "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": static(chemin_512), "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ]


def _manifeste(donnees):
    reponse = JsonResponse(donnees, json_dumps_params={"ensure_ascii": False})
    reponse["Content-Type"] = "application/manifest+json; charset=utf-8"
    return reponse


@require_GET
def manifeste_codexo(request):
    return _manifeste({
        "id": "/",
        "name": "Codexo",
        "short_name": "Codexo",
        "description": "Exercices de Python et de SQL à correction automatique.",
        "lang": "fr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": COULEUR_FOND,
        "theme_color": "#1c2747",  # --indigo-deep
        "icons": _icones("favicon-192.png", "favicon-512.png"),
    })


@require_GET
def manifeste_anki(request):
    return _manifeste({
        "id": "/anki/",
        "name": "Anki",
        "short_name": "Anki",
        "description": "Révision des cartes de cours.",
        "lang": "fr",
        "start_url": "/anki/",
        "scope": "/anki/",
        "display": "standalone",
        "background_color": COULEUR_FOND,
        "theme_color": "#2b8a7f",
        "icons": _icones("anki_review/icons/favicon-192.png", "anki_review/icons/favicon-512.png"),
    })


@require_GET
def service_worker(request):
    """Sert le service worker à la racine (/sw.js) : servi depuis /static/, il ne
    pourrait contrôler que les pages de /static/.

    Le même script est aussi servi en /anki/sw.js, enregistré avec le périmètre /anki/ :
    Android attribue une notification à l'appli installée dont le périmètre couvre celui
    du service worker qui l'affiche. Avec le seul service worker de la racine, l'appli Anki
    (périmètre /anki/) ne le couvre pas : la notification était attribuée à Chrome (ou à
    Codexo s'il est installé)."""
    reponse = render(
        request,
        "pwa/sw.js",
        {
            "debug": settings.DEBUG,
            "static_prefix": settings.STATIC_URL,
        },
        content_type="application/javascript; charset=utf-8",
    )
    # Le navigateur doit revérifier le script à chaque fois pour détecter une nouvelle version.
    reponse["Cache-Control"] = "no-cache"
    reponse["Service-Worker-Allowed"] = "/"
    return reponse
