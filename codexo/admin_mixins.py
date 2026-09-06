import re

from django.forms.widgets import SelectMultiple


class SimplifieIndicationCtrlMixin:
    """Django ajoute automatiquement, à tout champ ManyToMany affiché en liste à sélection
    multiple (y compris avec filter_horizontal — ce n'est pas réservé au simple menu
    déroulant), une mention de la touche "Ctrl" (ou "Cmd"/"Commande (touche pomme)" sur un
    Mac) pour sélectionner plusieurs éléments à la fois. La mention Ctrl elle-même reste
    utile : on la garde partout, mais sans le rappel Mac hors-sujet ici (voir la discussion
    du 06/09/2026 sur l'admin — signalé d'abord sur "Visibilité par classe", retrouvé
    ensuite à l'identique sur "Groupes"/"Permissions de l'utilisateur").

    Deux façons de s'en servir, selon qu'il reste ou non un texte utile à préserver :

    - CHAMPS_AVEC_INDICATION_CTRL_SIMPLIFIEE + INDICATION_CTRL_SIMPLIFIEE : remplace
      ENTIÈREMENT le help_text par un texte court — pour un champ qui n'a par ailleurs
      aucun help_text (ex: Theme/Exercise.enabled_for_classes, où seule la mention
      Ctrl/Mac générée par Django existait avant).
    - CHAMPS_AVEC_MENTION_MAC_A_RETIRER : ne retire QUE le rappel Mac, en conservant le
      reste du help_text généré par Django (ex: User.groups/user_permissions, dont la
      première phrase — "Les groupes dont fait partie cet utilisateur...", etc. — est
      utile et ne doit pas disparaître).
    """

    CHAMPS_AVEC_INDICATION_CTRL_SIMPLIFIEE = ()
    INDICATION_CTRL_SIMPLIFIEE = "Maintenir la touche Ctrl enfoncée pour en sélectionner plusieurs."

    CHAMPS_AVEC_MENTION_MAC_A_RETIRER = ()
    # Motif tolérant aux espaces insécables que Django met autour des guillemets français
    # (« Commande (touche pomme) » n'est pas séparé de ses guillemets par de vraies espaces
    # normales, un simple .replace() sur du texte "recopié à l'œil" échoue silencieusement).
    _MENTION_MAC_RE = re.compile(r",\s*ou\s*«\s*Commande \(touche pomme\)\s*»\s*sur un Mac,")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        formfield = super().formfield_for_manytomany(db_field, request, **kwargs)
        if not isinstance(formfield.widget, SelectMultiple):
            return formfield
        if db_field.name in self.CHAMPS_AVEC_INDICATION_CTRL_SIMPLIFIEE:
            formfield.help_text = self.INDICATION_CTRL_SIMPLIFIEE
        elif db_field.name in self.CHAMPS_AVEC_MENTION_MAC_A_RETIRER:
            formfield.help_text = self._MENTION_MAC_RE.sub("", str(formfield.help_text))
        return formfield
