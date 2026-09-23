"""
Schéma inspiré du format natif d'Anki (.anki2), adapté à Django/SQLite.

Séparation volontaire :
- Deck  : regroupement de notes (ex. "Optique")
- Note  : contenu (question/réponse), UNE SEULE fois en base même quand
          plusieurs étudiants la révisent — pas de copie par étudiant.
          Le propriétaire (cree_par) est seul à pouvoir la modifier
          directement ; une modification par quelqu'un d'autre passe par
          une PropositionModification, à valider par le propriétaire.
- Card  : progression SM-2 d'UN étudiant sur UNE note. Une note a autant de
          Card que d'étudiants qui l'ont ajoutée à leur révision, toutes
          rattachées à la MÊME Note.
- PropositionModification : correction en attente de validation par le
          propriétaire d'une note (cf. Note ci-dessus).

Les images référencées dans question/reponse sont stockées comme fichiers
(MEDIA_ROOT), pas en base64 inline — cf. balises <img src="..."> classiques,
pour rester compatible avec l'export .apkg (dossier media/ du zip).
"""
import html
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.html import strip_tags


class Deck(models.Model):
    class Matiere(models.TextChoices):
        PHYSIQUE = "physique", "Physique"
        MATHEMATIQUES = "mathematiques", "Mathématiques"
        CHIMIE = "chimie", "Chimie"
        ANGLAIS = "anglais", "Anglais"
        LETTRES_PHILOSOPHIE = "lettres-philosophie", "Lettres-Philosophie"
        ALLEMAND = "allemand", "Allemand"
        ESPAGNOL = "espagnol", "Espagnol"

    nom = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    matiere = models.CharField(max_length=30, choices=Matiere.choices, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="decks_crees",
        help_text="Propriétaire du paquet (prof ou étudiant) — seul lui (ou un prof) peut le modifier/supprimer",
    )

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Note(models.Model):
    """
    Contenu d'une carte, indépendant de l'étudiant qui la révise.

    Le GUID est LA clé de compatibilité avec Anki : à l'import d'un .apkg,
    on réutilise le GUID déjà présent dans le fichier plutôt que d'en générer
    un nouveau, pour pouvoir détecter les notes déjà connues lors d'un futur
    import/partage entre étudiants (cf. logique de diff GUID évoquée en chat).
    """
    guid = models.CharField(max_length=64, default=uuid.uuid4)
    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name="notes")

    question = models.TextField(help_text="HTML autorisé, y compris <img src=\"...\">")
    reponse = models.TextField(help_text="HTML autorisé, y compris <img src=\"...\">")
    tags = models.CharField(max_length=300, blank=True, help_text="Séparés par des espaces, comme Anki")

    # Équivalent du champ `mod` d'Anki : sert à la résolution de conflit
    # lors d'un partage/fusion entre étudiants (la version la plus récente
    # l'emporte sur le contenu, jamais de fusion champ par champ).
    modifie_le = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notes_creees",
        help_text="Propriétaire de cette copie de la note (prof ou étudiant)",
    )

    # Une note personnelle d'un étudiant n'est visible que par lui tant que
    # ce champ est False. Contrairement à avant, "ajouter" une note
    # partagée ne la duplique plus — l'étudiant reçoit juste sa propre Card
    # (progression) sur CETTE MÊME Note, cf. anki_review.views.ajouter_carte_partagee.
    partagee_avec_classe = models.BooleanField(default=False)

    # Carte réversible (cf. NoteForm.CHOIX_TYPE_CARTE) : lien vers l'autre
    # moitié de la paire, comme Anki où une note "Basic (and reversed
    # card)" génère 2 cartes à partir des MÊMES champs — sauf que chez nous
    # ce sont 2 lignes Note distinctes (pas de notion de "modèle de carte"
    # dans notre schéma), synchronisées via save() ci-dessous plutôt que
    # partageant littéralement les mêmes champs. SET_NULL plutôt que CASCADE
    # : supprimer une moitié rend l'autre indépendante plutôt que de la
    # supprimer aussi en cascade (un choix délibéré, pas un oubli).
    note_miroir = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Autre moitié d'une paire recto-verso/verso-recto — modifier l'une met à jour l'autre (inversée).",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.deck.nom} — {self.question[:40]}"

    def titre_affichage(self):
        """Ce qu'il faut montrer dans une liste (Édition, Import/Export) :
        la question, nettoyée de son HTML ET de ses codes d'entité comme
        &nbsp; (strip_tags seul ne décode pas ces codes, laissant "&nbsp;"
        affiché tel quel) — jamais utilisé pour l'écran de révision
        lui-même, qui montre toujours la vraie Question."""
        return html.unescape(strip_tags(self.question))

    def sens_affichage(self):
        """Pour une carte réversible (note_miroir renseigné) : "(recto →
        verso)" pour celle créée en premier, "(verso → recto)" pour son
        miroir — déduit de l'ordre de création (id le plus petit = sens
        original saisi), il n'y a pas de champ dédié pour ça. Chaîne vide
        pour une carte normale."""
        if not self.note_miroir_id:
            return ""
        return "(recto → verso)" if self.id < self.note_miroir_id else "(verso → recto)"

    def bandes_apercu(self):
        """("R", "V") normalement — le champ question porte le recto, la
        réponse le verso. Pour la moitié "verso -> recto" d'une carte
        réversible (cf. sens_affichage), c'est l'inverse : le champ
        question contient en fait le contenu d'origine du VERSO, d'où
        ("V", "R") pour ne pas afficher une lettre trompeuse dans l'aperçu."""
        if self.note_miroir_id and self.id > self.note_miroir_id:
            return "V", "R"
        return "R", "V"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Carte réversible : répercute automatiquement sur l'autre moitié
        # (question/réponse inversées, le reste identique) — via un simple
        # UPDATE en base, jamais un second .save(), pour éviter tout risque
        # de boucle infinie entre les deux notes liées.
        if self.note_miroir_id:
            Note.objects.filter(pk=self.note_miroir_id).update(
                deck=self.deck_id, tags=self.tags,
                question=self.reponse, reponse=self.question,
            )


class Card(models.Model):
    """
    Progression SM-2 d'un étudiant sur une note donnée.

    Une carte importée par un nouvel étudiant démarre TOUJOURS à l'état
    neuf (repetitions=0, ease_factor par défaut), même si la note existait
    déjà ailleurs avec un historique — comportement identique à l'import
    Anki natif.
    """

    class File(models.TextChoices):
        NOUVELLE = "new", "Nouvelle"
        APPRENTISSAGE = "learning", "En apprentissage"
        REVISION = "review", "En révision"

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="cards")
    etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cartes_anki"
    )
    # Sert à déterminer qui, parmi plusieurs détenteurs d'une même note,
    # l'a récupérée en premier — utilisé pour le transfert de propriété
    # quand le propriétaire d'origine supprime sa carte (cf.
    # anki_review.views.supprimer_note).
    cree_le = models.DateTimeField(auto_now_add=True)

    file = models.CharField(max_length=10, choices=File.choices, default=File.NOUVELLE)
    intervalle_jours = models.FloatField(default=0)
    facteur_facilite = models.FloatField(default=2.5)  # ease factor, valeur SM-2 standard
    repetitions = models.PositiveIntegerField(default=0)
    echecs = models.PositiveIntegerField(default=0, help_text="Nombre de fois répondu 'Again'")

    prochaine_revision = models.DateTimeField(default=timezone.now)
    derniere_revision = models.DateTimeField(null=True, blank=True)
    suspendue = models.BooleanField(default=False)

    class Meta:
        unique_together = [("note", "etudiant")]
        indexes = [
            models.Index(fields=["etudiant", "prochaine_revision"]),
        ]

    def __str__(self):
        return f"{self.etudiant} — {self.note_id} (échéance {self.prochaine_revision:%d/%m})"


class PropositionModification(models.Model):
    """
    Correction proposée par quelqu'un qui n'est PAS propriétaire d'une note
    (cf. anki_review.views._peut_editer_note) : le contenu proposé est
    stocké ICI, séparément, tant que le propriétaire (ou un prof) ne l'a
    pas explicitement acceptée — jamais appliqué directement à la Note.
    """

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        ACCEPTEE = "acceptee", "Acceptée"
        REFUSEE = "refusee", "Refusée"

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="propositions")
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="propositions_faites",
    )
    question = models.TextField(help_text="HTML autorisé, y compris <img src=\"...\">")
    reponse = models.TextField(help_text="HTML autorisé, y compris <img src=\"...\">")
    tags = models.CharField(max_length=300, blank=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.EN_ATTENTE)
    cree_le = models.DateTimeField(auto_now_add=True)
    traitee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Proposition de {self.auteur} sur note {self.note_id} ({self.get_statut_display()})"
