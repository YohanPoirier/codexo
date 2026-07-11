from django.contrib import admin
from django.urls import path
from accounts.views import EmailLoginView, signup
from django.contrib.auth.views import LogoutView
from exercises import views as ex_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', EmailLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('signup/', signup, name='signup'),
    path('', ex_views.theme_list, name='theme_list'),
    path('profil/', ex_views.profile, name='profile'),
    path('theme/<slug:theme_slug>/', ex_views.exercise_list, name='exercise_list'),
    path('theme/<slug:theme_slug>/<slug:exercise_slug>/', ex_views.exercise_detail, name='exercise_detail'),
    path('api/exercise/<int:exercise_id>/tests/', ex_views.exercise_tests, name='exercise_tests'),
    path('api/exercise/<int:exercise_id>/submit/', ex_views.submit_result, name='submit_result'),
    path('api/exercise/<int:exercise_id>/abandon/', ex_views.abandon_exercise, name='abandon_exercise'),
]
