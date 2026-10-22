"""Notifications push d'Anki : calcul du contenu et envoi.

Deux informations, regroupées en UN seul message par élève et par semaine :
  - les cartes à réviser (échéance dépassée, hors cartes suspendues) ;
  - les nouvelles cartes partagées par un prof depuis le dernier passage, que
    l'élève n'a pas encore ajoutées à ses révisions.
Aucun message n'est envoyé s'il n'y a rien à dire.

L'envoi hebdomadaire est lancé par la commande `envoyer_notifications` (tâche
planifiée du serveur). Les vues de la page « Notifications » réutilisent
envoyer_message() pour le bouton de test.
"""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from .models import AbonnementPush, Card, Note, PreferencesNotification

logger = logging.getLogger(__name__)

# Si le dernier passage date de plus de 14 jours (élève qui avait coupé les notifications,
# par exemple), on ne remonte pas plus loin pour les « nouvelles cartes ».
FENETRE_MAX_JOURS = 14
# Délai minimal entre deux passages sur un même élève (protège d'un double lancement).
INTERVALLE_MIN_JOURS = 6
# Durée pendant laquelle le service de notifications garde le message si le téléphone
# est éteint ou hors ligne.
TTL_SECONDES = 3 * 24 * 3600


def configuration_ok():
    """Clés d'envoi présentes dans l'environnement (voir settings.VAPID_*)."""
    return bool(
        settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_CONTACT
    )


# ---------------------------------------------------------------- contenu


def compter_a_reviser(etudiant, maintenant=None):
    maintenant = maintenant or timezone.now()
    return Card.objects.filter(
        etudiant=etudiant, suspendue=False, prochaine_revision__lte=maintenant
    ).count()


def compter_nouvelles_cartes(etudiant, depuis):
    """Cartes partagées par un prof depuis `depuis`, que l'élève n'a pas encore."""
    deja = Card.objects.filter(etudiant=etudiant).values("note_id")
    return (
        Note.objects.filter(
            partagee_avec_classe=True,
            cree_par__is_staff=True,
            partagee_le__gt=depuis,
        )
        .exclude(id__in=deja)
        .count()
    )


def _cartes(n):
    return f"{n} carte{'s' if n > 1 else ''}"


def construire_message(nb_a_reviser, nb_nouvelles):
    """Dictionnaire {titre, corps, url} ou None s'il n'y a rien à annoncer."""
    url_accueil = reverse("anki_review:liste_decks")
    url_partage = reverse("anki_review:partage_etudiants")
    if nb_a_reviser and nb_nouvelles:
        return {
            "titre": "Anki",
            "corps": (
                f"{_cartes(nb_a_reviser)} à réviser et "
                f"{nb_nouvelles} nouvelle{'s' if nb_nouvelles > 1 else ''} "
                f"carte{'s' if nb_nouvelles > 1 else ''} à ajouter."
            ),
            "url": url_accueil,
        }
    if nb_a_reviser:
        return {
            "titre": "Cartes à réviser",
            "corps": f"Tu as {_cartes(nb_a_reviser)} à réviser.",
            "url": url_accueil,
        }
    if nb_nouvelles:
        return {
            "titre": "Nouvelles cartes",
            "corps": (
                f"Ton prof a partagé {nb_nouvelles} nouvelle{'s' if nb_nouvelles > 1 else ''} "
                f"carte{'s' if nb_nouvelles > 1 else ''} : ajoute-les à tes révisions."
            ),
            "url": url_partage,
        }
    return None


# ---------------------------------------------------------------- envoi


def _icone():
    try:
        return static("anki_review/icons/favicon-192.png")
    except ValueError:  # fichier absent du manifeste statique (ex. avant collectstatic)
        return None


def envoyer_push(abonnement, message):
    """Envoie `message` à un appareil. Retourne "ok", "mort" (appareil désinscrit :
    l'abonnement est alors supprimé) ou "erreur"."""
    from pywebpush import WebPushException, webpush

    charge = dict(message)
    icone = _icone()
    if icone:
        charge["icone"] = icone
    try:
        webpush(
            subscription_info={
                "endpoint": abonnement.endpoint,
                "keys": {"p256dh": abonnement.p256dh, "auth": abonnement.auth},
            },
            data=json.dumps(charge, ensure_ascii=False),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_CONTACT},
            ttl=TTL_SECONDES,
            timeout=15,
        )
        return "ok"
    except WebPushException as exc:
        statut = getattr(getattr(exc, "response", None), "status_code", None)
        if statut in (404, 410):
            abonnement.delete()
            return "mort"
        logger.warning("Envoi push échoué (abonnement %s, statut %s) : %s", abonnement.pk, statut, exc)
        return "erreur"
    except Exception as exc:  # réseau, clé invalide... : ne jamais interrompre la boucle d'envoi
        logger.warning("Envoi push échoué (abonnement %s) : %s", abonnement.pk, exc)
        return "erreur"


def envoyer_message(etudiant, message):
    """Envoie `message` à tous les appareils de l'élève. Retourne le nombre d'appareils
    atteints."""
    envoyes = 0
    for abonnement in list(AbonnementPush.objects.filter(etudiant=etudiant)):
        if envoyer_push(abonnement, message) == "ok":
            envoyes += 1
    return envoyes


# ---------------------------------------------------------------- tâche hebdomadaire


def envoyer_hebdomadaire(simulation=False, force=False, identifiant=None, maintenant=None):
    """Passe sur les élèves abonnés et envoie le message hebdomadaire.

    simulation : calcule tout et retourne le détail, sans rien envoyer ni enregistrer.
    force      : ignore le délai minimal entre deux passages.
    identifiant: ne traite que cet élève.

    Retourne une liste de dictionnaires {etudiant, a_reviser, nouvelles, message, statut,
    envoyes} utilisée par la commande pour afficher le détail.
    """
    maintenant = maintenant or timezone.now()
    User = get_user_model()
    eleves = (
        User.objects.filter(is_active=True, is_staff=False, abonnements_push__isnull=False)
        .distinct()
        .order_by("pk")
    )
    if identifiant:
        eleves = eleves.filter(**{User.USERNAME_FIELD: identifiant})

    resultats = []
    for eleve in eleves:
        preferences = PreferencesNotification.pour(eleve)
        ligne = {"etudiant": eleve, "a_reviser": 0, "nouvelles": 0, "message": None,
                 "statut": "", "envoyes": 0}
        resultats.append(ligne)

        if (
            not force
            and preferences.dernier_passage
            and maintenant - preferences.dernier_passage < timedelta(days=INTERVALLE_MIN_JOURS)
        ):
            ligne["statut"] = "déjà traité cette semaine"
            continue

        depuis = max(
            preferences.dernier_passage or (maintenant - timedelta(days=7)),
            maintenant - timedelta(days=FENETRE_MAX_JOURS),
        )
        if preferences.cartes_a_reviser:
            ligne["a_reviser"] = compter_a_reviser(eleve, maintenant)
        if preferences.nouvelles_cartes:
            ligne["nouvelles"] = compter_nouvelles_cartes(eleve, depuis)
        ligne["message"] = construire_message(ligne["a_reviser"], ligne["nouvelles"])

        if ligne["message"] is None:
            ligne["statut"] = "rien à annoncer"
        elif simulation:
            ligne["statut"] = "simulation (rien envoyé)"
        else:
            ligne["envoyes"] = envoyer_message(eleve, ligne["message"])
            ligne["statut"] = (
                f"envoyé sur {ligne['envoyes']} appareil{'s' if ligne['envoyes'] > 1 else ''}"
                if ligne["envoyes"] else "échec de l'envoi"
            )

        # On marque le passage sauf en simulation, et sauf si l'envoi a échoué partout
        # (pour qu'un nouvel essai ne considère pas la semaine comme traitée).
        if not simulation and (ligne["message"] is None or ligne["envoyes"]):
            preferences.dernier_passage = maintenant
            preferences.save(update_fields=["dernier_passage"])
    return resultats
