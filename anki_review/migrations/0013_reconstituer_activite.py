"""
Reconstitution de l'historique d'Activite à partir des Card existantes, pour
que la page Trafic ne démarre pas vide (la partie Anki a été mise en ligne
le jour même où ce journal a été ajouté).

Approximations assumées :
- ajout / récupération : déduit du propriétaire ACTUEL de la note (une note
  dont l'étudiant est propriétaire = ajout, sinon = récupération), daté par
  Card.cree_le. Une carte déjà retirée n'est plus comptée.
- révision : on ne connaît que la DERNIÈRE révision de chaque carte
  (Card.derniere_revision), d'où au plus un événement par carte — c'est un
  minimum, une carte révisée trois fois le même jour ne compte qu'une fois.
"""
from django.db import migrations


def reconstituer(apps, schema_editor):
    Card = apps.get_model("anki_review", "Card")
    Activite = apps.get_model("anki_review", "Activite")

    # Sécurité : si le journal contient déjà des lignes (migration rejouée
    # après coup), on ne reconstitue rien pour ne pas créer de doublons.
    if Activite.objects.exists():
        return

    activites = []
    for carte in Card.objects.select_related("note").iterator():
        type_creation = "ajout" if carte.note.cree_par_id == carte.etudiant_id else "recuperation"
        activites.append(Activite(
            etudiant_id=carte.etudiant_id, type=type_creation, carte_id=carte.id, date=carte.cree_le,
        ))
        if carte.derniere_revision:
            activites.append(Activite(
                etudiant_id=carte.etudiant_id, type="revision", carte_id=carte.id,
                date=carte.derniere_revision,
            ))
    Activite.objects.bulk_create(activites, batch_size=500)


def vider(apps, schema_editor):
    apps.get_model("anki_review", "Activite").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anki_review", "0012_activite"),
    ]

    operations = [
        migrations.RunPython(reconstituer, vider),
    ]
