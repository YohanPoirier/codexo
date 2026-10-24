from django import forms

from .models import Deck, Note
from .slugs import slug_unique


class DeckForm(forms.ModelForm):
    class Meta:
        model = Deck
        fields = ["nom", "description", "matiere"]
        widgets = {
            "nom": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "matiere": forms.Select(attrs={"class": "select-stylise"}),
        }

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

    class Meta:
        model = Note
        fields = ["deck", "question", "reponse", "tags"]
        widgets = {
            "question": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "reponse": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "tags": forms.TextInput(),
        }
