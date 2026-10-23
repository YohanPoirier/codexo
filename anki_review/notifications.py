"""Notifications push (Anki et Codexo) : calcul du contenu et envoi.

Chaque élève reçoit, au plus une fois par semaine, jusqu'à DEUX notifications distinctes,
chacune avec l'icône de son appli et ouvrant son appli :
  - Anki : les cartes à réviser (échéance dépassée, hors cartes suspendues) et les
    nouvelles cartes partagées par un professeur depuis le dernier passage, que l'élève
    n'a pas encore ajoutées — regroupées en UN seul message ;
  - Codexo : les nouveaux exercices, c'est-à-dire ceux qui sont devenus visibles pour la
    classe de l'élève depuis le dernier passage (créés, ou rendus visibles ensuite).
Aucun message n'est envoyé s'il n'y a rien à dire.

L'envoi hebdomadaire est lancé par la commande `envoyer_notifications` (tâche
planifiée du serveur). Les vues de la page « Notifications » réutilisent
envoyer_message() pour le bouton de test.
"""
import json
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
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

# Pour chaque appli : grande image de la notification, petite icône monochrome de la barre
# d'état d'Android (sans elle, Android montre une cloche générique) et « tag » : deux
# notifications de tags différents ne se remplacent pas l'une l'autre.
APPLIS = {
    "anki": {
        # Grande icône transparente : la notification est attribuée à l'appli Anki installée
        # (service worker /anki/sw.js), dont l'icône s'affiche déjà à gauche. Sans icône du tout,
        # Chrome en génère une avec la première lettre du site (un « C »).
        "icone": "anki_review/icons/transparent-192.png",
        "badge": "anki_review/icons/badge-96.png",
        "tag": "anki-rappel",
    },
    "codexo": {
        "icone": "favicon-192.png",
        "badge": "badge-96.png",
        "tag": "codexo-nouveautes",
    },
}


def configuration_ok():
    """Clés d'envoi présentes dans l'environnement (voir settings.VAPID_*)."""
    return bool(
        settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_CONTACT
    )


# ---------------------------------------------------------------- contenu : Anki


def compter_a_reviser(etudiant, maintenant=None):
    maintenant = maintenant or timezone.now()
    return Card.objects.filter(
        etudiant=etudiant, suspendue=False, prochaine_revision__lte=maintenant
    ).count()


def compter_nouvelles_cartes(etudiant, depuis):
    """Cartes partagées par un professeur depuis `depuis`, que l'utilisateur n'a pas encore
    (hors les siennes)."""
    deja = Card.objects.filter(etudiant=etudiant).values("note_id")
    return (
        Note.objects.filter(
            partagee_avec_classe=True,
            cree_par__is_staff=True,
            partagee_le__gt=depuis,
        )
        .exclude(id__in=deja)
        .exclude(cree_par=etudiant)  # un professeur n'est pas prévenu de ses propres cartes
        .count()
    )


def _cartes(n):
    return f"{n} carte{'s' if n > 1 else ''}"


def construire_message(nb_a_reviser, nb_nouvelles):
    """Message Anki : dictionnaire {titre, corps, url} ou None s'il n'y a rien à annoncer."""
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
                f"Ton professeur a partagé {nb_nouvelles} nouvelle{'s' if nb_nouvelles > 1 else ''} "
                f"carte{'s' if nb_nouvelles > 1 else ''} : ajoute-les à tes révisions."
            ),
            "url": url_partage,
        }
    return None


# ---------------------------------------------------------------- contenu : Codexo


def exercices_visibles_ids(etudiant):
    """Identifiants des exercices visibles pour l'élève (thème ET exercice ouverts à sa
    classe, comme Exercise.is_visible_for) ; tous si l'élève n'a pas de classe."""
    from exercises.models import Exercise

    exercices = Exercise.objects.all()
    if etudiant.classe_id is not None:
        exercices = exercices.filter(
            enabled_for_classes=etudiant.classe_id,
            theme__enabled_for_classes=etudiant.classe_id,
        )
    return set(exercices.values_list("id", flat=True))


def nouveaux_exercices(etudiant, connus):
    """Exercices visibles pour l'élève et absents de la liste `connus` (identifiants)."""
    from exercises.models import Exercise

    nouveaux = exercices_visibles_ids(etudiant) - set(connus or [])
    return list(
        Exercise.objects.filter(id__in=nouveaux)
        .select_related("theme")
        .order_by("theme__order", "theme__name", "order", "id")
    )


def construire_message_exercices(exercices):
    """Message Codexo : dictionnaire {titre, corps, url, appli} ou None."""
    n = len(exercices)
    if not n:
        return None
    titres = [f"« {e.title} »" for e in exercices]
    if n == 1:
        corps = f"Nouvel exercice : {titres[0]}."
    elif n <= 3:
        corps = f"{n} nouveaux exercices : {', '.join(titres)}."
    else:
        corps = f"{n} nouveaux exercices, dont {titres[0]}, {titres[1]} et {titres[2]}."
    themes = {e.theme_id for e in exercices}
    url = (
        reverse("exercise_list", args=[exercices[0].theme.slug])
        if len(themes) == 1 else reverse("theme_list")
    )
    return {
        "titre": "Nouvel exercice" if n == 1 else "Nouveaux exercices",
        "corps": corps,
        "url": url,
        "appli": "codexo",
    }


# ---------------------------------------------------------------- envoi


def _url_statique(chemin):
    """Adresse d'un fichier statique, ou None s'il est introuvable (ex. avant collectstatic)."""
    try:
        return static(chemin)
    except ValueError:
        return None


def envoyer_push(abonnement, message):
    """Envoie `message` à un appareil. Retourne "ok", "mort" (appareil désinscrit :
    l'abonnement est alors supprimé) ou "erreur"."""
    from pywebpush import WebPushException, webpush

    charge = dict(message)
    appli = APPLIS[charge.pop("appli", "anki")]
    icone = _url_statique(appli["icone"]) if appli["icone"] else None
    badge = _url_statique(appli["badge"])
    if icone:
        charge["icone"] = icone
    if badge:
        charge["badge"] = badge
    charge["tag"] = charge.get("tag") or appli["tag"]
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
    """Envoie `message` à tous les appareils de l'utilisateur abonnés pour l'appli du message
    (message["appli"], Anki par défaut). Retourne le nombre d'appareils atteints."""
    envoyes = 0
    appli = message.get("appli", AbonnementPush.Appli.ANKI)
    for abonnement in list(AbonnementPush.objects.filter(etudiant=etudiant, appli=appli)):
        if envoyer_push(abonnement, message) == "ok":
            envoyes += 1
    return envoyes


# ---------------------------------------------------------------- tâche hebdomadaire


def _texte_envoi(envoyes):
    if not envoyes:
        return "échec de l'envoi"
    return f"envoyé sur {envoyes} appareil{'s' if envoyes > 1 else ''}"


def envoyer_hebdomadaire(simulation=False, force=False, identifiant=None, maintenant=None):
    """Passe sur les élèves abonnés et envoie les notifications de la semaine.

    simulation : calcule tout et retourne le détail, sans rien envoyer ni enregistrer.
    force      : ignore le délai minimal entre deux passages.
    identifiant: ne traite que cet élève.

    Retourne une liste de dictionnaires {etudiant, a_reviser, nouvelles, exercices, message,
    message_exercices, statut, envoyes} utilisée par la commande pour afficher le détail.
    """
    maintenant = maintenant or timezone.now()
    User = get_user_model()
    eleves = (
        User.objects.filter(is_active=True, abonnements_push__isnull=False)
        .distinct()
        .order_by("pk")
    )
    if identifiant:
        eleves = eleves.filter(**{User.USERNAME_FIELD: identifiant})

    resultats = []
    for eleve in eleves:
        preferences = PreferencesNotification.pour(eleve)
        ligne = {"etudiant": eleve, "a_reviser": 0, "nouvelles": 0, "exercices": 0,
                 "message": None, "message_exercices": None, "statut": "", "envoyes": 0}
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

        # Exercices : le premier passage (exercices_connus vide) sert d'état de départ. L'état
        # continue d'avancer même si les notifications Codexo sont désactivées (réglage
        # settings.NOTIFICATIONS_CODEXO), pour ne pas annoncer de retard à la réactivation.
        etat_exercices = sorted(exercices_visibles_ids(eleve))
        if (
            settings.NOTIFICATIONS_CODEXO
            and preferences.exercices_connus is not None
            and preferences.nouveaux_exercices
        ):
            exercices = nouveaux_exercices(eleve, preferences.exercices_connus)
            ligne["exercices"] = len(exercices)
            ligne["message_exercices"] = construire_message_exercices(exercices)

        a_envoyer = [
            (nom, m) for nom, m in (("Anki", ligne["message"]), ("Codexo", ligne["message_exercices"]))
            if m is not None
        ]
        envoyes = {}
        if not a_envoyer:
            ligne["statut"] = "rien à annoncer"
        elif simulation:
            ligne["statut"] = "simulation (rien envoyé)"
        else:
            for nom, m in a_envoyer:
                envoyes[nom] = envoyer_message(eleve, m)
            ligne["envoyes"] = max(envoyes.values())
            if len(a_envoyer) == 1:
                ligne["statut"] = _texte_envoi(ligne["envoyes"])
            else:
                ligne["statut"] = " ; ".join(f"{nom} : {_texte_envoi(n)}" for nom, n in envoyes.items())

        if simulation:
            continue
        # On marque le passage sauf si l'envoi a échoué partout (pour qu'un nouvel essai ne
        # considère pas la semaine comme traitée).
        champs = []
        if not a_envoyer or ligne["envoyes"]:
            preferences.dernier_passage = maintenant
            champs.append("dernier_passage")
        # L'état des exercices n'avance que si leur annonce est partie (ou s'il n'y en avait
        # pas) : sinon ils seraient annoncés la semaine suivante.
        if ligne["message_exercices"] is None or envoyes.get("Codexo"):
            preferences.exercices_connus = etat_exercices
            champs.append("exercices_connus")
        if champs:
            preferences.save(update_fields=champs)
    return resultats


# ---------------------------------------------------------------- propositions de modification


def destinataires_proposition(note):
    """Qui prévenir d'une proposition sur `note` : son propriétaire ; à défaut (carte sans
    propriétaire), les professeurs."""
    if note.cree_par_id:
        return [note.cree_par]
    return list(get_user_model().objects.filter(is_staff=True, is_active=True))


def message_proposition(proposition):
    titre_carte = proposition.note.titre_affichage().strip()
    if len(titre_carte) > 60:
        titre_carte = titre_carte[:57] + "…"
    return {
        "titre": "Modification proposée",
        "corps": f"{proposition.auteur} propose une modification de ta carte « {titre_carte} ».",
        "url": reverse("anki_review:voir_proposition", args=[proposition.id]),
        "tag": f"anki-proposition-{proposition.id}",
    }


def prevenir_proposition(proposition):
    """Notification immédiate au propriétaire de la carte. Envoyée dans un fil à part pour
    ne pas faire attendre l'étudiant qui propose (l'envoi peut prendre quelques secondes)."""
    if not configuration_ok():
        return
    destinataires = [
        u for u in destinataires_proposition(proposition.note)
        if u.id != proposition.auteur_id and PreferencesNotification.pour(u).propositions
    ]
    if not destinataires:
        return
    message = message_proposition(proposition)

    def envoyer():
        try:
            for utilisateur in destinataires:
                envoyer_message(utilisateur, message)
        finally:
            connection.close()

    threading.Thread(target=envoyer, daemon=True).start()


# ---------------------------------------------------------------- demandes d'aide (Codexo)


def _envoyer_en_fond(destinataires, message):
    """Envoi dans un fil à part : la personne qui agit (demande, réponse) n'attend pas."""
    if not destinataires:
        return

    def envoyer():
        try:
            for utilisateur in destinataires:
                envoyer_message(utilisateur, message)
        finally:
            connection.close()

    threading.Thread(target=envoyer, daemon=True).start()


def _codexo_actif():
    return settings.NOTIFICATIONS_CODEXO and configuration_ok()


def prevenir_demande_aide(demande):
    """Nouvelle demande d'aide (ou demande mise à jour) : les professeurs qui le souhaitent."""
    if not _codexo_actif():
        return
    profs = [
        u for u in get_user_model().objects.filter(is_staff=True, is_active=True).exclude(pk=demande.eleve_id)
        if PreferencesNotification.pour(u).demandes_aide
    ]
    _envoyer_en_fond(profs, {
        "titre": "Demande d'aide",
        "corps": f"{demande.eleve} demande de l'aide sur « {demande.exercise.title} ».",
        "url": reverse("demande_aide_detail", args=[demande.id]),
        "appli": "codexo",
        "tag": f"codexo-demande-{demande.id}",   # une demande renvoyée remplace la précédente
    })


def prevenir_reponse_aide(demande):
    """Réponse d'un professeur : l'élève qui avait demandé de l'aide."""
    if not _codexo_actif() or not PreferencesNotification.pour(demande.eleve).reponses_aide:
        return
    _envoyer_en_fond([demande.eleve], {
        "titre": "Réponse à ta demande d'aide",
        "corps": f"Un professeur t'a répondu sur « {demande.exercise.title} ».",
        "url": reverse("mes_demandes_aide"),
        "appli": "codexo",
        "tag": f"codexo-reponse-{demande.id}",
    })


def prevenir_demande_mdp(demande):
    """Demande de réinitialisation de mot de passe (formulaire public) : les professeurs qui le
    souhaitent. Même étiquette pour toutes : plusieurs demandes ne s'empilent pas, la dernière
    remplace la précédente sur le téléphone."""
    if not _codexo_actif():
        return
    profs = [
        u for u in get_user_model().objects.filter(is_staff=True, is_active=True)
        if PreferencesNotification.pour(u).demandes_mdp
    ]
    _envoyer_en_fond(profs, {
        "titre": "Mot de passe oublié",
        "corps": f"Demande de réinitialisation pour « {demande.identifiant_saisi} ».",
        "url": reverse("demandes_reinitialisation"),
        "appli": "codexo",
        "tag": "codexo-mdp",
    })
