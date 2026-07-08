from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from .forms import SignUpForm


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("theme_list")
    else:
        form = SignUpForm()
    return render(request, "accounts/signup.html", {"form": form})
