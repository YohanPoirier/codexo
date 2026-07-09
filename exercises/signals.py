from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Theme, Exercise, TestCase
from .export_utils import export_exercises_to_json


def _auto_export(sender, **kwargs):
    # Uniquement en local (DEBUG=True) : sur Render, ce fichier n'est de toute
    # façon pas synchronisé vers Git automatiquement, inutile de l'écrire là-bas.
    if settings.DEBUG:
        export_exercises_to_json()


post_save.connect(_auto_export, sender=Theme, dispatch_uid="auto_export_theme_save")
post_delete.connect(_auto_export, sender=Theme, dispatch_uid="auto_export_theme_delete")
post_save.connect(_auto_export, sender=Exercise, dispatch_uid="auto_export_exercise_save")
post_delete.connect(_auto_export, sender=Exercise, dispatch_uid="auto_export_exercise_delete")
post_save.connect(_auto_export, sender=TestCase, dispatch_uid="auto_export_testcase_save")
post_delete.connect(_auto_export, sender=TestCase, dispatch_uid="auto_export_testcase_delete")
