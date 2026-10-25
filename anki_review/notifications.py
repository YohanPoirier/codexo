"""Notifications push (Anki et Codexo) : calcul du contenu et envoi.

Envois planifiés (commande `envoyer_notifications`, lancée TOUTES LES HEURES par le serveur),
chacun en notification séparée, avec l'icône et le lien de son appli :
  - Anki, cartes à réviser (échéance dépassée, hors cartes suspendues) : au jour et à l'heure
    choisis par chacun (tous les jours possible ; dimanche 18 h par défaut) ;
  - Anki, nouvelles cartes partagées par un professeur depuis l'annonce précédente, pas encore
    ajoutées : tous les jours à 20 h, s'il y en a ;
  - Codexo, nouveaux exercices devenus visibles pour la classe : au passage qui suit.
Envois immédiats (dans un fil à part) : modification proposée sur une carte, réponse à une
demande d'aide, nouvelle demande d'aide ou de mot de passe (professeurs).
Aucun message n'est envoyé s'il n'y a rien à dire. Les vues de la page « Notifications »
réutilisent envoyer_message() pour le bouton de test.
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

# Si le dernier envoi date de plus de 14 jours (élève qui avait coupé les notifications,
# par exemple), on ne remonte pas plus loin pour les « nouvelles cartes ».
FENETRE_MAX_JOURS = 14
# Heure (locale) de l'annonce quotidienne des nouvelles cartes.
HEURE_NOUVELLES = 20
# Deux passages à moins de 50 minutes d'écart sur un même créneau : le second ne renvoie rien
# (protège d'un double lancement de la tâche horaire).
ECART_MIN_MINUTES = 50
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


def message_revisions(nb_a_reviser):
    """Rappel « cartes à réviser » (Anki), ou None s'il n'y en a pas."""
    if not nb_a_reviser:
        return None
    return {
        "titre": "Cartes à réviser",
        "corps": f"Tu as {_cartes(nb_a_reviser)} à réviser.",
        "url": reverse("anki_review:liste_decks"),
        "tag": "anki-rappel",
    }


def message_nouvelles(nb_nouvelles):
    """Annonce des nouvelles cartes partagées par un professeur (Anki), ou None."""
    if not nb_nouvelles:
        return None
    s = "s" if nb_nouvelles > 1 else ""
    return {
        "titre": "Nouvelles cartes",
        "corps": f"Ton professeur a partagé {nb_nouvelles} nouvelle{s} carte{s} : ajoute-les à tes révisions.",
        "url": reverse("anki_review:partage_etudiants"),
        "tag": "anki-nouvelles",   # ne remplace pas un rappel de révision encore affiché
    }


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


# ---------------------------------------------------------------- tâche planifiée (toutes les heures)


def _texte_envoi(envoyes):
    if not envoyes:
        return "échec de l'envoi"
    return f"envoyé sur {envoyes} appareil{'s' if envoyes > 1 else ''}"


def _jour_ok(jour_choisi, local):
    return jour_choisi == PreferencesNotification.TOUS_LES_JOURS or jour_choisi == local.weekday()


def _deja_fait(dernier, maintenant):
    return dernier is not None and maintenant - dernier < timedelta(minutes=ECART_MIN_MINUTES)


def envoyer_planifie(simulation=False, force=False, identifiant=None, maintenant=None):
    """Passage horaire sur les utilisateurs abonnés (tâche cron « 0 * * * * »).

    - Cartes à réviser (Anki) : au jour et à l'heure choisis par chacun (tous les jours possible).
    - Nouvelles cartes (Anki) : tous les jours à 20 h, s'il y en a depuis l'annonce précédente.
    - Nouveaux exercices (Codexo) : à chaque passage, donc au plus une heure après leur
      publication (un seul message si plusieurs exercices sont publiés en même temps).
    Chaque annonce est une notification séparée, et rien n'est envoyé s'il n'y a rien à dire.

    simulation : calcule tout et retourne le détail, sans rien envoyer ni enregistrer.
    force      : ignore le jour et l'heure choisis (et le délai anti-doublon) : tout est
                 calculé maintenant.
    identifiant: ne traite que cet utilisateur.

    Retourne une liste de dictionnaires {etudiant, a_reviser, nouvelles, exercices, statut,
    envoyes} — seulement pour les utilisateurs concernés à ce passage.
    """
    maintenant = maintenant or timezone.now()
    local = timezone.localtime(maintenant)
    User = get_user_model()
    utilisateurs = (
        User.objects.filter(is_active=True, abonnements_push__isnull=False)
        .distinct()
        .order_by("pk")
    )
    if identifiant:
        utilisateurs = utilisateurs.filter(**{User.USERNAME_FIELD: identifiant})

    resultats = []
    for utilisateur in utilisateurs:
        prefs = PreferencesNotification.pour(utilisateur)
        ligne = {"etudiant": utilisateur, "a_reviser": 0, "nouvelles": 0, "exercices": 0,
                 "statut": "", "envoyes": 0}
        envois = []      # (nom, message, champ de date à poser si l'envoi part)
        a_marquer = []   # créneaux traités sans rien à envoyer

        # Cartes à réviser
        if prefs.cartes_a_reviser and (force or (
            _jour_ok(prefs.jour_revisions, local) and local.hour == prefs.heure_revisions
            and not _deja_fait(prefs.dernier_rappel_revisions, maintenant)
        )):
            ligne["a_reviser"] = compter_a_reviser(utilisateur, maintenant)
            m = message_revisions(ligne["a_reviser"])
            (envois.append(("Révisions", m, "dernier_rappel_revisions")) if m
             else a_marquer.append("dernier_rappel_revisions"))

        # Nouvelles cartes
        if prefs.nouvelles_cartes and (force or (
            local.hour == HEURE_NOUVELLES and not _deja_fait(prefs.dernier_envoi_nouvelles, maintenant)
        )):
            depuis = max(prefs.dernier_envoi_nouvelles or (maintenant - timedelta(days=1)),
                         maintenant - timedelta(days=FENETRE_MAX_JOURS))
            ligne["nouvelles"] = compter_nouvelles_cartes(utilisateur, depuis)
            m = message_nouvelles(ligne["nouvelles"])
            (envois.append(("Nouvelles cartes", m, "dernier_envoi_nouvelles")) if m
             else a_marquer.append("dernier_envoi_nouvelles"))

        # Nouveaux exercices (Codexo) : le premier passage (exercices_connus vide) sert d'état
        # de départ. L'état avance même si les notifications Codexo sont coupées, pour ne pas
        # annoncer de retard à la réactivation.
        etat_exercices = sorted(exercices_visibles_ids(utilisateur))
        message_exos = None
        if (settings.NOTIFICATIONS_CODEXO and prefs.exercices_connus is not None
                and prefs.nouveaux_exercices):
            exercices = nouveaux_exercices(utilisateur, prefs.exercices_connus)
            ligne["exercices"] = len(exercices)
            message_exos = construire_message_exercices(exercices)
            if message_exos:
                envois.append(("Exercices", message_exos, "exercices_connus"))

        if not envois and not a_marquer and etat_exercices == prefs.exercices_connus:
            continue   # rien à faire pour cet utilisateur à cette heure
        resultats.append(ligne)

        envoyes = {}
        if not envois:
            ligne["statut"] = "rien à annoncer"
        elif simulation:
            ligne["statut"] = "simulation (rien envoyé)"
        else:
            for nom, m, _ in envois:
                envoyes[nom] = envoyer_message(utilisateur, m)
            ligne["envoyes"] = max(envoyes.values())
            ligne["statut"] = " ; ".join(f"{nom} : {_texte_envoi(n)}" for nom, n in envoyes.items())

        if simulation:
            continue
        # Une date n'avance que si l'annonce correspondante est partie (sinon elle sera
        # reprise au créneau suivant) ; idem pour l'état des exercices.
        champs = list(a_marquer)
        for nom, _, champ in envois:
            if envoyes.get(nom) and champ != "exercices_connus":
                champs.append(champ)
        for champ in champs:
            setattr(prefs, champ, maintenant)
        if message_exos is None or envoyes.get("Exercices"):
            prefs.exercices_connus = etat_exercices
            champs.append("exercices_connus")
        if champs:
            prefs.save(update_fields=champs)
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
