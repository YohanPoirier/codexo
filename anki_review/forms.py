from django import forms

from .html_propre import nettoyer_html
from .models import Deck, Note
from .slugs import slug_unique


class DeckForm(forms.ModelForm):
    class Meta:
        model = Deck
        fields = ["nom", "description", "matiere", "partie"]
        widgets = {
            "nom": forms.TextInput(),
            "partie": forms.TextInput(attrs={"list": "parties-existantes", "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "matiere": forms.Select(attrs={"class": "select-stylise"}),
        }

    def clean_partie(self):
        # Une partie sert d'adresse (« /partie/<nom>/ ») et de segment de nom Anki (« :: ») :
        # on interdit « / » et « :: », qui casseraient l'un ou l'autre.
        partie = " ".join((self.cleaned_data.get("partie") or "").split())
        if "/" in partie or "::" in partie:
            raise forms.ValidationError("La partie ne peut contenir ni « / » ni « :: ».")
        return partie

    def clean(self):
        donnees = super().clean()
        if donnees.get("partie") and not donnees.get("matiere"):
            self.add_error("partie", "Choisis d'abord une matière pour pouvoir indiquer une partie.")
        return donnees

    def save(self, commit=True):
        deck = super().save(commit=False)
        if not deck.slug:
            deck.slug = slug_unique(deck.nom, exclure_pk=deck.pk)
        if commit:
            deck.save()
        return deck


class NoteForm(forms.ModelForm):
    TYPE_NORMAL = "normal"
    TYPE_DOUBLE = "double"
    CHOIX_TYPE_CARTE = [
        (TYPE_NORMAL, "Normal"),
        (TYPE_DOUBLE, "Double (recto-verso et verso-recto)"),
    ]

    # Champ non lié au modèle : influence UNIQUEMENT la création (une ou
    # deux notes générées) — jamais sauvegardé sur la Note elle-même, donc
    # sans effet à la modification au-delà du choix Normal/Double lui-même.
    type_carte = forms.ChoiceField(choices=CHOIX_TYPE_CARTE, initial=TYPE_NORMAL, required=False)

    # Le paquet n'est pas un champ de la Note : c'est le paquet À MOI dans lequel je range cette
    # carte (la vue le restreint à mes paquets et décide quoi mettre à jour).
    deck = forms.ModelChoiceField(queryset=Deck.objects.none(), empty_label="— Choisir —")
    field_order = ["deck", "type_carte", "question", "reponse", "tags"]

    class Meta:
        model = Note
        fields = ["question", "reponse", "tags"]
        widgets = {
            "question": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "reponse": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "tags": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # L'éditeur place le contenu des champs dans la page en HTML brut (innerHTML) : on lui
        # donne la version nettoyée, même pour une carte enregistrée avant le nettoyage.
        if self.instance.pk:
            self.initial["question"] = nettoyer_html(self.instance.question)
            self.initial["reponse"] = nettoyer_html(self.instance.reponse)
