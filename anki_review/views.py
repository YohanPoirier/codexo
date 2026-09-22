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
from .models import Card, Deck, Note
from .sm2 import Reponse, appliquer
from .apkg_import import importer_apkg, analyser_apkg, ErreurImportApkg
from .apkg_export import exporter_notes_apkg

EXTENSIONS_IMAGE_AUTORISEES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Pseudo-matière pour les paquets sans matière assignée — affichés avec la
# même bande que les vraies matières plutôt qu'à part, pour la cohérence
# visuelle (Édition, Révision, Import/Export utilisent tous cette valeur).
VALEUR_SANS_MATIERE = "sans-matiere"
LIBELLE_SANS_MATIERE = "Sans matière"

# "Double vocabulaire" : l'étiquette du verso s'adapte à la matière du
# paquet choisi ; à défaut de correspondance (paquet d'une autre matière,
# ou sans matière), on retombe sur le générique "Étranger".
LIBELLES_LANGUE_ETRANGERE = {
    Deck.Matiere.ANGLAIS: "Anglais",
    Deck.Matiere.ESPAGNOL: "Espagnol",
    Deck.Matiere.ALLEMAND: "Allemand",
}
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
    créateur ou créé par un membre du staff) + les siens propres. Un paquet
    créé par un AUTRE étudiant reste invisible — pas de notion de partage de
    paquet pour l'instant (contrairement aux notes)."""
    if user.is_staff:
        return Deck.objects.all()
    return Deck.objects.filter(Q(cree_par__isnull=True) | Q(cree_par__is_staff=True) | Q(cree_par=user))


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


def _traiter_revision(request, decks_qs, titre, nom_url_action, args_url_action):
    """
    Logique commune à l'écran de révision, qu'il porte sur UN paquet ou sur
    TOUS les paquets d'une même matière à la fois (cf. reviser et
    reviser_matiere) — seule `decks_qs` change entre les deux cas.
    """
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
        return redirect(reverse(nom_url_action, args=args_url_action))

    carte, file = _prochaine_carte(request, decks_qs, request.user)
    _ecrire_file_apprentissage(request, file)

    if carte is None:
        return render(request, "anki_review/session_terminee.html", {"titre_paquet": titre})

    ids_apprentissage = [e["id"] for e in file]
    nb_apprentissage_scope = Card.objects.filter(id__in=ids_apprentissage, note__deck__in=decks_qs).count()
    restantes = Card.objects.filter(
        note__deck__in=decks_qs, etudiant=request.user, suspendue=False,
        prochaine_revision__lte=timezone.now(),
    ).count() + nb_apprentissage_scope

    return render(
        request, "anki_review/reviser.html",
        {"titre_paquet": titre, "carte": carte, "note": carte.note, "restantes": restantes},
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

    Pour un étudiant, la liste des cartes de chaque paquet se limite
    TOUJOURS aux siennes : sans diffusion automatique, une carte du prof
    qu'il n'a pas encore récupérée (via Import/Export) n'a aucune raison de
    lui être montrée ici — Édition est son espace personnel, la découverte
    du contenu à récupérer se fait sur la page de partage. Le filtre
    (?mes=1) n'a donc de sens que pour le prof, qui voit tout par défaut.
    """
    filtre_mes = True if not request.user.is_staff else request.GET.get("mes") == "1"

    decks = _decks_visibles(request.user).order_by("nom")
    par_matiere = {}
    paquets_sans_matiere = []
    for deck in decks:
        if filtre_mes:
            notes = list(deck.notes.select_related("cree_par").filter(cree_par=request.user).order_by("id"))
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
        "matieres": matieres, "filtre_mes": filtre_mes,
    })


@login_required
def edition_deck(request, deck_slug):
    """
    Liste des cartes d'un paquet précis. La visibilité du PAQUET lui-même
    suit _decks_visibles (404 si ce paquet privé appartient à un autre
    étudiant) ; les NOTES à l'intérieur se limitent aux siennes pour un
    étudiant (Édition = espace personnel, la découverte se fait via
    Import/Export), tout est visible pour le prof.
    """
    deck = get_object_or_404(_decks_visibles(request.user), slug=deck_slug)
    if request.user.is_staff:
        notes = deck.notes.select_related("cree_par").order_by("id")
    else:
        notes = deck.notes.select_related("cree_par").filter(cree_par=request.user).order_by("id")
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


def _etiquette(texte):
    return f'<p><strong>{texte}</strong></p>'


def _etiquettes_pour_type(type_carte, deck):
    """Renvoie (etiquette_recto, etiquette_verso), ou (None, None) si ce
    type ne prévoit pas d'étiquette automatique (normal ou double simple)."""
    if type_carte == NoteForm.TYPE_DOUBLE_DEFINITION:
        return "Terme", "Définition"
    if type_carte == NoteForm.TYPE_DOUBLE_VOCABULAIRE:
        return "Français", LIBELLES_LANGUE_ETRANGERE.get(deck.matiere, "Étranger")
    return None, None


def _creer_notes_depuis_formulaire(form, utilisateur):
    """
    Crée une ou deux Note à partir d'un formulaire NoteForm validé, selon
    le type de carte choisi (cf. NoteForm.CHOIX_TYPE_CARTE) :
    - normal : une seule note, telle quelle ;
    - double : la note telle quelle + son inverse (verso devient recto) ;
    - double_definition / double_vocabulaire : pareil, avec une étiquette
      ajoutée en tête de chaque champ ("Terme"/"Définition",
      "Français"/langue étrangère selon la matière du paquet).

    Renvoie la liste des Note créées (une ou deux).
    """
    type_carte = form.cleaned_data.get("type_carte") or NoteForm.TYPE_NORMAL
    deck = form.cleaned_data["deck"]
    question = form.cleaned_data["question"]
    reponse = form.cleaned_data["reponse"]
    titre = form.cleaned_data.get("titre", "")
    tags = form.cleaned_data.get("tags", "")

    etiquette_recto, etiquette_verso = _etiquettes_pour_type(type_carte, deck)

    def _note(q, r, t):
        return Note.objects.create(
            guid=uuid.uuid4(), deck=deck, titre=t, question=q, reponse=r,
            tags=tags, cree_par=utilisateur, partagee_avec_classe=False,
        )

    if etiquette_recto:
        question_finale = _etiquette(etiquette_recto) + question
        reponse_finale = _etiquette(etiquette_verso) + reponse
    else:
        question_finale, reponse_finale = question, reponse

    notes = [_note(question_finale, reponse_finale, titre)]

    if type_carte in (NoteForm.TYPE_DOUBLE, NoteForm.TYPE_DOUBLE_DEFINITION, NoteForm.TYPE_DOUBLE_VOCABULAIRE):
        if etiquette_recto:
            question_inverse = _etiquette(etiquette_verso) + reponse
            reponse_inverse = _etiquette(etiquette_recto) + question
        else:
            question_inverse, reponse_inverse = reponse, question
        notes.append(_note(question_inverse, reponse_inverse, titre))

        # Vrai lien entre les deux moitiés (cf. Note.note_miroir/save) :
        # modifier l'une répercutera automatiquement sur l'autre ensuite.
        notes[0].note_miroir = notes[1]
        notes[1].note_miroir = notes[0]
        notes[0].save()
        notes[1].save()

    return notes


def _creer_miroir_pour_note_existante(form, note):
    """
    Bascule Normal -> Double(...) pendant la MODIFICATION d'une note déjà
    existante : applique les étiquettes éventuelles au contenu tel que
    soumis dans le formulaire, enregistre la note avec ce contenu, crée sa
    carte miroir (inversée) et les lie (cf. Note.note_miroir/save).

    La carte miroir appartient au même propriétaire que `note` (pas
    forcément la personne qui modifie — le prof peut éditer la carte d'un
    étudiant) et reçoit sa propre Card pour ce même propriétaire.
    """
    type_carte = form.cleaned_data.get("type_carte")
    deck = form.cleaned_data["deck"]
    question = form.cleaned_data["question"]
    reponse = form.cleaned_data["reponse"]
    titre = form.cleaned_data.get("titre", "")
    tags = form.cleaned_data.get("tags", "")

    etiquette_recto, etiquette_verso = _etiquettes_pour_type(type_carte, deck)

    if etiquette_recto:
        question_finale = _etiquette(etiquette_recto) + question
        reponse_finale = _etiquette(etiquette_verso) + reponse
        question_inverse = _etiquette(etiquette_verso) + reponse
        reponse_inverse = _etiquette(etiquette_recto) + question
    else:
        question_finale, reponse_finale = question, reponse
        question_inverse, reponse_inverse = reponse, question

    note.deck = deck
    note.titre = titre
    note.question = question_finale
    note.reponse = reponse_finale
    note.tags = tags

    miroir = Note.objects.create(
        guid=uuid.uuid4(), deck=deck, titre=titre, question=question_inverse, reponse=reponse_inverse,
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
    note = get_object_or_404(Note, id=note_id)
    if not _peut_editer_note(request.user, note):
        return HttpResponseForbidden("Tu ne peux modifier que tes propres cartes.")
    decks_visibles = _decks_visibles(request.user)

    CHOIX_EDITION = [c for c in NoteForm.CHOIX_TYPE_CARTE if c[0] in (NoteForm.TYPE_NORMAL, NoteForm.TYPE_DOUBLE)]

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note)
        form.fields["deck"].queryset = decks_visibles
        # Toujours les deux mêmes choix en modification (jamais "définition"
        # /"vocabulaire" ici) — pour un comportement prévisible plutôt que
        # de faire varier les options selon le contenu déjà présent.
        form.fields["type_carte"].choices = CHOIX_EDITION
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
        form = NoteForm(instance=note, initial={
            "type_carte": NoteForm.TYPE_DOUBLE if note.note_miroir_id else NoteForm.TYPE_NORMAL,
        })
        form.fields["deck"].queryset = decks_visibles
        form.fields["type_carte"].choices = CHOIX_EDITION

    return render(
        request, "anki_review/ajouter_note.html",
        {"form": form, "decks": decks_visibles, "note": note, "media_notes_prefix": PREFIXE_IMAGES_NOTES,
         "retour_url": reverse("anki_review:edition")},
    )


@login_required
def supprimer_note(request, note_id):
    """Suppression d'une note — POST uniquement, avec confirmation JS.
    Une carte réversible entraîne aussi la suppression de sa carte miroir
    (les deux forment une seule paire conceptuelle, cf. Note.note_miroir)."""
    note = get_object_or_404(Note, id=note_id)
    if not _peut_supprimer_note(request.user, note):
        return HttpResponseForbidden("Seul le créateur de la carte peut la supprimer.")
    if request.method == "POST":
        miroir_id = note.note_miroir_id
        note.delete()
        if miroir_id:
            Note.objects.filter(pk=miroir_id).delete()
            messages.success(request, "Les 2 cartes liées ont été supprimées.")
        else:
            messages.success(request, "Carte supprimée.")
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


def _peut_editer_note(user, note):
    """Le prof peut tout MODIFIER (corriger une erreur, y compris sur une
    carte d'étudiant) ; un étudiant ne peut modifier que ses propres notes.
    Sert aussi pour le droit de partager/départager une note."""
    return user.is_staff or note.cree_par_id == user.id


def _peut_supprimer_note(user, note):
    """La SUPPRESSION, elle, est réservée au propriétaire de la note — sans
    exception pour le prof : aucune raison qu'il supprime la carte d'un
    étudiant, et ça évite un clic malheureux en parcourant les paquets de
    la classe."""
    return note.cree_par_id == user.id


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
    mes_decks_ids = set(_decks_visibles(request.user).values_list("id", flat=True))

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
    mes_notes_par_guid = {n.guid: n for n in mes_notes}

    groupes_partages = {}
    for note in notes_partagees:
        ma_version = mes_notes_par_guid.get(note.guid)
        if ma_version is None:
            statut = "absente"
        elif (ma_version.question, ma_version.reponse, ma_version.tags) == (note.question, note.reponse, note.tags):
            statut = "identique"
        else:
            statut = "differente"

        cle = (note.deck_id, note.cree_par_id)
        groupe = groupes_partages.setdefault(cle, {
            "deck": note.deck, "cree_par": note.cree_par, "notes": [],
            "besoin_choix_paquet": note.deck_id not in mes_decks_ids,
        })
        groupe["notes"].append({"note": note, "statut": statut})

    groupes_partages = list(groupes_partages.values())
    for groupe in groupes_partages:
        statuts = {item["statut"] for item in groupe["notes"]}
        groupe["tout_identique"] = statuts == {"identique"}

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
    """Supprime en bloc TOUTES mes notes dans ce paquet, sans toucher au
    paquet lui-même ni aux notes des autres — utile pour "rendre" un paquet
    récupéré (téléchargé, importé) sans avoir à supprimer carte par carte,
    alors qu'on n'a pas le droit de supprimer le paquet en tant que tel."""
    if request.method == "POST":
        mes_notes = Note.objects.filter(deck_id=deck_id, cree_par=request.user)
        nb = mes_notes.count()
        mes_notes.delete()
        messages.success(request, f"{nb} carte{'s' if nb > 1 else ''} supprimée{'s' if nb > 1 else ''}.")
    return redirect("anki_review:partage_etudiants")


@login_required
def partager_note_toggle(request, note_id):
    """Bascule le statut partagé/privé d'une note — action explicite et
    réversible, jamais automatique."""
    note = get_object_or_404(Note, id=note_id)
    if not _peut_editer_note(request.user, note):
        return HttpResponseForbidden("Tu ne peux partager que tes propres cartes.")
    if request.method == "POST":
        note.partagee_avec_classe = not note.partagee_avec_classe
        note.save(update_fields=["partagee_avec_classe"])
    return redirect("anki_review:partage_etudiants")


def _copier_ou_mettre_a_jour_carte_partagee(user, note_source, deck_pour_creation):
    """
    Logique commune d'ajout d'une carte partagée, que le paquet cible ait dû
    être choisi explicitement ou non.

    Si l'utilisateur a déjà une copie (même guid) : seul le CONTENU est mis
    à jour (question/réponse/tags) — surtout pas le paquet, qui reste celui
    que l'utilisateur avait lui-même choisi pour organiser sa révision.
    Sinon : nouvelle copie indépendante, placée dans `deck_pour_creation`.
    """
    ma_version = Note.objects.filter(guid=note_source.guid, cree_par=user).first()
    if ma_version:
        ma_version.question = note_source.question
        ma_version.reponse = note_source.reponse
        ma_version.tags = note_source.tags
        ma_version.save()
        return "mise_a_jour"

    copie = Note.objects.create(
        guid=note_source.guid,
        deck=deck_pour_creation,
        question=note_source.question,
        reponse=note_source.reponse,
        tags=note_source.tags,
        cree_par=user,
        partagee_avec_classe=False,
    )
    Card.objects.get_or_create(note=copie, etudiant=user)
    return "cree"


@login_required
def ajouter_carte_partagee(request, note_id):
    """
    "Ajouter" une carte partagée, dans le cas simple où son paquet d'origine
    m'est déjà visible (paquet du prof, ou l'un de mes propres paquets) —
    pas besoin de demander où la ranger. Sinon, voir
    choisir_paquet_carte_partagee.
    """
    if request.method != "POST":
        return redirect("anki_review:partage_etudiants")
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")

    note_source = get_object_or_404(Note, id=note_id, partagee_avec_classe=True)
    resultat = _copier_ou_mettre_a_jour_carte_partagee(request.user, note_source, note_source.deck)

    if resultat == "mise_a_jour":
        messages.success(request, "Ta copie a été mise à jour avec la dernière version.")
    else:
        messages.success(request, "Carte ajoutée à ton paquet.")
    return redirect("anki_review:partage_etudiants")


@login_required
def choisir_paquet_carte_partagee(request, note_id):
    """
    Étape intermédiaire quand le paquet d'origine d'une carte partagée ne
    m'est PAS visible (cas courant : le partageur l'a rangée dans un de ses
    paquets privés). Je choisis où l'accueillir : créer un nouveau paquet
    (pré-rempli avec le nom du paquet d'origine, modifiable), ou l'ajouter
    dans l'un de mes paquets existants.
    """
    note_source = get_object_or_404(Note, id=note_id, partagee_avec_classe=True)
    decks_visibles = _decks_visibles(request.user)
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")

    if request.method == "POST":
        deck_cible = _traiter_choix_paquet(request, decks_visibles)
        if deck_cible is None:
            return redirect("anki_review:choisir_paquet_carte_partagee", note_id=note_id)
        _copier_ou_mettre_a_jour_carte_partagee(request.user, note_source, deck_cible)
        messages.success(request, "Carte ajoutée à ton paquet.")
        return redirect("anki_review:partage_etudiants")

    return render(request, "anki_review/choisir_paquet_partage.html", {
        "nom_paquet_source": note_source.deck.nom,
        "description_source": f"la carte « {note_source.titre_affichage[:60]} »",
        "decks_visibles": decks_visibles,
    })


def _traiter_choix_paquet(request, decks_visibles):
    """Factorise la partie commune aux deux écrans de choix (carte seule ou
    paquet entier) : lit le choix posté et renvoie le Deck cible, ou None
    si invalide (un message d'erreur est alors déjà déposé)."""
    if request.POST.get("choix") == "nouveau":
        nom_paquet = request.POST.get("nouveau_paquet_nom", "").strip()
        deck_form = DeckForm({"nom": nom_paquet, "description": ""})
        if not nom_paquet or not deck_form.is_valid():
            messages.error(request, "Merci d'indiquer un nom de paquet valide.")
            return None
        deck_cible = deck_form.save(commit=False)
        deck_cible.cree_par = request.user
        deck_cible.save()
        return deck_cible

    deck_cible = decks_visibles.filter(id=request.POST.get("deck_existant")).first()
    if not deck_cible:
        messages.error(request, "Choisis un paquet valide.")
        return None
    return deck_cible


@login_required
def ajouter_paquet_partage(request, deck_id, cree_par_id):
    """Ajoute/met à jour EN BLOC toutes les cartes qu'un même étudiant a
    partagées depuis un paquet donné — cas où ce paquet m'est déjà visible
    (sinon voir choisir_paquet_paquet_partage)."""
    if request.method != "POST":
        return redirect("anki_review:partage_etudiants")
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")
    notes = Note.objects.filter(deck_id=deck_id, cree_par_id=cree_par_id, partagee_avec_classe=True)
    deck_source = get_object_or_404(Deck, id=deck_id)
    for note in notes:
        _copier_ou_mettre_a_jour_carte_partagee(request.user, note, deck_source)
    messages.success(request, f"Paquet « {deck_source.nom} » ajouté ({notes.count()} carte{'s' if notes.count() > 1 else ''}).")
    return redirect("anki_review:partage_etudiants")


@login_required
def choisir_paquet_paquet_partage(request, deck_id, cree_par_id):
    """Même principe que choisir_paquet_carte_partagee, mais pour tout un
    lot de cartes d'un coup : un seul choix de paquet d'accueil, appliqué à
    chacune."""
    notes = list(Note.objects.filter(deck_id=deck_id, cree_par_id=cree_par_id, partagee_avec_classe=True))
    if not notes:
        return redirect("anki_review:partage_etudiants")
    if request.user.is_staff:
        return HttpResponseForbidden("Réservé aux étudiants — le prof ne récupère pas de cartes ici.")
    deck_source = notes[0].deck
    decks_visibles = _decks_visibles(request.user)

    if request.method == "POST":
        deck_cible = _traiter_choix_paquet(request, decks_visibles)
        if deck_cible is None:
            return redirect("anki_review:choisir_paquet_paquet_partage", deck_id=deck_id, cree_par_id=cree_par_id)
        for note in notes:
            _copier_ou_mettre_a_jour_carte_partagee(request.user, note, deck_cible)
        messages.success(request, f"Paquet « {deck_source.nom} » ajouté ({len(notes)} carte{'s' if len(notes) > 1 else ''}).")
        return redirect("anki_review:partage_etudiants")

    return render(request, "anki_review/choisir_paquet_partage.html", {
        "nom_paquet_source": deck_source.nom,
        "description_source": f"les {len(notes)} carte{'s' if len(notes) > 1 else ''} du paquet « {deck_source.nom} »",
        "decks_visibles": decks_visibles,
    })
