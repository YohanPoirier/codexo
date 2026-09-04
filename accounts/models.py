from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        # Le compte admin créé via createsuperuser (voir seed_exercises.py /
        # Procfile) est traité comme un prof : is_staff/is_superuser seront de
        # toute façon forcés à True par User.save() dès que role="prof", mais
        # on le pose ici explicitement pour que ce soit cohérent dès la création.
        extra_fields.setdefault("role", "prof")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Classe(models.Model):
    """Une classe d'élèves (ex: "Terminale NSI 1"). Uniquement utile pour les
    utilisateurs de rôle ELEVE : un prof n'appartient à aucune classe."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    PROF = "prof"
    ELEVE = "eleve"
    ROLE_CHOICES = [
        (PROF, "Professeur"),
        (ELEVE, "Élève"),
    ]

    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ELEVE)
    classe = models.ForeignKey(
        Classe,
        related_name="eleves",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Uniquement pour les élèves : la classe à laquelle ils appartiennent.",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.display_name or self.email

    @property
    def is_prof(self):
        return self.role == self.PROF

    @property
    def is_eleve(self):
        return self.role == self.ELEVE

    def save(self, *args, **kwargs):
        # Tous les profs ont EXACTEMENT les mêmes droits : plutôt que de
        # devoir cocher "staff"/"superuser" à la main dans l'admin à chaque
        # création de compte prof, on les déduit automatiquement du rôle ici.
        # Pour un élève, on ne touche PAS à is_staff/is_superuser : ça permet
        # de garder un éventuel superuser technique (compte admin local/prod
        # créé par createsuperuser) qui n'aurait pas explicitement role="prof",
        # sans lui retirer ses droits à chaque sauvegarde.
        if self.role == self.PROF:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)
