import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import DeckForm, NoteForm
from .models import Card, Deck, Note, PropositionModification
from .sm2 import Reponse, appliquer, calculer_prochaine_etape
from .apkg_import import importer_apkg, analyser_apkg, ErreurImportApkg
from .apkg_export import exporter_notes_apkg

EXTENSIONS_IMAGE_AUTORISEES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Pseudo-matière pour les paquets sans matière assignée — affichés avec la
# même bande que les vraies matières plutôt qu'à part, pour la cohérence
# visuelle (Édition, Révision, Import/Export utilisent tous cette valeur).
VALEUR_SANS_MATIERE = "sans-matiere"
LIBELLE_SANS_MATIERE = "Sans matière"

TAILLE_IMAGE_MAX = 5 * 1024 * 1024  # 5 Mo

# Préfixe reconstitué côté affichage à partir du nom de fichier nu stocké
# dans les champs (voir anki_review/templatetags/anki_extras.py) — transmis
# au template pour que le JS de l'éditeur fasse la même reconstitution dans
# l'aperçu en direct.
PREFIXE_IMAGES_NOTES = f"{settings.MEDIA_URL}anki_review/notes/"

# Nombre d'autres cartes à voir avant qu'une carte répondue "Again" ne
# revienne dans la session en cours (comportement proche des "learning
# steps" d'Anki : une carte ratée revient vite, pas seulement à sa
# prochaine échéance SM-2 réelle).
SEUIL_REAPPARITION_SESSION = 3


def _decks_visibles(user):
    """Paquets visibles par cet utilisateur : ceux du prof (officiels, sans
    créateur ou créé par un membre du staff) + les siens propres + tout
    paquet contenant au moins une note partagée (même appartenant à un
    autre étudiant) — nécessaire depuis qu'une note "récupérée" n'est plus
    copiée dans un paquet à soi : elle reste dans son paquet d'origine, qui
    doit donc devenir visible pour qu'on puisse la retrouver dans Édition.
    Un paquet privé sans aucune note partagée reste invisible aux autres,
    comme avant."""
    if user.is_staff:
        return Deck.objects.all()
    return Deck.objects.filter(
        Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=user)
        | Q(notes__partagee_avec_classe=True)
    ).distinct()


@login_required
def liste_decks(request):
    """Vue d'accueil de l'espace révision : les paquets ayant une matière
    sont regroupés dessous (dépliable, avec un bouton pour tout réviser
    d'un coup) ; les paquets sans matière restent à plat."""
    par_matiere = {}
    paquets_sans_matiere = []
    for deck in _decks_visibles(request.user):
        dues = Card.objects.filter(
            note__deck=deck,
            etudiant=request.user,
            suspendue=False,
            prochaine_revision__lte=timezone.now(),
        ).count()
        total = Card.objects.filter(note__deck=deck, etudiant=request.user).count()
        item = {"deck": deck, "dues": dues, "total": total}
        if deck.matiere:
            groupe = par_matiere.setdefault(deck.matiere, {"paquets": [], "dues": 0, "total": 0})
            groupe["paquets"].append(item)
            groupe["dues"] += dues
            groupe["total"] += total
        else:
            paquets_sans_matiere.append(item)

    matieres = [
        {"valeur": valeur, "libelle": dict(Deck.Matiere.choices).get(valeur, valeur), **compte}
        for valeur, compte in par_matiere.items()
    ]
    matieres.sort(key=lambda m: m["libelle"])

    if paquets_sans_matiere:
        matieres.append({
            "valeur": VALEUR_SANS_MATIERE, "libelle": LIBELLE_SANS_MATIERE,
            "paquets": paquets_sans_matiere,
            "dues": sum(p["dues"] for p in paquets_sans_matiere),
            "total": sum(p["total"] for p in paquets_sans_matiere),
        })

    return render(request, "anki_review/liste_decks.html", {"matieres": matieres})


def _prochaine_carte_due(decks_qs, etudiant):
    return (
        Card.objects.filter(
            note__deck__in=decks_qs,
            etudiant=etudiant,
            suspendue=False,
            prochaine_revision__lte=timezone.now(),
        )
        .select_related("note")
        .order_by("prochaine_revision")
        .first()
    )


def _cle_file_apprentissage():
    return "anki_file_apprentissage"


def _lire_file_apprentissage(request):
    return request.session.get(_cle_file_apprentissage(), [])


def _ecrire_file_apprentissage(request, file):
    request.session[_cle_file_apprentissage()] = file
    request.session.modified = True


def _ajouter_a_la_file_apprentissage(request, carte_id):
    """Une carte répondue "Again" est ajoutée (ou remise à zéro si déjà
    présente) en tête de la file d'apprentissage — GLOBALE par étudiant,
    pas par paquet : une carte ratée dans "Optique" doit être vue comme
    ratée aussi si on la croise via "réviser toute la Physique"."""
    file = [e for e in _lire_file_apprentissage(request) if e["id"] != carte_id]
    file.append({"id": carte_id, "n": 0})
    _ecrire_file_apprentissage(request, file)


def _retirer_de_la_file_apprentissage(request, carte_id):
    file = [e for e in _lire_file_apprentissage(request) if e["id"] != carte_id]
    _ecrire_file_apprentissage(request, file)


def _prochaine_carte(request, decks_qs, etudiant):
    """
    Détermine la prochaine carte à afficher, en combinant :
    - le planning SM-2 classique, restreint à `decks_qs` (le paquet seul,
      ou tous les paquets d'une même matière en mode "réviser la matière")
    - la file d'apprentissage GLOBALE de la session (cartes "Again" plus
      tôt, quel que soit le paquet) — mais on n'en propose une que si elle
      appartient bien à `decks_qs` ; les entrées d'autres paquets restent
      dans la file, en attente, sans être perdues.

    Une entrée n'est retirée DÉFINITIVEMENT de la file que si sa Card
    n'existe plus du tout (supprimée entretemps) — jamais simplement parce
    qu'elle est hors du scope de la session en cours.
    """
    deck_ids = set(decks_qs.values_list("id", flat=True))
    file_brute = _lire_file_apprentissage(request)

    file = []
    carte_apprentissage = None
    for entree in file_brute:
        carte = Card.objects.filter(id=entree["id"], etudiant=etudiant).select_related("note").first()
        if carte is None:
            continue  # supprimée entretemps : oubliée définitivement
        file.append(entree)
        if carte_apprentissage is None and entree["n"] >= SEUIL_REAPPARITION_SESSION and carte.note.deck_id in deck_ids:
            carte_apprentissage = carte

    if carte_apprentissage:
        return carte_apprentissage, file

    carte_due = _prochaine_carte_due(decks_qs, etudiant)
    if carte_due:
        for entree in file:
            entree["n"] += 1
        return carte_due, file

    # Rien de dû dans ce scope, mais une carte en apprentissage de CE
    # scope attend peut-être encore sous le seuil : autant la montrer.
    for entree in file:
        carte = Card.objects.filter(
            id=entree["id"], etudiant=etudiant, note__deck_id__in=deck_ids
        ).select_related("note").first()
        if carte:
            return carte, file

    return None, file


def _formater_intervalle(jours: float) -> str:
    """Convertit un intervalle SM-2 (en jours) en texte court façon
    AnkiDroid : "<10 min"/"<19 h" pour les échéances proches (le "<" reflète
    l'arrondi vers le bas, comme fait Anki), valeur nue en jours/mois/ans
    au-delà — un préavis à la minute près n'a plus de sens à cette échelle."""
    minutes = jours * 24 * 60
    if minutes < 60:
        return f"<{max(1, round(minutes))} min"
    heures = minutes / 60
    if heures < 24:
        return f"<{max(1, round(heures))} h"
    if jours < 30:
        n = round(jours)
        return f"{n} j" if n != 1 else "1 j"
    mois = jours / 30
    if mois < 12:
        n = round(mois)
        return f"{n} mois" if n != 1 else "1 mois"
    ans = jours / 365
    n = round(ans)
    return f"{n} an{'s' if n != 1 else ''}"


def _traiter_revision(request, decks_qs, titre, nom_url_action, args_url_action):
    """
    Logique commune à l'écran de révision, qu'il porte sur UN paquet ou sur
    TOUS les paquets d'une même matière à la fois (cf. reviser et
    reviser_matiere) — seule `decks_qs` change entre les deux cas.
    """
    # Clé de session pour le compteur de progression (cf. plus bas) — une
    # par "portée" de révision (paquet ou matière précis), pour ne pas
    # mélanger la progression de deux sessions différentes.
    cle_progres = "anki_progres_" + "-".join(str(a) for a in args_url_action)

    if request.method == "POST":
        carte = get_object_or_404(Card, id=request.POST["carte_id"], etudiant=request.user)
        reponse = request.POST.get("reponse")
        if reponse in (Reponse.AGAIN, Reponse.HARD, Reponse.GOOD, Reponse.EASY):
            appliquer(carte, reponse)
            carte.save()
            if reponse == Reponse.AGAIN:
                _ajouter_a_la_file_apprentissage(request, carte.id)
            else:
                _retirer_de_la_file_apprentissage(request, carte.id)
            request.session[cle_progres] = request.session.get(cle_progres, 0) + 1
        return redirect(reverse(nom_url_action, args=args_url_action))

    carte, file = _prochaine_carte(request, decks_qs, request.user)
    _ecrire_file_apprentissage(request, file)

    if carte is None:
        request.session.pop(cle_progres, None)
        return render(request, "anki_review/session_terminee.html", {"titre_paquet": titre})

    ids_apprentissage = [e["id"] for e in file]
    nb_apprentissage_scope = Card.objects.filter(id__in=ids_apprentissage, note__deck__in=decks_qs).count()
    restantes = Card.objects.filter(
        note__deck__in=decks_qs, etudiant=request.user, suspendue=False,
        prochaine_revision__lte=timezone.now(),
    ).count() + nb_apprentissage_scope

    # Progression réelle (traitées / total) — pas de "total de session" figé
    # à l'avance, puisque les échecs (Again) remettent une carte dans le
    # lot : "traites" est juste un compteur qui grandit à chaque réponse.
    traites = request.session.get(cle_progres, 0)
    total_session = traites + restantes
    pourcentage = round(traites / total_session * 100) if total_session else 0

    intervalles = {
        reponse: _formater_intervalle(calculer_prochaine_etape(carte, reponse).intervalle_jours)
        for reponse in (Reponse.AGAIN, Reponse.HARD, Reponse.GOOD, Reponse.EASY)
    }

    return render(
        request, "anki_review/reviser.html",
        {
            "titre_paquet": titre, "carte": carte, "note": carte.note, "restantes": restantes,
            "pourcentage": pourcentage, "intervalles": intervalles,
        },
    )


@login_required
def reviser(request, deck_slug):
    """Écran de révision plein écran pour UN paquet précis."""
    deck = get_object_or_404(_decks_visibles(request.user), slug=deck_slug)
    return _traiter_revision(
        request, Deck.objects.filter(pk=deck.pk), deck.nom,
        "anki_review:reviser", [deck_slug],
    )


@login_required
def reviser_matiere(request, matiere):
    """Écran de révision plein écran pour TOUS les paquets d'une matière à
    la fois — pas un vrai paquet Anki, juste un regroupement pour la
    révision (cf. discussion : chaque carte reste dans son paquet réel).
    `matiere` peut aussi être la pseudo-matière "sans-matiere" (paquets
    sans matière assignée, regroupés pour la cohérence visuelle)."""
    if matiere == VALEUR_SANS_MATIERE:
        decks = _decks_visibles(request.user).filter(matiere="")
        libelle = LIBELLE_SANS_MATIERE
    else:
        decks = _decks_visibles(request.user).filter(matiere=matiere)
        libelle = dict(Deck.Matiere.choices).get(matiere, matiere)
    if not decks.exists():
        messages.error(request, "Aucun paquet pour cette matière.")
        return redirect("anki_review:liste_decks")
    return _traiter_revision(request, decks, libelle, "anki_review:reviser_matiere", [matiere])


@login_required
def edition_accueil(request):
    """
    Page d'accueil de l'espace Édition : liste des paquets VISIBLES par
    l'utilisateur, chacun avec ses cartes chargées pour un dépliage inline.
    Les paquets ayant une matière sont regroupés sous celle-ci (dépliable
    elle aussi, sans retrait supplémentaire — seule la couleur de bordure
    distingue les niveaux) ; les paquets sans matière restent à plat.

    Pour un étudiant, "mes cartes" veut dire : celles qu'il a personnellement
    dans sa révision (créées par lui OU récupérées ailleurs) — une note
    n'étant plus dupliquée, "récupérer" ne fait plus que créer une Card sur
    la note déjà existante (cf. ajouter_carte_partagee), donc "cards__etudiant"
    est le bon critère, pas "cree_par" qui ne désigne plus que le
    propriétaire d'origine. Le filtre (?mes=1) n'a de sens que pour le prof,
    qui voit tout par défaut.

    Les PROPOSITIONS DE MODIFICATION en attente sur les notes dont cet
    utilisateur est propriétaire (ou toutes, pour le prof) sont mises en
    avant tout en haut de la page, à valider (cf. voir_proposition).
    """
    filtre_mes = True if not request.user.is_staff else request.GET.get("mes") == "1"

    if request.user.is_staff:
        propositions = PropositionModification.objects.filter(
            statut=PropositionModification.Statut.EN_ATTENTE
        ).select_related("note", "note__cree_par", "auteur")
    else:
        propositions = PropositionModification.objects.filter(
            statut=PropositionModification.Statut.EN_ATTENTE, note__cree_par=request.user,
        ).select_related("note", "auteur")

    decks = _decks_visibles(request.user).order_by("nom")
    par_matiere = {}
    paquets_sans_matiere = []
    for deck in decks:
        if filtre_mes:
            notes = list(
                deck.notes.select_related("cree_par").filter(cards__etudiant=request.user).distinct().order_by("id")
            )
        else:
            notes = list(deck.notes.select_related("cree_par").order_by("id"))
        item = {"deck": deck, "notes": notes}
        if deck.matiere:
            par_matiere.setdefault(deck.matiere, []).append(item)
        else:
            paquets_sans_matiere.append(item)

    matieres = [
        {"valeur": valeur, "libelle": dict(Deck.Matiere.choices).get(valeur, valeur), "paquets": paquets}
        for valeur, paquets in par_matiere.items()
    ]
    matieres.sort(key=lambda m: m["libelle"])

    if paquets_sans_matiere:
        matieres.append({"valeur": VALEUR_SANS_MATIERE, "libelle": LIBELLE_SANS_MATIERE, "paquets": paquets_sans_matiere})

    return render(request, "anki_review/edition_accueil.html", {
        "matieres": matieres, "filtre_mes": filtre_mes, "propositions": propositions,
    })


@login_required
def edition_deck(request, deck_slug):
    """
    Liste des cartes d'un paquet précis. La visibilité du PAQUET lui-même
    suit _decks_visibles (404 si ce paquet privé appartient à un autre
    étudiant) ; les NOTES à l'intérieur suivent la même règle que
    edition_accueil (les siennes pour un étudiant, tout pour le prof).
    """
    deck = get_object_or_404(_decks_visibles(request.user), slug=deck_slug)
    if request.user.is_staff:
        notes = list(deck.notes.select_related("cree_par").order_by("id"))
    else:
        notes = deck.notes.select_related("cree_par").filter(cards__etudiant=request.user).distinct().order_by("id")
    return render(request, "anki_review/edition_deck.html", {"deck": deck, "notes": notes})


def _peut_editer_deck(user, deck):
    """Le prof peut tout modifier ; un étudiant ne peut modifier/supprimer
    que les paquets qu'il a lui-même créés."""
    return user.is_staff or deck.cree_par_id == user.id


@login_required
def ajouter_deck(request):
    """Création ou modification d'un paquet (même template, même vue) —
    ouvert à tout utilisateur connecté. Le slug est généré automatiquement
    à partir du nom à la création (cf. DeckForm.save), inchangé en
    modification.

    Un paquet créé par un étudiant reste visible par toute la classe (pas
    de notion de paquet privé pour l'instant) — seule sa modification est
    restreinte à son créateur (ou au prof).
    """
    if request.method == "POST":
        form = DeckForm(request.POST)
        if form.is_valid():
            deck = form.save(commit=False)
            deck.cree_par = request.user
            deck.save()
            messages.success(request, f"Paquet « {deck.nom} » créé.")
            return redirect("anki_review:edition")
    else:
        form = DeckForm()

    return render(request, "anki_review/ajouter_deck.html", {"form": form})


@login_required
def modifier_deck(request, deck_id):
    deck = get_object_or_404(Deck, id=deck_id)
    if not _peut_editer_deck(request.user, deck):
        return HttpResponseForbidden("Tu ne peux modifier que les paquets que tu as créés.")

    if request.method == "POST":
        form = DeckForm(request.POST, instance=deck)
        if form.is_valid():
            form.save()
            messages.success(request, f"Paquet « {deck.nom} » mis à jour.")
            return redirect("anki_review:edition")
    else:
        form = DeckForm(instance=deck)

    return render(request, "anki_review/ajouter_deck.html", {"form": form, "deck": deck})


@login_required
def supprimer_deck(request, deck_id):
    """Suppression d'un paquet — POST uniquement (déclenché par un petit
    formulaire avec confirmation JS, cf. edition_accueil.html). Supprime en
    cascade ses notes et les cartes de progression associées."""
    deck = get_object_or_404(Deck, id=deck_id)
    if not _peut_editer_deck(request.user, deck):
        return HttpResponseForbidden("Tu ne peux supprimer que les paquets que tu as créés.")
    if request.method == "POST":
        nom = deck.nom
        deck.delete()
        messages.success(request, f"Paquet « {nom} » supprimé.")
    return redirect("anki_review:edition")


def _creer_notes_depuis_formulaire(form, utilisateur):
    """
    Crée une ou deux Note à partir d'un formulaire NoteForm validé, selon
    le type de carte choisi (cf. NoteForm.CHOIX_TYPE_CARTE) :
    - normal : une seule note, telle quelle ;
    - double : la note telle quelle + son inverse (verso devient recto),
      vraiment liées entre elles (cf. Note.note_miroir/save).

    Renvoie la liste des Note créées (une ou deux).
    """
    type_carte = form.cleaned_data.get("type_carte") or NoteForm.TYPE_NORMAL
    deck = form.cleaned_data["deck"]
    question = form.cleaned_data["question"]
    reponse = form.cleaned_data["reponse"]
    tags = form.cleaned_data.get("tags", "")

    def _note(q, r):
        return Note.objects.create(
            guid=uuid.uuid4(), deck=deck, question=q, reponse=r,
            tags=tags, cree_par=utilisateur, partagee_avec_classe=False,
        )

    notes = [_note(question, reponse)]

    if type_carte == NoteForm.TYPE_DOUBLE:
        notes.append(_note(reponse, question))
        # Vrai lien entre les deux moitiés (cf. Note.note_miroir/save) :
        # modifier l'une répercutera automatiquement sur l'autre ensuite.
        notes[0].note_miroir = notes[1]
        notes[1].note_miroir = notes[0]
        notes[0].save()
        notes[1].save()

    return notes


def _creer_miroir_pour_note_existante(form, note):
    """
    Bascule Normal -> Double pendant la MODIFICATION d'une note déjà
    existante : enregistre la note avec le contenu tel que soumis dans le
    formulaire, crée sa carte miroir (inversée) et les lie (cf.
    Note.note_miroir/save).

    La carte miroir appartient au même propriétaire que `note` (pas
    forcément la personne qui modifie — le prof peut éditer la carte d'un
    étudiant) et reçoit sa propre Card pour ce même propriétaire.
    """
    deck = form.cleaned_data["deck"]
    question = form.cleaned_data["question"]
    reponse = form.cleaned_data["reponse"]
    tags = form.cleaned_data.get("tags", "")

    note.deck = deck
    note.question = question
    note.reponse = reponse
    note.tags = tags

    miroir = Note.objects.create(
        guid=uuid.uuid4(), deck=deck, question=reponse, reponse=question,
        tags=tags, cree_par=note.cree_par, partagee_avec_classe=note.partagee_avec_classe,
    )
    if note.cree_par_id:
        Card.objects.get_or_create(note=miroir, etudiant=note.cree_par)

    note.note_miroir = miroir
    miroir.note_miroir = note
    note.save()
    miroir.save()


@login_required
def ajouter_note(request):
    """
    Création d'une note — ouverte à tout utilisateur connecté (prof ou
    étudiant). Une carte créée par un étudiant est privée par défaut
    (partagee_avec_classe=False) et reçoit immédiatement sa propre Card,
    pour apparaître aussitôt dans sa révision. Selon le type de carte
    choisi, une ou deux notes sont créées (cf. _creer_notes_depuis_formulaire).
    """
    deck_prerempli = request.GET.get("deck")
    decks_visibles = _decks_visibles(request.user)

    if request.method == "POST":
        form = NoteForm(request.POST)
        form.fields["deck"].queryset = decks_visibles
        if form.is_valid():
            notes = _creer_notes_depuis_formulaire(form, request.user)
            for note in notes:
                Card.objects.get_or_create(note=note, etudiant=request.user)
            messages.success(request, f"{len(notes)} carte{'s' if len(notes) > 1 else ''} ajoutée{'s' if len(notes) > 1 else ''}.")
            # Retour sur le même formulaire, paquet pré-rempli, pour
            # enchaîner facilement l'ajout de plusieurs cartes de suite.
            url = reverse("anki_review:ajouter_note")
            return redirect(f"{url}?deck={notes[0].deck.slug}")
    else:
        initial = {}
        if deck_prerempli:
            deck = decks_visibles.filter(slug=deck_prerempli).first()
            if deck:
                initial["deck"] = deck.pk
        form = NoteForm(initial=initial)
        form.fields["deck"].queryset = decks_visibles

    return render(request, "anki_review/ajouter_note.html", {
        "form": form, "decks": decks_visibles, "media_notes_prefix": PREFIXE_IMAGES_NOTES,
        "retour_url": reverse("anki_review:edition"),
    })


@login_required
def modifier_note(request, note_id):
    """
    Modification d'une note.
    - Propriétaire (ou prof) : modification DIRECTE, comme avant.
    - Quelqu'un d'autre qui a cette carte dans sa révision : ce qu'il
      soumet devient une PropositionModification en attente, jamais
      appliqué à la note elle-même — c'est au propriétaire de l'accepter
      ou non (cf. voir_proposition).
    """
    note = get_object_or_404(Note, id=note_id)
    peut_direct = _peut_editer_directement(request.user, note)
    peut_proposer = _peut_proposer_modification(request.user, note)
    if not peut_direct and not peut_proposer:
        return HttpResponseForbidden("Tu n'as pas cette carte dans ta révision.")
    decks_visibles = _decks_visibles(request.user)

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note)
        form.fields["deck"].queryset = decks_visibles
        if peut_direct:
            if form.is_valid():
                ancien_miroir_id = note.note_miroir_id
                nouveau_type = form.cleaned_data.get("type_carte") or NoteForm.TYPE_NORMAL

                if nouveau_type == NoteForm.TYPE_NORMAL and ancien_miroir_id:
                    # Double -> Normal : supprime la carte liée (et sa
                    # progression de révision, cf. Card.note en CASCADE).
                    form.save()
                    Note.objects.filter(pk=ancien_miroir_id).delete()
                elif nouveau_type != NoteForm.TYPE_NORMAL and not ancien_miroir_id:
                    # Normal -> Double : crée la carte miroir à la volée.
                    _creer_miroir_pour_note_existante(form, note)
                else:
                    form.save()

                messages.success(request, "Carte mise à jour.")
                return redirect("anki_review:edition")
        else:
            # Pas propriétaire : seul le CONTENU (question/réponse/tags) est
            # retenu — le paquet et le type de carte restent ceux du
            # propriétaire, une proposition ne porte que sur le contenu.
            if form.is_valid():
                PropositionModification.objects.create(
                    note=note, auteur=request.user,
                    question=form.cleaned_data["question"],
                    reponse=form.cleaned_data["reponse"],
                    tags=form.cleaned_data.get("tags", ""),
                )
                messages.success(request, "Ta proposition de modification a été envoyée au propriétaire de la carte.")
                return redirect("anki_review:edition")
    else:
        if peut_direct:
            form = NoteForm(instance=note, initial={
                "type_carte": NoteForm.TYPE_DOUBLE if note.note_miroir_id else NoteForm.TYPE_NORMAL,
            })
        else:
            form = NoteForm(instance=note)
        form.fields["deck"].queryset = decks_visibles

    return render(
        request, "anki_review/ajouter_note.html",
        {"form": form, "decks": decks_visibles, "note": note, "media_notes_prefix": PREFIXE_IMAGES_NOTES,
         "retour_url": reverse("anki_review:edition"), "mode_proposition": not peut_direct},
    )


@login_required
def supprimer_note(request, note_id):
    """
    Retrait d'une note.
    - Le prof supprime réellement la note (pour tout le monde) — pouvoir de
      modération déjà établi, inchangé ici.
    - Pour tout le monde d'autre : ça ne retire QUE sa propre Card (la note
      disparaît juste de SA révision, pas de celle des autres). Si c'était
      le PROPRIÉTAIRE, la propriété passe au détenteur restant le plus
      ancien (cf. Card.cree_le) ; s'il ne reste plus personne, la note est
      alors vraiment supprimée (plus aucune Card dessus, elle ne sert plus
      à rien).
    Une carte réversible entraîne aussi la suppression de sa carte miroir
    quand la note elle-même disparaît (les deux forment une seule paire
    conceptuelle, cf. Note.note_miroir) — pas quand c'est un simple retrait
    de Card, qui laisse la note (et son miroir) intacts pour les autres.
    """
    note = get_object_or_404(Note, id=note_id)
    carte_utilisateur = Card.objects.filter(note=note, etudiant=request.user).first()
    if not request.user.is_staff and not carte_utilisateur:
        return HttpResponseForbidden("Tu n'as pas cette carte dans ta révision.")

    if request.method == "POST":
        if request.user.is_staff:
            miroir_id = note.note_miroir_id
            note.delete()
            if miroir_id:
                Note.objects.filter(pk=miroir_id).delete()
            messages.success(request, "Carte supprimée pour tout le monde.")
        else:
            etait_proprietaire = note.cree_par_id == request.user.id
            if carte_utilisateur:
                carte_utilisateur.delete()
            if etait_proprietaire:
                carte_suivante = Card.objects.filter(note=note).order_by("cree_le", "id").first()
                if carte_suivante:
                    note.cree_par = carte_suivante.etudiant
                    note.save(update_fields=["cree_par"])
                    messages.success(
                        request,
                        f"Carte retirée de ta révision. Comme tu en étais propriétaire, "
                        f"{carte_suivante.etudiant} en devient propriétaire.",
                    )
                else:
                    miroir_id = note.note_miroir_id
                    note.delete()
                    if miroir_id:
                        Note.objects.filter(pk=miroir_id).delete()
                    messages.success(request, "Carte retirée — plus personne ne l'avait, elle a été supprimée.")
            else:
                messages.success(request, "Carte retirée de ta révision.")
    return redirect("anki_review:edition")


@login_required
def uploader_image(request):
    """
    Reçoit une image (drag/drop ou sélection de fichier) depuis l'éditeur,
    la stocke sur disque (MEDIA_ROOT), et renvoie son URL en JSON pour que
    le JS l'insère dans le champ texte sous forme de balise <img>.

    Ouvert à tout utilisateur connecté (pas seulement is_staff) : les
    étudiants créent aussi leurs propres cartes personnelles, avec images.

    Volontairement séparé de la sauvegarde de la note : l'image est utile
    immédiatement pour la prévisualisation, avant même que le formulaire
    ne soit soumis.
    """
    if request.method != "POST" or "image" not in request.FILES:
        return JsonResponse({"erreur": "Aucune image reçue."}, status=400)

    fichier = request.FILES["image"]
    extension = "." + fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""

    if extension not in EXTENSIONS_IMAGE_AUTORISEES:
        return JsonResponse({"erreur": "Format d'image non autorisé."}, status=400)
    if fichier.size > TAILLE_IMAGE_MAX:
        return JsonResponse({"erreur": "Image trop volumineuse (5 Mo max)."}, status=400)

    nom_fichier = f"anki_review/notes/{uuid.uuid4().hex}{extension}"
    chemin_sauvegarde = default_storage.save(nom_fichier, fichier)
    return JsonResponse({"url": default_storage.url(chemin_sauvegarde)})


def _peut_editer_directement(user, note):
    """Modification DIRECTE (appliquée tout de suite à la note, visible par
    tout le monde) : réservée au propriétaire, ou au prof (droit de
    modération déjà établi). Sert aussi pour partager/départager une note."""
    return user.is_staff or note.cree_par_id == user.id


def _peut_proposer_modification(user, note):
    """Sinon, si la carte est dans sa révision (il l'a créée à l'origine ou
    récupérée ailleurs), il peut PROPOSER une correction — jamais modifier
    directement (cf. PropositionModification, à valider par le
    propriétaire)."""
    if _peut_editer_directement(user, note):
        return False
    return note.cards.filter(etudiant=user).exists()


def _peut_retirer_note(user, note):
    """Qui peut déclencher "supprimer" : le prof (suppression réelle, pour
    tout le monde — modération) ou quiconque a cette carte dans sa révision
    (simple retrait de SA carte, cf. supprimer_note pour le détail)."""
    return user.is_staff or note.cards.filter(etudiant=user).exists()


@login_required
def import_export_accueil(request):
    """Page d'accueil : deux façons d'importer/exporter des cartes — un
    fichier .apkg, ou un partage direct entre étudiants."""
    return render(request, "anki_review/import_export_accueil.html")


@login_required
def import_export_fichier(request):
    """Import/export via fichier .apkg (Anki) — page d'accueil : formulaire
    d'upload (mène à l'écran de sélection) + liste des paquets exportables
    (chacun dépliable pour choisir les cartes à exporter)."""
    erreur = None
    if request.method == "POST" and "fichier" in request.FILES:
        fichier = request.FILES["fichier"]
        chemin_temp = default_storage.save(f"anki_review/import_temp/{uuid.uuid4().hex}.apkg", fichier)
        try:
            paquets, nb_cloze = analyser_apkg(default_storage.open(chemin_temp))
        except ErreurImportApkg as e:
            default_storage.delete(chemin_temp)
            erreur = str(e)
        else:
            return render(request, "anki_review/import_apkg_selection.html", {
                "paquets": paquets, "nb_cloze": nb_cloze, "chemin_temp": chemin_temp,
            })

    decks_pour_export = {}
    for deck in _decks_visibles(request.user).order_by("nom"):
        if request.user.is_staff:
            notes = list(deck.notes.all())
        else:
            notes = list(deck.notes.filter(
                Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=request.user)
            ))
        if notes:
            decks_pour_export[deck] = notes

    return render(request, "anki_review/import_export_fichier.html", {
        "erreur": erreur, "decks_pour_export": decks_pour_export,
    })


@login_required
def import_apkg_confirmer(request):
    """Deuxième temps de l'import : ne retient que les notes cochées sur
    l'écran de sélection, puis nettoie le fichier temporaire."""
    if request.method != "POST":
        return redirect("anki_review:import_export_fichier")

    chemin_temp = request.POST.get("chemin_temp")
    guids = set(request.POST.getlist("notes"))
    resultat = None
    erreur = None

    if not chemin_temp or not default_storage.exists(chemin_temp):
        erreur = "Le fichier temporaire a expiré, réimporte-le."
    elif not guids:
        erreur = "Aucune carte cochée — rien à importer."
    else:
        try:
            resultat = importer_apkg(default_storage.open(chemin_temp), request.user, guids_selectionnes=guids)
        except ErreurImportApkg as e:
            erreur = str(e)
        finally:
            default_storage.delete(chemin_temp)

    decks_pour_export = {}
    for deck in _decks_visibles(request.user).order_by("nom"):
        if request.user.is_staff:
            notes = list(deck.notes.all())
        else:
            notes = list(deck.notes.filter(
                Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=request.user)
            ))
        if notes:
            decks_pour_export[deck] = notes

    return render(request, "anki_review/import_export_fichier.html", {
        "resultat": resultat, "erreur": erreur, "decks_pour_export": decks_pour_export,
    })


@login_required
def exporter_apkg_selection(request):
    """Génère et propose en téléchargement un .apkg contenant les notes
    cochées sur la page Import/Export — potentiellement réparties sur
    plusieurs paquets, chacun devenant son propre paquet dans le fichier."""
    if request.method != "POST":
        return redirect("anki_review:import_export_fichier")

    ids_notes = request.POST.getlist("notes")
    if not ids_notes:
        messages.error(request, "Sélectionne au moins une carte à exporter.")
        return redirect("anki_review:import_export_fichier")

    notes = Note.objects.filter(id__in=ids_notes).select_related("deck")
    if not request.user.is_staff:
        notes = notes.filter(Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=request.user))
    notes = list(notes)
    if not notes:
        messages.error(request, "Aucune des cartes sélectionnées n'est accessible.")
        return redirect("anki_review:import_export_fichier")

    contenu = exporter_notes_apkg(notes)
    reponse = HttpResponse(contenu, content_type="application/octet-stream")
    reponse["Content-Disposition"] = 'attachment; filename="export.apkg"'
    return reponse


@login_required
def partage_etudiants(request):
    """
    Page de partage entre étudiants, groupée par PAQUET (plutôt que carte
    par carte) pour permettre de tout partager / tout ajouter en une fois :
    - mes_paquets : mes propres paquets contenant des cartes personnelles,
      avec un bouton "tout partager"/"tout retirer"
    - groupes_partages : les cartes partagées par les autres, regroupées par
      (paquet source, partageur) — un même bouton "tout ajouter" pour
      chaque groupe, avec le voyant global du groupe.
    """
    mes_notes = Note.objects.filter(cree_par=request.user).select_related("deck").order_by("-modifie_le")

    mes_paquets = {}
    for note in mes_notes:
        groupe = mes_paquets.setdefault(note.deck_id, {"deck": note.deck, "notes": [], "toutes_partagees": True})
        groupe["notes"].append(note)
        if not note.partagee_avec_classe:
            groupe["toutes_partagees"] = False
    mes_paquets = sorted(mes_paquets.values(), key=lambda g: g["deck"].nom)

    mes_matieres_dict = {}
    mes_paquets_sans_matiere = []
    for groupe in mes_paquets:
        if groupe["deck"].matiere:
            mes_matieres_dict.setdefault(groupe["deck"].matiere, []).append(groupe)
        else:
            mes_paquets_sans_matiere.append(groupe)
    mes_matieres = [
        {"valeur": valeur, "libelle": dict(Deck.Matiere.choices).get(valeur, valeur), "paquets": paquets}
        for valeur, paquets in mes_matieres_dict.items()
    ]
    mes_matieres.sort(key=lambda m: m["libelle"])

    if mes_paquets_sans_matiere:
        mes_matieres.append({"valeur": VALEUR_SANS_MATIERE, "libelle": LIBELLE_SANS_MATIERE, "paquets": mes_paquets_sans_matiere})

    notes_partagees = (
        Note.objects.filter(partagee_avec_classe=True)
        .exclude(cree_par=request.user)
        .select_related("deck", "cree_par")
        .order_by("-modifie_le")
    )
    mes_cartes_ids = set(Card.objects.filter(etudiant=request.user).values_list("note_id", flat=True))

    groupes_partages = {}
    for note in notes_partagees:
        statut = "deja" if note.id in mes_cartes_ids else "absente"
        cle = (note.deck_id, note.cree_par_id)
        groupe = groupes_partages.setdefault(cle, {"deck": note.deck, "cree_par": note.cree_par, "notes": []})
        groupe["notes"].append({"note": note, "statut": statut})

    groupes_partages = list(groupes_partages.values())
    for groupe in groupes_partages:
        groupe["tout_deja"] = all(item["statut"] == "deja" for item in groupe["notes"])

    return render(request, "anki_review/partage_etudiants.html", {
        "mes_matieres": mes_matieres,
        "groupes_partages": groupes_partages,
    })


@login_required
def partager_paquet_toggle(request, deck_id):
    """Partage ou retire du partage TOUTES mes notes d'un paquet donné en
    une fois, plutôt que carte par carte."""
    if request.method == "POST":
        mes_notes = Note.objects.filter(deck_id=deck_id, cree_par=request.user)
        tout_deja_partage = not mes_notes.filter(partagee_avec_classe=False).exists()
        mes_notes.update(partagee_avec_classe=not tout_deja_partage)
    return redirect("anki_review:partage_etudiants")


@login_required
def supprimer_mes_cartes_paquet(request, deck_id):
    """Retire en bloc toutes MES cartes de ce paquet (celles que j'ai dans
    ma révision, que j'en sois propriétaire ou non) — même logique que
    supprimer_note, répétée pour chacune : pour celles dont j'étais
    propriétaire, la propriété passe au détenteur restant le plus ancien
    (ou la note est supprimée si plus personne ne l'a) ; pour les autres,
    ça ne retire que ma Card, sans toucher à la note."""
    if request.method == "POST":
        mes_cartes = list(Card.objects.filter(note__deck_id=deck_id, etudiant=request.user).select_related("note"))
        nb = len(mes_cartes)
        for carte in mes_cartes:
            note = carte.note
            etait_proprietaire = note.cree_par_id == request.user.id
            carte.delete()
            if etait_proprietaire:
                carte_suivante = Card.objects.filter(note=note).order_by("cree_le", "id").first()
                if carte_suivante:
                    note.cree_par = carte_suivante.etudiant
                    note.save(update_fields=["cree_par"])
                else:
                    miroir_id = note.note_miroir_id
                    note.delete()
                    if miroir_id:
                        Note.objects.filter(pk=miroir_id).delete()
        messages.success(request, f"{nb} carte{'s' if nb > 1 else ''} retirée{'s' if nb > 1 else ''} de ta révision.")
    return redirect("anki_review:partage_etudiants")


@login_required
def partager_note_toggle(request, note_id):
    """Bascule le statut partagé/privé d'une note — action explicite et
    réversible, jamais automatique."""
    note = get_object_or_404(Note, id=note_id)
    if not _peut_editer_directement(request.user, note):
        return HttpResponseForbidden("Tu ne peux partager que tes propres cartes.")
    if request.method == "POST":
        note.partagee_avec_classe = not note.partagee_avec_classe
        note.save(update_fields=["partagee_avec_classe"])
    return redirect("anki_review:partage_etudiants")


@login_required
def ajouter_carte_partagee(request, note_id):
    """
    "Ajouter" une carte partagée : depuis qu'une note n'est plus dupliquée,
    ça ne fait plus que créer une Card pour soi sur la note EXISTANTE — pas
    de copie, pas de paquet à choisir (elle reste dans son paquet
    d'origine, devenu visible via _decks_visibles dès qu'elle est partagée).
    """
    if request.method != "POST":
        return redirect("anki_review:partage_etudiants")
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")

    note = get_object_or_404(Note, id=note_id, partagee_avec_classe=True)
    _, cree = Card.objects.get_or_create(note=note, etudiant=request.user)
    messages.success(request, "Carte ajoutée à ta révision." if cree else "Tu avais déjà cette carte.")
    return redirect("anki_review:partage_etudiants")


@login_required
def ajouter_paquet_partage(request, deck_id, cree_par_id):
    """Ajoute EN BLOC toutes les cartes qu'un même étudiant a partagées
    depuis un paquet donné — une Card par note, sans rien dupliquer."""
    if request.method != "POST":
        return redirect("anki_review:partage_etudiants")
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")
    notes = Note.objects.filter(deck_id=deck_id, cree_par_id=cree_par_id, partagee_avec_classe=True)
    deck_source = get_object_or_404(Deck, id=deck_id)
    nb_ajoutees = 0
    for note in notes:
        _, cree = Card.objects.get_or_create(note=note, etudiant=request.user)
        if cree:
            nb_ajoutees += 1
    messages.success(
        request,
        f"Paquet « {deck_source.nom} » ajouté ({nb_ajoutees} nouvelle{'s' if nb_ajoutees > 1 else ''} "
        f"carte{'s' if nb_ajoutees > 1 else ''}).",
    )
    return redirect("anki_review:partage_etudiants")


@login_required
def voir_proposition(request, proposition_id):
    """Écran de validation d'une proposition de modification : montre les
    deux versions (actuelle / proposée) côte à côte, pour que le
    propriétaire (ou le prof) accepte ou refuse en connaissance de cause."""
    proposition = get_object_or_404(
        PropositionModification.objects.select_related("note", "note__cree_par", "auteur"),
        id=proposition_id,
    )
    if not (request.user.is_staff or proposition.note.cree_par_id == request.user.id):
        return HttpResponseForbidden("Seul le propriétaire de la carte (ou le prof) peut traiter cette proposition.")
    return render(request, "anki_review/voir_proposition.html", {"proposition": proposition})


@login_required
def accepter_proposition(request, proposition_id):
    """Applique le contenu proposé à la note elle-même — visible aussitôt
    par tout le monde qui l'a dans sa révision."""
    proposition = get_object_or_404(PropositionModification.objects.select_related("note"), id=proposition_id)
    if not (request.user.is_staff or proposition.note.cree_par_id == request.user.id):
        return HttpResponseForbidden("Seul le propriétaire de la carte (ou le prof) peut traiter cette proposition.")
    if request.method == "POST":
        note = proposition.note
        note.question = proposition.question
        note.reponse = proposition.reponse
        note.tags = proposition.tags
        note.save()
        proposition.statut = PropositionModification.Statut.ACCEPTEE
        proposition.traitee_le = timezone.now()
        proposition.save(update_fields=["statut", "traitee_le"])
        messages.success(request, "Proposition acceptée — la carte est mise à jour pour tout le monde.")
    return redirect("anki_review:edition")


@login_required
def refuser_proposition(request, proposition_id):
    proposition = get_object_or_404(PropositionModification.objects.select_related("note"), id=proposition_id)
    if not (request.user.is_staff or proposition.note.cree_par_id == request.user.id):
        return HttpResponseForbidden("Seul le propriétaire de la carte (ou le prof) peut traiter cette proposition.")
    if request.method == "POST":
        proposition.statut = PropositionModification.Statut.REFUSEE
        proposition.traitee_le = timezone.now()
        proposition.save(update_fields=["statut", "traitee_le"])
        messages.success(request, "Proposition refusée.")
    return redirect("anki_review:edition")
