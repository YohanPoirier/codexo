"""migrer_chapitres sur « Outils mathématiques » (sans tags) : diffusé -> Équations différentielles,
non diffusé -> Complexes ; les cartes des élèves suivent."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from .models import Card, Deck, Note
from .tests_rangement import CONFIG, eleve, prof


@override_settings(**CONFIG)
class MigrerOutilsMathTests(TestCase):
    def setUp(self):
        self.p = prof("prof-om")
        self.e = eleve("eleve-om")
        self.src = Deck.objects.create(nom="Outils mathématiques", slug="om", cree_par=self.p, matiere="physique")
        self.diffusee = self._note("Équa diff 1", partagee=True)
        self.privee = self._note("Complexe 1", partagee=False)
        src_e = Deck.objects.create(nom="Outils mathématiques", slug="om-e", cree_par=self.e, matiere="physique")
        Card.objects.create(note=self.diffusee, etudiant=self.e, deck=src_e)

    def _note(self, q, partagee):
        n = Note.objects.create(deck=self.src, question=q, reponse="R", cree_par=self.p, partagee_avec_classe=partagee)
        Card.objects.create(note=n, etudiant=self.p, deck=self.src)
        return n

    def _lancer(self, *args):
        call_command("migrer_chapitres", "--partie", "Outils mathématiques", *args, stdout=StringIO())

    def test_simulation_ne_change_rien(self):
        self._lancer()
        self.assertTrue(Deck.objects.filter(pk=self.src.pk).exists())
        self.assertFalse(Deck.objects.filter(nom="Complexes").exists())

    def test_appliquer_range_par_diffusion_sans_rien_supprimer(self):
        self._lancer("--appliquer")
        nb = Card.objects.count()
        self.assertEqual(nb, 3)
        carte = lambda note, u: Card.objects.get(note=note, etudiant=u).deck
        self.assertEqual(carte(self.diffusee, self.p).nom, "Équations différentielles")
        self.assertEqual(carte(self.privee, self.p).nom, "Complexes")
        self.assertEqual(carte(self.diffusee, self.e).nom, "Équations différentielles")
        self.assertEqual(carte(self.diffusee, self.e).cree_par, self.e)
        self.assertEqual(carte(self.diffusee, self.p).partie, "Outils mathématiques")
        self.assertFalse(Deck.objects.filter(pk=self.src.pk).exists())

    def test_rejouable(self):
        self._lancer("--appliquer")
        self._lancer("--appliquer")
        self.assertEqual(Deck.objects.filter(nom="Complexes").count(), 1)
