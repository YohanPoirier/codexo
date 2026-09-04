from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Classe


@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "display_name", "role", "classe", "is_staff", "date_joined")
    list_filter = ("role", "classe", "is_staff")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Infos", {"fields": ("display_name", "role", "classe")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "display_name", "role", "classe", "password1", "password2")}),
    )
    search_fields = ("email", "display_name")
