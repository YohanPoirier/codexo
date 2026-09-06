from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'
    # Sans ce réglage, l'admin Django affiche l'app sous son nom de code anglais
    # ("Accounts") en tête de page — incohérent avec le reste de l'admin, en français
    # (voir la même remarque sur exercises/apps.py).
    verbose_name = "Comptes"
