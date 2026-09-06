from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from codexo.admin_mixins import SimplifieIndicationCtrlMixin

from .models import User, Classe


@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(SimplifieIndicationCtrlMixin, BaseUserAdmin):
    # "groups" et "user_permissions" sont hérités de BaseUserAdmin (filter_horizontal) :
    # même rappel "sur un Mac" hors-sujet que sur Theme/Exercise.enabled_for_classes, mais
    # ici la première phrase du help_text (ex: "Les groupes dont fait partie cet
    # utilisateur...") est utile et doit être conservée — voir CHAMPS_AVEC_MENTION_MAC_A_RETIRER
    # dans codexo/admin_mixins.py.
    CHAMPS_AVEC_MENTION_MAC_A_RETIRER = ("groups", "user_permissions")

    ordering = ("identifiant",)
    list_display = (
        "identifiant", "display_name", "role", "classe", "is_staff",
        "doit_changer_mot_de_passe", "date_joined",
    )
    list_filter = ("role", "classe", "is_staff", "doit_changer_mot_de_passe")
    fieldsets = (
        (None, {"fields": ("identifiant", "password")}),
        ("Informations", {"fields": ("display_name", "email", "role", "classe")}),
        ("Mot de passe", {"fields": ("doit_changer_mot_de_passe",)}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    # Rappel (voir contexte-technique.md) : pour un compte prof, cocher "is_staff"
    # (fait automatiquement par User.save() dès que role="Professeur") et assigner le
    # groupe "Professeurs" ici (champ "groups") — NE PAS cocher "is_superuser".
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "identifiant", "display_name", "email", "role", "classe",
                    "groups", "password1", "password2",
                ),
            },
        ),
    )
    search_fields = ("identifiant", "display_name", "email")

# DemandeReinitialisation n'est plus enregistrée ici (retiré le 06/09/2026) : le seul
# circuit de traitement reste la page dédiée /demandes-reinitialisation/, pour éviter
# d'avoir deux façons de faire la même chose dans deux endroits différents.
