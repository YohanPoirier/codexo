from django.contrib import admin

from .models import Activite, Card, Deck, Note


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("nom", "slug")
    prepopulated_fields = {"slug": ("nom",)}


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("id", "deck", "guid", "modifie_le")
    list_filter = ("deck",)
    search_fields = ("guid", "question", "reponse", "tags")


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("id", "note", "etudiant", "file", "prochaine_revision", "repetitions")
    list_filter = ("file", "suspendue")
    search_fields = ("etudiant__username",)


@admin.register(Activite)
class ActiviteAdmin(admin.ModelAdmin):
    list_display = ("date", "etudiant", "type", "carte")
    list_filter = ("type",)
    date_hierarchy = "date"
