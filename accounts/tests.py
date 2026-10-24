import os
import tempfile
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.importation import ErreurEncodage, importer_eleves_depuis_lignes, lire_csv_texte
from accounts.models import Classe, User

CONFIG = dict(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)

ENTETE = "id,nom_complet,classe,mot_de_passe\n"


def importer(texte, delimiter=","):
    return importer_eleves_depuis_lignes(StringIO(texte, newline=""), delimiter=delimiter)


class ImportEleveTests(TestCase):
    def setUp(self):
        self.pcsi = Classe.objects.create(name="PCSI", slug="pcsi")
        self.psi = Classe.objects.create(name="PSI", slug="psi")

    def test_nouveau_compte(self):
        crees, maj, erreurs = importer(ENTETE + "jdupont,Jean Dupont,PCSI,01/01/2008\n")
        self.assertEqual((crees, maj, erreurs), (1, 0, []))
        eleve = User.objects.get(identifiant="jdupont")
        self.assertEqual(eleve.role, User.ELEVE)
        self.assertEqual(eleve.classe, self.pcsi)
        self.assertTrue(eleve.check_password("01/01/2008"))
        self.assertTrue(eleve.doit_changer_mot_de_passe)

    def test_eleve_existant_garde_son_mot_de_passe_et_change_de_classe(self):
        importer(ENTETE + "jdupont,Jean Dupont,PCSI,01/01/2008\n")
        eleve = User.objects.get(identifiant="jdupont")
        eleve.set_password("mon-nouveau-mot-de-passe-9")  # choisi par l'élève
        eleve.doit_changer_mot_de_passe = False
        eleve.save()

        # L'année suivante : même fichier, nouvelle classe, nom corrigé, autre mot de passe.
        crees, maj, erreurs = importer(ENTETE + "jdupont,Jean-Marc Dupont,PSI,autre-mdp\n")

        self.assertEqual((crees, maj, erreurs), (0, 1, []))
        eleve.refresh_from_db()
        self.assertEqual(eleve.classe, self.psi)
        self.assertEqual(eleve.display_name, "Jean-Marc Dupont")
        self.assertTrue(eleve.check_password("mon-nouveau-mot-de-passe-9"))
        self.assertFalse(eleve.doit_changer_mot_de_passe)

    def test_historique_conserve_apres_changement_de_classe(self):
        from anki_review.models import Card, Deck, Note

        importer(ENTETE + "jdupont,Jean Dupont,PCSI,01/01/2008\n")
        eleve = User.objects.get(identifiant="jdupont")
        note = Note.objects.create(deck=Deck.objects.create(nom="D", slug="d"), question="q", reponse="r")
        Card.objects.create(note=note, etudiant=eleve, repetitions=4)

        importer(ENTETE + "jdupont,Jean Dupont,PSI,x\n")

        self.assertEqual(Card.objects.get(etudiant=eleve).repetitions, 4)

    def test_eleve_existant_sans_mot_de_passe_dans_le_fichier_est_accepte(self):
        importer(ENTETE + "jdupont,Jean Dupont,PCSI,01/01/2008\n")
        crees, maj, erreurs = importer(ENTETE + "jdupont,Jean Dupont,PSI,\n")
        self.assertEqual((crees, maj, erreurs), (0, 1, []))

    def test_nouveau_compte_sans_mot_de_passe_refuse(self):
        crees, maj, erreurs = importer(ENTETE + "jdupont,Jean Dupont,PCSI,\n")
        self.assertEqual((crees, maj), (0, 0))
        self.assertEqual(len(erreurs), 1)
        self.assertFalse(User.objects.filter(identifiant="jdupont").exists())

    def test_compte_professeur_jamais_modifie(self):
        prof = User.objects.create_user("prof", "mdp-prof-solide-1", role=User.PROF)
        admin = User.objects.create_superuser("admin", "mdp-admin-solide-1")
        crees, maj, erreurs = importer(
            ENTETE + "prof,Pirate,PCSI,pirate123\nadmin,Pirate,PCSI,pirate123\n"
        )
        self.assertEqual((crees, maj), (0, 0))
        self.assertEqual(len(erreurs), 2)
        for compte, ancien in ((prof, "mdp-prof-solide-1"), (admin, "mdp-admin-solide-1")):
            compte.refresh_from_db()
            self.assertTrue(compte.check_password(ancien))
            self.assertFalse(compte.check_password("pirate123"))
            self.assertIsNone(compte.classe)
        admin.refresh_from_db()
        self.assertTrue(admin.is_superuser)
        self.assertNotEqual(admin.role, User.ELEVE)

    def test_compte_staff_sans_role_prof_protege(self):
        staff = User.objects.create_user("technique", "mdp-tech-solide-1", is_staff=True)
        importer(ENTETE + "technique,Pirate,PCSI,pirate123\n")
        staff.refresh_from_db()
        self.assertTrue(staff.check_password("mdp-tech-solide-1"))

    def test_classe_inconnue_et_champs_manquants(self):
        crees, maj, erreurs = importer(
            ENTETE + "a,Alice,INCONNUE,x\n,Bob,PCSI,x\nc,Chloé,PCSI,x\n"
        )
        self.assertEqual((crees, maj), (1, 0))
        self.assertEqual(len(erreurs), 2)


class LectureCsvTests(TestCase):
    def test_utf8_avec_bom(self):
        self.assertEqual(lire_csv_texte("id;nom\né".encode("utf-8-sig")), "id;nom\né")

    def test_windows_1252_excel_francais(self):
        self.assertEqual(lire_csv_texte("id;nom\nJérôme".encode("cp1252")), "id;nom\nJérôme")

    def test_illisible(self):
        with self.assertRaises(ErreurEncodage):
            lire_csv_texte(b"id;\x81\x8d\x8f\x90\x9d")


@override_settings(**CONFIG)
class ImportWebEtCommandeTests(TestCase):
    def setUp(self):
        Classe.objects.create(name="PCSI", slug="pcsi")
        self.prof = User.objects.create_user("prof-w", "mdp-prof-solide-1", role=User.PROF)
        self.prof.a_vu_intro_pas_a_pas = True
        self.prof.save()

    def _envoyer(self, octets, delimiter=";"):
        self.client.force_login(self.prof)
        return self.client.post(reverse("importer_eleves"), {
            "fichier": SimpleUploadedFile("eleves.csv", octets), "delimiter": delimiter,
        })

    def test_csv_excel_francais_avec_accents(self):
        contenu = "id;nom_complet;classe;mot_de_passe\njdupont;Jérôme Dupont;PCSI;01/01/2008\n"
        reponse = self._envoyer(contenu.encode("cp1252"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["resultat"]["crees"], 1)
        self.assertEqual(User.objects.get(identifiant="jdupont").display_name, "Jérôme Dupont")

    def test_fichier_illisible_affiche_une_erreur_au_lieu_de_planter(self):
        reponse = self._envoyer(b"id;\x81\x8d\x8f\x90\x9d")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("fichier", reponse.context["form"].errors)

    def test_page_reservee_aux_professeurs(self):
        eleve = User.objects.create_user("eleve-w", "mdp-eleve-solide-1")
        eleve.a_vu_intro_pas_a_pas = True
        eleve.save()
        self.client.force_login(eleve)
        self.assertEqual(self.client.get(reverse("importer_eleves")).status_code, 302)

    def test_commande_lit_aussi_le_cp1252(self):
        contenu = "id;nom_complet;classe;mot_de_passe\nrdupont;René Dupont;PCSI;01/01/2008\n"
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "eleves.csv")
            with open(chemin, "wb") as f:
                f.write(contenu.encode("cp1252"))
            call_command("importer_eleves", chemin, "--delimiter", ";", stdout=StringIO())
        self.assertEqual(User.objects.get(identifiant="rdupont").display_name, "René Dupont")
