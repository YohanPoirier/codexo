"""Range les cartes d'une partie (ex. « Électricité ») dans un paquet par chapitre, d'après leurs
tags « Chap.N » — pour passer de « un paquet = une partie » à « une partie = plusieurs paquets,
un par chapitre » (matière → partie → chapitre).

Pour CHAQUE paquet « Électricité » (celui du professeur comme ceux des élèves), les cartes sont
rangées dans un paquet par chapitre, du même propriétaire, de même matière et de même partie ;
les cartes sans tag « Chap.N » connu vont dans un paquet « Autres ». L'ancien paquet est supprimé
s'il est vide ensuite. La progression de révision ne change pas (on ne déplace que le rangement).

Par défaut c'est une SIMULATION : tout est calculé et affiché, puis annulé. Il faut ajouter
--appliquer pour écrire en base. La commande est rejouable : les paquets-chapitres déjà créés sont
réutilisés. Les intitulés des chapitres sont dans CHAPITRES ci-dessous.

    python manage.py migrer_chapitres --partie "Outils mathématiques"              # simulation
    python manage.py migrer_chapitres --partie "Outils mathématiques" --appliquer

Pour une nouvelle partie : ajouter son entrée dans CHAPITRES (et, si ses cartes n'ont pas de tags
Chap.N, une fonction dans CLASSEURS). Les parties déjà migrées (ex. Électricité) en sont retirées.
"""
import re
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.html import strip_tags

from anki_review.decks import creer_paquet
from anki_review.models import Card, Deck, Note
from anki_review.slugs import slug_unique

# (matière, partie) -> {numéro de chapitre: nom du paquet}
CHAPITRES = {
    # Pas de tags Chap.N ici : le rangement se fait avec CLASSEURS ci-dessous.
    ("physique", "Outils mathématiques"): {
        1: "Équations différentielles",
        2: "Complexes",
    },
}

NOM_PAQUET_AUTRES = "Autres"
_RE_TAG_CHAPITRE = re.compile(r"(?:^|\s)Chap\.(\d+)(?=\s|$)")


def _normaliser(texte):
    """Sans accents, en minuscules : « Électricité » et « electricite » sont le même nom."""
    sans_accents = unicodedata.normalize("NFD", texte or "")
    sans_accents = "".join(c for c in sans_accents if unicodedata.category(c) != "Mn")
    return sans_accents.casefold().strip()


def _est_diffusee(note):
    """Une note est « diffusée » si elle est partagée avec la classe ou si un autre élève que son
    auteur en a déjà une carte. Sert à distinguer les cartes déjà en circulation de celles que
    le professeur est seul à avoir (et n'a pas encore partagées)."""
    if note.partagee_avec_classe:
        return True
    return Card.objects.filter(note=note).exclude(etudiant_id=note.cree_par_id).exists()


def _classer_outils_math(note, chapitres):
    """Outils mathématiques, sans tags : ce qui est déjà diffusé = Équations différentielles ;
    ce que seul le professeur a (cartes sur les complexes ajoutées depuis) = Complexes."""
    return chapitres[1] if _est_diffusee(note) else chapitres[2]


# (matière, partie) -> fonction(note, chapitres) -> nom du paquet. Pour les parties dont les
# cartes ne portent pas de tags Chap.N ; sinon on range d'après les tags.
CLASSEURS = {
    ("physique", "Outils mathématiques"): _classer_outils_math,
}


def chapitre_de(note):
    """Numéro du chapitre d'après le tag « Chap.N » de la note, ou None."""
    numeros = [int(n) for n in _RE_TAG_CHAPITRE.findall(note.tags or "")]
    return min(numeros) if numeros else None


class Command(BaseCommand):
    help = "Range les cartes d'une partie dans un paquet par chapitre (tags Chap.N). Simulation par défaut."

    def add_arguments(self, parser):
        parser.add_argument("--matiere", default="physique")
        parser.add_argument("--partie", required=True, help="Nom de la partie, ex. « Outils mathématiques ».")
        parser.add_argument("--appliquer", action="store_true", help="Écrire en base (sinon simulation).")

    def handle(self, *args, **options):
        matiere, partie = options["matiere"], options["partie"]
        chapitres = CHAPITRES.get((matiere, partie))
        if chapitres is None:
            self.stderr.write(f"Aucun chapitre configuré pour {matiere} / {partie} (voir CHAPITRES).")
            return
        appliquer = options["appliquer"]

        class _Annuler(Exception):
            pass

        try:
            with transaction.atomic():
                self._migrer(matiere, partie, chapitres, CLASSEURS.get((matiere, partie)))
                if not appliquer:
                    raise _Annuler
        except _Annuler:
            self.stdout.write(self.style.WARNING(
                "\nSIMULATION : rien n'a été écrit. Relancez avec --appliquer pour appliquer."))
            return
        self.stdout.write(self.style.SUCCESS("\nMigration appliquée."))

    def _paquet_cible(self, proprietaire, matiere, partie, nom, cache):
        cle = (proprietaire.pk if proprietaire else None, nom)
        if cle not in cache:
            deck = Deck.objects.filter(cree_par=proprietaire, matiere=matiere, partie=partie, nom=nom).first()
            if deck is None:
                if proprietaire is None:
                    deck = Deck.objects.create(
                        nom=nom, slug=slug_unique(nom), matiere=matiere, partie=partie)
                else:
                    deck = creer_paquet(proprietaire, nom, matiere=matiere, partie=partie)
            cache[cle] = deck
        return cache[cle]

    def _migrer(self, matiere, partie, chapitres, classeur=None):
        sources = [
            d for d in Deck.objects.filter(matiere=matiere, partie="").select_related("cree_par").order_by("id")
            if _normaliser(d.nom) == _normaliser(partie)
        ]
        if not sources:
            self.stdout.write(f"Aucun paquet « {partie} » (matière {matiere}) sans partie : rien à faire.")
            return

        cache = {}
        for source in sources:
            proprietaire = source.cree_par
            cartes = list(Card.objects.filter(deck=source).select_related("note"))
            notes_auteur = list(Note.objects.filter(deck=source))
            titre = f"{proprietaire or 'sans propriétaire'} — {len(cartes)} carte(s), {len(notes_auteur)} note(s) d'auteur"
            self.stdout.write(f"\n« {source.nom} » de {titre}")

            def nom_cible(note):
                if classeur is not None:
                    return classeur(note, chapitres)
                numero = chapitre_de(note)
                return chapitres.get(numero, NOM_PAQUET_AUTRES)

            repartition = {}
            sans_tag = []
            a_lister = []  # (nom du paquet, note) : cartes à montrer en simulation si on trie sans tags
            for carte in cartes:
                nom = nom_cible(carte.note)
                cible = self._paquet_cible(proprietaire, matiere, partie, nom, cache)
                if carte.deck_id != cible.id:
                    carte.deck = cible
                    carte.save(update_fields=["deck"])
                repartition[nom] = repartition.get(nom, 0) + 1
                if nom == NOM_PAQUET_AUTRES:
                    sans_tag.append(carte.note)
                if classeur is not None and nom == chapitres[2]:
                    a_lister.append(carte.note)
            for note in notes_auteur:
                cible = self._paquet_cible(proprietaire, matiere, partie, nom_cible(note), cache)
                Note.objects.filter(pk=note.pk).update(deck=cible)

            for nom in list(chapitres.values()) + [NOM_PAQUET_AUTRES]:
                if nom in repartition:
                    self.stdout.write(f"   {nom} : {repartition[nom]} carte(s)")
            if sans_tag:
                self.stdout.write(self.style.WARNING(
                    f"   {len(sans_tag)} carte(s) sans tag Chap.N reconnu → « {NOM_PAQUET_AUTRES} » :"))
                for note in sans_tag[:30]:
                    self.stdout.write(f"      - {strip_tags(note.question)[:70]}  [tags : {note.tags or '—'}]")
                if len(sans_tag) > 30:
                    self.stdout.write(f"      … et {len(sans_tag) - 30} autre(s)")

            if a_lister:
                self.stdout.write(self.style.WARNING(
                    f"   {len(a_lister)} carte(s) rangée(s) dans « {chapitres[2]} » (non diffusées) :"))
                for note in a_lister[:30]:
                    self.stdout.write(f"      - {strip_tags(note.question)[:70]}")
                if len(a_lister) > 30:
                    self.stdout.write(f"      … et {len(a_lister) - 30} autre(s)")

            if not Card.objects.filter(deck=source).exists() and not Note.objects.filter(deck=source).exists():
                source.delete()
                self.stdout.write("   ancien paquet supprimé (vide)")
            else:
                self.stdout.write("   ancien paquet conservé (il reste du contenu)")
