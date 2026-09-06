from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, identifiant, password=None, **extra_fields):
        if not identifiant:
            raise ValueError("L'identifiant est obligatoire.")
        user = self.model(identifiant=identifiant, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, identifiant, password=None, **extra_fields):
        # Le compte admin créé via createsuperuser (voir seed_exercises.py / Procfile)
        # est traité comme un prof : is_staff sera de toute façon forcé par User.save()
        # dès que role="prof" ; is_superuser ne l'est en revanche PLUS automatiquement
        # (voir User.save() plus bas, refonte du 06/09/2026) — on le pose ici
        # explicitement pour que ce compte de bootstrap ait bien tous les droits.
        extra_fields.setdefault("role", "prof")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(identifiant, password, **extra_fields)


class Classe(models.Model):
    """Une classe d'élèves (ex: "Terminale NSI 1"). Uniquement utile pour les
    utilisateurs de rôle ELEVE : un prof n'appartient à aucune classe."""

    name = models.CharField("nom", max_length=100)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "classe"
        verbose_name_plural = "classes"

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

    # Identifiant de connexion (remplace l'email depuis la refonte du 06/09/2026,
    # voir contexte-technique.md) : texte libre choisi par le prof à la création du
    # compte (pour un élève, correspond typiquement au "id" fourni dans le CSV
    # d'import — voir accounts/management/commands/importer_eleves.py).
    identifiant = models.CharField(
        "identifiant",
        max_length=150,
        unique=True,
        null=True,  # nullable au niveau BDD uniquement pour permettre la migration en
                    # douceur des comptes déjà existants (voir la migration de données
                    # associée, qui reprend l'ancien email comme identifiant) ; en
                    # pratique tout compte utilisable doit en avoir un.
        blank=False,
        help_text=(
            "Identifiant de connexion. Pour un élève, correspond typiquement au 'id' "
            "fourni dans le CSV d'import."
        ),
    )

    # Email désormais facultatif : conservé uniquement pour les comptes profs (utile
    # pour les contacter). Les élèves importés par CSV n'en ont plus du tout
    # (minimisation des données). Ne sert plus à se connecter, voir USERNAME_FIELD.
    email = models.EmailField(
        "adresse email",
        blank=True,
        null=True,
        help_text="Facultatif. Les comptes élèves importés par CSV n'en ont pas.",
    )

    display_name = models.CharField("nom affiché", max_length=80, blank=True)
    role = models.CharField("rôle", max_length=10, choices=ROLE_CHOICES, default=ELEVE)
    classe = models.ForeignKey(
        Classe,
        related_name="eleves",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Uniquement pour les élèves : la classe à laquelle ils appartiennent.",
    )

    # Compte importé par CSV (ou tout autre compte à qui on veut imposer ça) : tant
    # que c'est True, ForcerChangementMotDePasseMiddleware (accounts/middleware.py)
    # redirige systématiquement vers le changement de mot de passe, quelle que soit
    # la page demandée. Repassé à False dès que le changement est effectué (voir
    # accounts/views.py : ChangerMotDePasseView).
    doit_changer_mot_de_passe = models.BooleanField(
        "doit changer son mot de passe",
        default=False,
        help_text=(
            "Coché automatiquement pour les comptes importés par CSV (mot de passe "
            "provisoire = date de naissance)."
        ),
    )

    USERNAME_FIELD = "identifiant"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.display_name or self.identifiant or self.email or f"Utilisateur #{self.pk}"

    @property
    def is_prof(self):
        return self.role == self.PROF

    @property
    def is_eleve(self):
        return self.role == self.ELEVE

    def save(self, *args, **kwargs):
        # Un prof a is_staff=True (accès à /admin/ et aux pages réservées comme
        # /stats/), mais N'EST PLUS automatiquement superuser depuis le 06/09/2026
        # (voir contexte-technique.md, section "Refonte de l'authentification") :
        # ses droits réels sur le contenu pédagogique (Theme/Exercise/TestCase/Hint/
        # Classe) viennent désormais du groupe Django "Professeurs", à assigner
        # manuellement lors de la création du compte (champ "groups" du formulaire
        # d'ajout de l'admin).
        #
        # Pour un élève, on ne touche PAS à is_staff/is_superuser : ça permet de
        # garder un éventuel superuser technique (compte admin créé par
        # createsuperuser/seed_exercises) qui n'aurait pas explicitement role="prof",
        # sans lui retirer ses droits à chaque sauvegarde.
        if self.role == self.PROF:
            self.is_staff = True
        super().save(*args, **kwargs)


class DemandeReinitialisation(models.Model):
    """Une demande de réinitialisation de mot de passe, soumise par un élève ayant
    perdu le sien (voir accounts/views.py : demande_mot_de_passe_oublie). Aucune
    vérification n'est faite à la soumission (l'identifiant saisi n'a même pas
    besoin de correspondre à un compte réel) : c'est un prof qui filtre ça à la main
    en traitant la demande (voir demandes_reinitialisation, page réservée aux
    profs)."""

    identifiant_saisi = models.CharField(
        "identifiant saisi",
        max_length=150,
        help_text="Tel que saisi par l'élève, pas forcément un identifiant existant.",
    )
    email_contact = models.EmailField(
        "email de contact",
        help_text="Adresse à laquelle le prof enverra lui-même le nouveau mot de passe.",
    )
    date_demande = models.DateTimeField("date de la demande", auto_now_add=True)
    traite = models.BooleanField("traité", default=False)
    traite_le = models.DateTimeField("traité le", null=True, blank=True)

    class Meta:
        ordering = ["traite", "-date_demande"]
        verbose_name = "demande de réinitialisation"
        verbose_name_plural = "demandes de réinitialisation"

    def __str__(self):
        return f"{self.identifiant_saisi} ({self.email_contact})"

    def marquer_traitee(self):
        self.traite = True
        self.traite_le = timezone.now()
        self.save(update_fields=["traite", "traite_le"])
