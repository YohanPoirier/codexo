from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Classe, DemandeReinitialisation


@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("identifiant",)
    list_display = (
        "identifiant", "display_name", "role", "classe", "is_staff",
        "doit_changer_mot_de_passe", "date_joined",
    )
    list_filter = ("role", "classe", "is_staff", "doit_changer_mot_de_passe")
    fieldsets = (
        (None, {"fields": ("identifiant", "password")}),
        ("Infos", {"fields": ("display_name", "email", "role", "classe")}),
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


@admin.register(DemandeReinitialisation)
class DemandeReinitialisationAdmin(admin.ModelAdmin):
    """Enregistré aussi dans l'admin par commodité/secours, même si le circuit
    normal passe par la page dédiée /demandes-reinitialisation/ (accessible depuis
    le menu pour tout compte is_staff)."""

    list_display = ("identifiant_saisi", "email_contact", "date_demande", "traite")
    list_filter = ("traite",)
    readonly_fields = ("date_demande",)
