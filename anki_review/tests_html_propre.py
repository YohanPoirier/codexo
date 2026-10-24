from django.test import TestCase

from anki_review.html_propre import nettoyer_html
from anki_review.models import Deck, Note, PropositionModification
from anki_review.templatetags.anki_extras import resoudre_images


class NettoyerHtmlTests(TestCase):
    def test_supprime_ce_qui_execute_du_code(self):
        sale = (
            '<b>ok</b><script>alert(1)</script><img src="a.png" onerror="alert(1)">'
            '<a href="javascript:alert(1)">x</a><iframe src="//e"></iframe>'
            '<style>body{x:y}</style><svg onload=alert(1)></svg>'
            '<div onclick="x()" style="text-align: center; position: fixed">c</div>'
        )
        propre = nettoyer_html(sale)
        for interdit in ("script", "onerror", "javascript", "iframe", "alert", "svg", "onclick",
                         "position", "<style", "body{"):
            self.assertNotIn(interdit, propre)
        self.assertIn("<b>ok</b>", propre)
        self.assertIn('src="a.png"', propre)
        self.assertIn("text-align: center", propre)

    def test_conserve_le_contenu_de_l_editeur_et_d_anki(self):
        html = (
            '<i>a</i><u>b</u><ul><li>x</li></ul><sub>1</sub><sup>2</sup>'
            '<font color="#ff0000">r</font><span style="color: red">s</span>'
            '<img src="f.png" width="200"><table><tr><td colspan="2">t</td></tr></table>'
            '<a href="https://exemple.fr">l</a>'
        )
        propre = nettoyer_html(html)
        # bleach normalise légèrement (point-virgule final des styles) : on vérifie le fond.
        for attendu in ("<i>a</i>", "<u>b</u>", "<ul><li>x</li></ul>", "<sub>1</sub>", "<sup>2</sup>",
                        '<font color="#ff0000">r</font>', "color: red", '<img src="f.png" width="200">',
                        '<td colspan="2">t</td>', '<a href="https://exemple.fr">l</a>'):
            self.assertIn(attendu, propre)
        self.assertEqual(nettoyer_html(propre), propre)

    def test_centrage_ancien_style_anki_conserve(self):
        self.assertEqual(nettoyer_html('<div align="center">x</div>'), '<div align="center">x</div>')

    def test_fins_de_ligne_windows_normalisees(self):
        # Les notes #105… du rapport ne changent que par \r\n -> \n (sans effet visible).
        self.assertEqual(nettoyer_html("a\r\nb"), "a\nb")

    def test_latex_echappe_conserve_et_idempotent(self):
        html = r"\(a &lt; b\) et \[x &gt; 0\]"
        self.assertEqual(nettoyer_html(html), html)
        sale = '<img src=x onerror=alert(1)>'
        self.assertEqual(nettoyer_html(nettoyer_html(sale)), nettoyer_html(sale))

    def test_vide(self):
        self.assertEqual(nettoyer_html(""), "")
        self.assertEqual(nettoyer_html(None), "")


class BrancheMentTests(TestCase):
    def setUp(self):
        self.deck = Deck.objects.create(nom="D", slug="d")

    def test_note_nettoyee_a_l_enregistrement(self):
        note = Note.objects.create(deck=self.deck, question="<script>x</script>Q<b onclick=1>g</b>", reponse="R")
        note.refresh_from_db()
        self.assertEqual(note.question, "Q<b>g</b>")

    def test_proposition_nettoyee(self):
        note = Note.objects.create(deck=self.deck, question="Q", reponse="R")
        from accounts.models import User
        u = User.objects.create_user("e1", "mdp-eleve-solide-1")
        p = PropositionModification.objects.create(
            note=note, auteur=u, question='<img src=a.png onerror=x>', reponse="R", tags="")
        p.refresh_from_db()
        self.assertNotIn("onerror", p.question)

    def test_filtre_d_affichage_nettoie_les_anciennes_cartes(self):
        rendu = resoudre_images('<img src="a.png" onerror="alert(1)">')
        self.assertNotIn("onerror", rendu)
        self.assertIn("/media/anki_review/notes/a.png", rendu)
