from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(label="Email")
    display_name = forms.CharField(label="Prénom / pseudo", max_length=80, required=False)

    class Meta:
        model = User
        fields = ("email", "display_name", "password1", "password2")
