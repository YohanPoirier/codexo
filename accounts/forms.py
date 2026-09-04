from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Classe


class SignUpForm(UserCreationForm):
    email = forms.EmailField(label="Email")
    display_name = forms.CharField(label="Prénom / pseudo", max_length=80, required=False)
    role = forms.ChoiceField(label="Je suis...", choices=User.ROLE_CHOICES, initial=User.ELEVE)
    classe = forms.ModelChoiceField(
        label="Classe",
        queryset=Classe.objects.all(),
        required=False,
        help_text="Obligatoire pour les élèves.",
    )

    class Meta:
        model = User
        fields = ("email", "display_name", "role", "classe", "password1", "password2")

    def clean(self):
        # Une classe n'a de sens que pour un élève : on l'exige dans ce cas
        # précis, et on l'ignore silencieusement si un prof en a sélectionné
        # une par erreur (les profs n'appartiennent à aucune classe).
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        classe = cleaned_data.get("classe")
        if role == User.ELEVE and not classe:
            self.add_error("classe", "Une classe est obligatoire pour un élève.")
        elif role == User.PROF:
            cleaned_data["classe"] = None
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.classe = self.cleaned_data.get("classe")
        if commit:
            user.save()  # User.save() se charge de poser is_staff/is_superuser si role="prof"
        return user
