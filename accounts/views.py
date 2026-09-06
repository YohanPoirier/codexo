import io

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy

from .forms import ConnexionThrottleeForm, DemandeReinitialisationForm, ImporterElevesForm
from .importation import ColonnesManquantes, importer_eleves_depuis_lignes
from .models import DemandeReinitialisation, User


class IdentifiantLoginView(LoginView):
    """Anciennement EmailLoginView : renommée suite au passage de l'email à
    l'identifiant comme USERNAME_FIELD (voir contexte-technique.md, refonte du
    06/09/2026). Redirige vers le changement de mot de passe si le compte doit
    encore changer son mot de passe provisoire (import CSV).

    form_class = ConnexionThrottleeForm (accounts/forms.py) : bloque
    temporairement un identifiant après plusieurs échecs de connexion, pour
    limiter le brute-force sur les mots de passe provisoires (date de
    naissance)."""

    template_name = "accounts/login.html"
    form_class = ConnexionThrottleeForm

    def get_success_url(self):
        if self.request.user.doit_changer_mot_de_passe:
            return str(reverse_lazy("changer_mot_de_passe"))
        return super().get_success_url()


class ChangerMotDePasseView(PasswordChangeView):
    """Formulaire de changement de mot de passe. Sert à la fois pour un changement
    volontaire et pour le changement FORCÉ après un import CSV (mot de passe
    provisoire = date de naissance) : dans ce cas,
    ForcerChangementMotDePasseMiddleware (accounts/middleware.py) redirige
    systématiquement ici tant que doit_changer_mot_de_passe reste True."""

    template_name = "accounts/changer_mot_de_passe.html"
    success_url = reverse_lazy("theme_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.doit_changer_mot_de_passe:
            self.request.user.doit_changer_mot_de_passe = False
            self.request.user.save(update_fields=["doit_changer_mot_de_passe"])
        messages.success(self.request, "Mot de passe changé avec succès.")
        return response


def demande_mot_de_passe_oublie(request):
    """Formulaire public : un élève qui a perdu son mot de passe indique son
    identifiant et une adresse email de contact. Aucune vérification n'est faite ici
    (voir DemandeReinitialisation) — c'est un prof qui traite ça à la main, voir
    demandes_reinitialisation ci-dessous."""
    if request.method == "POST":
        form = DemandeReinitialisationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("mot_de_passe_oublie_envoye")
    else:
        form = DemandeReinitialisationForm()
    return render(request, "accounts/mot_de_passe_oublie.html", {"form": form})


def mot_de_passe_oublie_envoye(request):
    return render(request, "accounts/mot_de_passe_oublie_envoye.html")


@staff_member_required
def demandes_reinitialisation(request):
    """Page réservée aux profs (voir base.html) : liste des demandes de
    réinitialisation en attente, avec un lien direct vers la fiche admin de l'élève
    concerné (si un compte correspondant à l'identifiant saisi existe) pour
    réinitialiser le mot de passe à la main, et un bouton pour marquer la demande
    comme traitée. Le prof envoie ensuite lui-même le nouveau mot de passe à l'email
    de contact indiqué, depuis sa propre boîte mail — l'application n'envoie
    elle-même aucun email."""
    if request.method == "POST":
        demande_id = request.POST.get("demande_id")
        demande = get_object_or_404(DemandeReinitialisation, id=demande_id)
        demande.marquer_traitee()
        messages.success(request, "Demande marquée comme traitée.")
        return redirect("demandes_reinitialisation")

    demandes = DemandeReinitialisation.objects.all()
    # Pour chaque demande, on essaie de retrouver le compte correspondant (par
    # identifiant) afin de proposer un lien direct vers sa fiche admin — ça peut ne
    # rien donner si l'élève s'est trompé en le saisissant, le prof devra alors
    # vérifier à la main.
    comptes_par_identifiant = {
        u.identifiant: u.id
        for u in User.objects.filter(
            identifiant__in=[d.identifiant_saisi for d in demandes]
        )
    }
    lignes = [
        {"demande": d, "user_id": comptes_par_identifiant.get(d.identifiant_saisi)}
        for d in demandes
    ]
    return render(request, "accounts/demandes_reinitialisation.html", {"lignes": lignes})


@staff_member_required
def importer_eleves_view(request):
    """Formulaire web d'import CSV élèves, réservé aux profs (voir base.html, menu
    déroulant "Espace prof"). Équivalent web de la commande de gestion
    "importer_eleves" (voir LISEZ_MOI.md pour l'usage en ligne de commande) : les
    deux réutilisent exactement la même logique d'import
    (accounts/importation.py), donc le résultat est identique quelle que soit la
    façon dont le CSV est importé."""
    resultat = None
    if request.method == "POST":
        form = ImporterElevesForm(request.POST, request.FILES)
        if form.is_valid():
            fichier = form.cleaned_data["fichier"]
            delimiter = form.cleaned_data["delimiter"]
            # encoding="utf-8-sig" : tolère le BOM ajouté par Excel en tête de
            # fichier (même remarque que dans la commande en ligne de commande).
            contenu = fichier.read().decode("utf-8-sig")
            try:
                crees, mis_a_jour, erreurs = importer_eleves_depuis_lignes(
                    io.StringIO(contenu), delimiter=delimiter
                )
                resultat = {"crees": crees, "mis_a_jour": mis_a_jour, "erreurs": erreurs}
                messages.success(
                    request,
                    f"Import terminé : {crees} compte(s) créé(s), {mis_a_jour} mis à jour.",
                )
            except ColonnesManquantes as exc:
                form.add_error("fichier", str(exc))
    else:
        form = ImporterElevesForm()
    return render(request, "accounts/importer_eleves.html", {"form": form, "resultat": resultat})
