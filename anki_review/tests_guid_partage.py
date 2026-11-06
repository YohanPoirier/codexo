"""Une carte est reconnue par son identifiant (guid) au partage, à la récupération et à l'import :
plusieurs copies d'une même carte (ex. un .apkg échangé entre élèves) n'en font qu'une pour un
troisième élève, qui ne peut jamais en avoir deux dans sa révision."""
import os
import tempfile

import genanki
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .apkg_import import importer_apkg
from .models import Card, Deck, Note
from .tests_rangement import AJAX, CONFIG, eleve, prof

GUID = "guid-commun-1"


def copie(auteur, deck, question="Q", guid=GUID, partagee=True):
    note = Note.objects.create(
        deck=deck, question=question, reponse="R", cree_par=auteur, guid=guid, partagee_avec_classe=partagee)
    Card.objects.create(note=note, etudiant=auteur, deck=deck)
    return note


def paquet_de(user, nom, slug):
    return Deck.objects.create(nom=nom, slug=slug, cree_par=user, matiere="anglais")


def apkg(guid=GUID, question="Q"):
    modele = genanki.Model(
        1968100422, "Basique", fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[{"name": "Carte 1", "qfmt": "{{Front}}", "afmt": "{{Back}}"}])
    paquet = genanki.Deck(2059400110, "Anglais")
    paquet.add_note(genanki.Note(model=modele, fields=[question, "R"], guid=guid))
    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "t.apkg")
        genanki.Package(paquet).write_to_file(chemin)
        return SimpleUploadedFile("t.apkg", open(chemin, "rb").read())


@override_settings(**CONFIG)
class PartageParGuidTests(TestCase):
    def setUp(self):
        self.philomene, self.antoine, self.zoe = eleve("philo-g"), eleve("antoine-g"), eleve("zoe-g")
        # Philomène d'abord (note la plus ancienne), puis Antoine : même guid, deux notes.
        self.n_philo = copie(self.philomene, paquet_de(self.philomene, "Presse", "presse-p"), "quotidien")
        self.n_antoine = copie(self.antoine, paquet_de(self.antoine, "Presse", "presse-a"), "quotidien")
        self.client.force_login(self.zoe)

    def _notes_vues(self):
        page = self.client.get(reverse("anki_review:partage_etudiants"))
        self.assertEqual(page.status_code, 200)
        return [(g["cree_par"], i["note"], i["statut"]) for g in page.context["groupes_partages"] for i in g["notes"]]

    def test_un_troisieme_eleve_ne_voit_que_la_version_la_plus_ancienne(self):
        vues = self._notes_vues()
        self.assertEqual(len(vues), 1)
        self.assertEqual((vues[0][0], vues[0][1]), (self.philomene, self.n_philo))

    def test_si_la_plus_ancienne_n_est_plus_partagee_l_autre_apparait(self):
        Note.objects.filter(pk=self.n_philo.pk).update(partagee_avec_classe=False)
        vues = self._notes_vues()
        self.assertEqual([(v[0], v[1]) for v in vues], [(self.antoine, self.n_antoine)])

    def test_carte_deja_possedee_sous_un_autre_note_du_meme_guid(self):
        # Zoé a déjà la version d'Antoine : celle de Philomène (affichée) est « déjà là ».
        Card.objects.create(note=self.n_antoine, etudiant=self.zoe, deck=paquet_de(self.zoe, "P", "p-z"))
        vues = self._notes_vues()
        self.assertEqual([(v[1], v[2]) for v in vues], [(self.n_philo, "deja")])

    def test_ajouter_ne_cree_pas_une_seconde_carte_du_meme_guid(self):
        self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n_philo.id]), **AJAX)
        self.assertEqual(Card.objects.filter(etudiant=self.zoe).count(), 1)
        reponse = self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n_antoine.id]), **AJAX)
        self.assertEqual(reponse.json(), {"cree": False})
        self.assertEqual(Card.objects.filter(etudiant=self.zoe).count(), 1)

    def test_tout_ajouter_saute_les_cartes_de_meme_guid_deja_presentes(self):
        self.client.post(reverse("anki_review:ajouter_carte_partagee", args=[self.n_philo.id]), **AJAX)
        copie(self.antoine, self.n_antoine.deck, "autre carte", guid="guid-2")
        reponse = self.client.post(
            reverse("anki_review:ajouter_paquet_partage", args=[self.n_antoine.deck_id, self.antoine.id]), **AJAX)
        self.assertEqual(reponse.json()["nouvelles"], 1)
        self.assertEqual(Card.objects.filter(etudiant=self.zoe).count(), 2)

    def test_chacun_garde_et_modifie_sa_carte(self):
        Note.objects.filter(pk=self.n_philo.pk).update(question="corrigée")
        self.n_antoine.refresh_from_db()
        self.assertEqual(self.n_antoine.question, "quotidien")


@override_settings(**CONFIG)
class ImportParGuidTests(TestCase):
    def setUp(self):
        self.p, self.a = eleve("philo-i"), eleve("antoine-i")
        self.n_p = copie(self.p, paquet_de(self.p, "Presse", "presse-ip"), "quotidien")
        self.n_a = copie(self.a, paquet_de(self.a, "Presse", "presse-ia"), "quotidien")
        self.zoe = eleve("zoe-i")

    def test_import_se_rattache_a_la_version_la_plus_ancienne(self):
        resume = importer_apkg(apkg(), self.zoe)
        self.assertEqual(resume["notes_recuperees"], 1)
        self.assertEqual(Card.objects.get(etudiant=self.zoe).note, self.n_p)

    def test_reimport_ne_cree_pas_de_seconde_carte_meme_si_on_a_l_autre_version(self):
        Card.objects.create(note=self.n_a, etudiant=self.zoe, deck=paquet_de(self.zoe, "P", "p-zi"))
        resume = importer_apkg(apkg(), self.zoe)
        self.assertEqual((resume["notes_recuperees"], resume["notes_deja_a_soi"]), (0, 1))
        self.assertEqual(Card.objects.filter(etudiant=self.zoe).count(), 1)

    def test_le_professeur_passe_avant_les_eleves(self):
        enseignant = prof("prof-guid")
        n_prof = copie(enseignant, paquet_de(enseignant, "Officiel", "officiel"), "quotidien")
        importer_apkg(apkg(), self.zoe)
        self.assertEqual(Card.objects.get(etudiant=self.zoe).note, n_prof)

    def test_carte_privee_de_l_original_donne_toujours_une_copie(self):
        Note.objects.filter(pk__in=[self.n_p.pk, self.n_a.pk]).update(partagee_avec_classe=False)
        resume = importer_apkg(apkg(), self.zoe)
        self.assertEqual((resume["notes_creees"], resume["notes_recuperees"]), (1, 0))
