from django import forms
from django.utils.text import slugify

from .models import Deck, Note


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
            base = slugify(deck.nom)
            slug = base
            i = 2
            while Deck.objects.filter(slug=slug).exclude(pk=deck.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            deck.slug = slug
        if commit:
            deck.save()
        return deck


class NoteForm(forms.ModelForm):
    TYPE_NORMAL = "normal"
    TYPE_DOUBLE = "double"
    TYPE_DOUBLE_DEFINITION = "double_definition"
    TYPE_DOUBLE_VOCABULAIRE = "double_vocabulaire"
    CHOIX_TYPE_CARTE = [
        (TYPE_NORMAL, "Normal"),
        (TYPE_DOUBLE, "Double (recto-verso et verso-recto)"),
        (TYPE_DOUBLE_DEFINITION, "Double définition (ajoute \"Terme\" / \"Définition\")"),
        (TYPE_DOUBLE_VOCABULAIRE, "Double vocabulaire (ajoute \"Français\" / langue étrangère)"),
    ]

    # Champ non lié au modèle : influence UNIQUEMENT la création (combien de
    # notes sont générées et avec quelles étiquettes) — jamais sauvegardé
    # sur la Note elle-même, donc sans effet à la modification.
    type_carte = forms.ChoiceField(choices=CHOIX_TYPE_CARTE, initial=TYPE_NORMAL, required=False)

    class Meta:
        model = Note
        fields = ["deck", "titre", "question", "reponse", "tags"]
        widgets = {
            "titre": forms.TextInput(),
            "question": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "reponse": forms.Textarea(attrs={"rows": 5, "class": "editeur-champ"}),
            "tags": forms.TextInput(),
        }
