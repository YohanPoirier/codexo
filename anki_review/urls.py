from django.urls import path

from . import views

app_name = "anki_review"

urlpatterns = [
    path("", views.liste_decks, name="liste_decks"),

    # Espace prof — routes fixes, doivent être déclarées AVANT le
    # "<slug:deck_slug>/" générique ci-dessous, sans quoi Django
    # interpréterait "edition" comme un slug de paquet à réviser.
    path("trafic/", views.trafic, name="trafic"),
    path("edition/", views.edition_accueil, name="edition"),
    path("edition/<slug:deck_slug>/", views.edition_deck, name="edition_deck"),

    path("paquets/ajouter/", views.ajouter_deck, name="ajouter_deck"),
    path("paquets/<int:deck_id>/modifier/", views.modifier_deck, name="modifier_deck"),
    path("paquets/<int:deck_id>/supprimer/", views.supprimer_deck, name="supprimer_deck"),

    path("ajouter/", views.ajouter_note, name="ajouter_note"),
    path("cartes/<int:note_id>/modifier/", views.modifier_note, name="modifier_note"),
    path("cartes/<int:note_id>/supprimer/", views.supprimer_note, name="supprimer_note"),

    path("uploader-image/", views.uploader_image, name="uploader_image"),
    path("matiere/<slug:matiere>/", views.reviser_matiere, name="reviser_matiere"),

    # Import/export — partage entre étudiants (le partage fichier .apkg
    # viendra ensuite dans import_export_fichier).
    path("import-export/", views.import_export_accueil, name="import_export_accueil"),
    path("import-export/fichier/", views.import_export_fichier, name="import_export_fichier"),
    path("import-export/fichier/importer-confirmer/", views.import_apkg_confirmer, name="import_apkg_confirmer"),
    path("import-export/fichier/exporter/", views.exporter_apkg_selection, name="exporter_apkg_selection"),
    path("import-export/etudiants/", views.partage_etudiants, name="partage_etudiants"),
    path("import-export/<int:note_id>/partager/", views.partager_note_toggle, name="partager_note_toggle"),
    path("import-export/<int:note_id>/ajouter-copie/", views.ajouter_carte_partagee, name="ajouter_carte_partagee"),

    path("import-export/paquet/<int:deck_id>/partager-tout/", views.partager_paquet_toggle, name="partager_paquet_toggle"),
    path("import-export/paquet/<int:deck_id>/supprimer-mes-cartes/", views.supprimer_mes_cartes_paquet, name="supprimer_mes_cartes_paquet"),
    path("import-export/paquet/<int:deck_id>/<int:cree_par_id>/ajouter/", views.ajouter_paquet_partage, name="ajouter_paquet_partage"),

    # Propositions de modification (quelqu'un qui n'est pas propriétaire
    # d'une note propose une correction, à valider par le propriétaire).
    path("propositions/<int:proposition_id>/", views.voir_proposition, name="voir_proposition"),
    path("propositions/<int:proposition_id>/accepter/", views.accepter_proposition, name="accepter_proposition"),
    path("propositions/<int:proposition_id>/refuser/", views.refuser_proposition, name="refuser_proposition"),

    # Générique : à laisser en dernier (capte tout slug restant = un paquet à réviser)
    path("<slug:deck_slug>/", views.reviser, name="reviser"),
]
