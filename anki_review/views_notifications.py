"""Vues des notifications d'Anki : page de réglages, abonnement des appareils, test.

L'abonnement (endpoint + clés) est créé côté navigateur par le JS de
static/anki_review/js/notifications.js, puis enregistré ici. Il n'existe aucun moyen
d'envoyer quoi que ce soit à un appareil qui ne s'est pas abonné lui-même : l'élève doit
appuyer sur « Activer » (bandeau de l'accueil ou cette page).
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import notifications
from .models import AbonnementPush, PreferencesNotification

LONGUEUR_ENDPOINT_MAX = 2000


def contexte_invitation(user):
    """Contexte du bandeau d'invitation de l'accueil : seulement pour un élève, et seulement
    si les clés d'envoi sont configurées sur le serveur."""
    return {
        "invitation_notifications": (
            user.is_authenticated and not user.is_staff and notifications.configuration_ok()
        ),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
    }


@login_required
def page(request):
    preferences = PreferencesNotification.pour(request.user)
    return render(request, "anki_review/notifications.html", {
        "configure": notifications.configuration_ok(),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "preferences": preferences,
    })


@login_required
@require_POST
def enregistrer_preferences(request):
    preferences = PreferencesNotification.pour(request.user)
    preferences.nouvelles_cartes = "nouvelles_cartes" in request.POST
    preferences.cartes_a_reviser = "cartes_a_reviser" in request.POST
    preferences.save(update_fields=["nouvelles_cartes", "cartes_a_reviser"])
    messages.success(request, "Réglages enregistrés.")
    return redirect("anki_review:notifications")


def _json_du_corps(request):
    try:
        donnees = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return donnees if isinstance(donnees, dict) else None


@login_required
@require_POST
def abonner(request):
    """Enregistre l'appareil qui vient d'accepter les notifications."""
    if not notifications.configuration_ok():
        return JsonResponse({"erreur": "Notifications non configurées sur le serveur."}, status=503)
    donnees = _json_du_corps(request)
    cles = (donnees or {}).get("keys")
    endpoint = (donnees or {}).get("endpoint")
    if (
        not isinstance(endpoint, str) or not endpoint.startswith("https://")
        or len(endpoint) > LONGUEUR_ENDPOINT_MAX
        or not isinstance(cles, dict)
        or not isinstance(cles.get("p256dh"), str) or not isinstance(cles.get("auth"), str)
        or not cles["p256dh"] or not cles["auth"]
        or len(cles["p256dh"]) > 200 or len(cles["auth"]) > 100
    ):
        return JsonResponse({"erreur": "Abonnement invalide."}, status=400)

    # Un téléphone prêté à un autre élève : l'appareil passe au dernier compte connecté.
    AbonnementPush.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "etudiant": request.user,
            "p256dh": cles["p256dh"],
            "auth": cles["auth"],
            "user_agent": request.headers.get("User-Agent", "")[:200],
        },
    )
    PreferencesNotification.pour(request.user)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def desabonner(request):
    donnees = _json_du_corps(request)
    endpoint = (donnees or {}).get("endpoint")
    if isinstance(endpoint, str):
        AbonnementPush.objects.filter(etudiant=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def tester(request):
    """Envoie une notification de test à tous les appareils de l'utilisateur. Le champ
    « appli » (anki par défaut, ou codexo) choisit l'icône, le message et la page de retour."""
    codexo = request.POST.get("appli") == "codexo"
    retour = "notifications_codexo" if codexo else "anki_review:notifications"
    if not notifications.configuration_ok():
        messages.error(request, "Les notifications ne sont pas configurées sur le serveur.")
    else:
        if codexo:
            message = {
                "titre": "Notification de test",
                "corps": "Tout fonctionne : tu recevras tes rappels Codexo sur cet appareil.",
                "url": reverse("theme_list"),
                "appli": "codexo",
            }
        else:
            message = {
                "titre": "Notification de test",
                "corps": "Tout fonctionne : tu recevras tes rappels Anki sur cet appareil.",
                "url": "/anki/",
            }
        envoyes = notifications.envoyer_message(request.user, message)
        if envoyes:
            messages.success(
                request,
                f"Notification envoyée sur {envoyes} appareil{'s' if envoyes > 1 else ''}.",
            )
        else:
            messages.error(
                request,
                "Aucune notification envoyée : active-les d'abord sur cet appareil, "
                "ou l'envoi a échoué.",
            )
    return redirect(retour)


# ---------------------------------------------------------------- côté Codexo
# Même abonnement d'appareil que pour Anki (un seul par navigateur) : seule la page de
# réglages et le choix « nouveaux exercices » sont propres à Codexo.


@login_required
def page_codexo(request):
    return render(request, "notifications.html", {
        "configure": notifications.configuration_ok(),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "preferences": PreferencesNotification.pour(request.user),
    })


@login_required
@require_POST
def enregistrer_preferences_codexo(request):
    preferences = PreferencesNotification.pour(request.user)
    preferences.nouveaux_exercices = "nouveaux_exercices" in request.POST
    preferences.save(update_fields=["nouveaux_exercices"])
    messages.success(request, "Réglages enregistrés.")
    return redirect("notifications_codexo")
