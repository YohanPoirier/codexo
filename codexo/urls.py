from django.contrib import admin
from django.urls import path
from accounts.views import (
    IdentifiantLoginView,
    ChangerMotDePasseView,
    demande_mot_de_passe_oublie,
    mot_de_passe_oublie_envoye,
    demandes_reinitialisation,
)
from django.contrib.auth.views import LogoutView
from exercises import views as ex_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', IdentifiantLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('changer-mot-de-passe/', ChangerMotDePasseView.as_view(), name='changer_mot_de_passe'),
    path('mot-de-passe-oublie/', demande_mot_de_passe_oublie, name='mot_de_passe_oublie'),
    path('mot-de-passe-oublie/envoye/', mot_de_passe_oublie_envoye, name='mot_de_passe_oublie_envoye'),
    path('demandes-reinitialisation/', demandes_reinitialisation, name='demandes_reinitialisation'),
    path('', ex_views.theme_list, name='theme_list'),
    path('profil/', ex_views.profile, name='profile'),
    path('stats/', ex_views.stats, name='stats'),
    path('stats/visibilite/', ex_views.classe_visibility, name='classe_visibility'),
    path('theme/<slug:theme_slug>/', ex_views.exercise_list, name='exercise_list'),
    path('theme/<slug:theme_slug>/<slug:exercise_slug>/', ex_views.exercise_detail, name='exercise_detail'),
    path('api/exercise/<int:exercise_id>/tests/', ex_views.exercise_tests, name='exercise_tests'),
    path('api/exercise/<int:exercise_id>/submit/', ex_views.submit_result, name='submit_result'),
    path('api/exercise/<int:exercise_id>/abandon/', ex_views.abandon_exercise, name='abandon_exercise'),
    path('api/hint/<int:hint_id>/viewed/', ex_views.hint_viewed, name='hint_viewed'),
]
# Suppression de /signup/ (06/09/2026) : plus d'inscription publique, pour aucun
# rôle. Voir contexte-technique.md — comptes créés uniquement via /admin/ (profs) ou
# la commande "importer_eleves" (élèves).
