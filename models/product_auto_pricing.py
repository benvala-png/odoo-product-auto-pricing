# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_MARGIN_PERCENT = 30.0  # marge appliquée si la catégorie n'en définit pas


# ------------------------------------------------------------
# Extension de product.supplierinfo : ajout d'un flag "promo"
# ------------------------------------------------------------
class SupplierInfo(models.Model):
    _inherit = "product.supplierinfo"

    is_promo_price = fields.Boolean(
        string="Prix promo",
        help="Ce prix provient d'une promo fournisseur et ne doit pas "
             "être utilisé pour le calcul automatique du prix de vente.",
        default=False,
    )


# ------------------------------------------------------------
# Catégorie produit (marge auto)
# ------------------------------------------------------------
class ProductCategory(models.Model):
    _inherit = "product.category"

    x_margin_percent = fields.Float(
        string="Marge automatique (%)",
        help="Marge appliquée automatiquement sur le fournisseur le moins cher.",
        default=30.0,
    )
    x_margin_zero_confirmed = fields.Boolean(
        string="Marge à 0% volontaire",
        help="À cocher si cette catégorie doit vraiment être vendue sans marge "
             "(ex. consignes). Sans cette case, une marge à 0% est traitée comme "
             "'non configurée' et remplacée par la marge par défaut "
             f"({DEFAULT_MARGIN_PERCENT:g}%) lors du calcul auto.",
        default=False,
    )


# ------------------------------------------------------------
# Template produit (auto-pricing)
# ------------------------------------------------------------
class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_auto_pricing_enabled = fields.Boolean(
        string="Auto-pricing activé",
        help="Recalcule automatiquement le prix de vente depuis le coût fournisseur.",
        default=False,
    )
    x_last_auto_cost = fields.Float(string="Dernier coût auto", readonly=True)
    x_last_auto_price = fields.Float(string="Dernier prix auto", readonly=True)
    x_last_auto_supplier_id = fields.Many2one(
        "res.partner", string="Dernier fournisseur choisi", readonly=True
    )
    x_last_auto_date = fields.Datetime(
        string="Date du dernier calcul auto", readonly=True
    )

    # ── Écran « Prix de vente à revoir » ──────────────────────────────────
    # Depuis le 2026-08-24, valider un prix d'achat ne recalcule plus le prix
    # de vente : une étiquette non réimprimée ferait diverger le prix affiché
    # en rayon et le prix encaissé. Le repricing est devenu un geste explicite
    # — encore faut-il savoir sur quoi le poser, d'où ces trois champs.
    x_auto_price_target = fields.Float(
        string="Prix de vente auto (cible)", digits="Product Price",
        compute="_compute_auto_price_gap",
        help="Ce que la règle donnerait aujourd'hui : fournisseur non-promo le "
             "moins cher x marge de la catégorie.")
    x_auto_price_gap = fields.Float(
        string="Écart au prix affiché", digits="Product Price",
        compute="_compute_auto_price_gap")
    x_auto_price_stale = fields.Boolean(
        string="Prix de vente à revoir", compute="_compute_auto_price_gap",
        search="_search_auto_price_stale",
        help="Le prix de vente affiché ne correspond plus à la règle "
             "auto-pricing. À recalculer, puis à réimprimer.")

    # La règle arrondit au cent : comparer plus fin ne ferait que signaler du
    # bruit de virgule flottante.
    _AUTO_PRICE_TOL = 0.005

    @api.depends("x_auto_pricing_enabled", "list_price", "categ_id",
                 "seller_ids.price", "seller_ids.is_promo_price")
    def _compute_auto_price_gap(self):
        for template in self:
            cible = template._auto_price_target()
            if not cible:
                template.x_auto_price_target = 0.0
                template.x_auto_price_gap = 0.0
                template.x_auto_price_stale = False
                continue
            _cost, prix, _fournisseur = cible
            template.x_auto_price_target = prix
            template.x_auto_price_gap = prix - (template.list_price or 0.0)
            template.x_auto_price_stale = (
                abs(template.x_auto_price_gap) > template._AUTO_PRICE_TOL)

    def _search_auto_price_stale(self, operator, value):
        """Champ calculé non stocké : sans cette méthode il ne serait pas
        filtrable, donc l'écran serait impossible. Le parcours reste peu coûteux
        — seuls les produits en auto-pricing sont candidats (66 sur 2 354 au
        2026-08-24), pas tout le catalogue."""
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Filtre non supporté sur « Prix de vente à revoir »."))
        candidats = self.search([("x_auto_pricing_enabled", "=", True)])
        ids = [t.id for t in candidats if t.x_auto_price_stale]
        positif = (operator == "=") == value
        return [("id", "in" if positif else "not in", ids)]

    def _action_print_labels(self):
        """Assistant d'impression d'étiquettes, pré-rempli sur `self`.

        Le format « 3x7xprice » (étiquette de rayon : nom, code-barres, prix)
        vient de `product_label_extra_format`, qui dépend de CE module — donc
        jamais l'inverse. On ne le présélectionne que s'il est réellement
        installé, sinon le défaut du core s'applique.
        """
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "product.action_open_label_layout")
        contexte = {"default_product_tmpl_ids": self.ids}
        formats = self.env["product.label.layout"]._fields["print_format"].get_values(self.env)
        if "3x7xprice" in formats:
            contexte["default_print_format"] = "3x7xprice"
        action["context"] = contexte
        action["name"] = _("Imprimer les étiquettes (%s article(s))") % len(self)
        return action

    def action_print_labels_selection(self):
        """Bouton « Imprimer les étiquettes » de l'écran « Prix de vente à
        revoir » — pour réimprimer sans repasser par le recalcul (étiquette
        abîmée, prix corrigé à la main)."""
        if not self:
            raise UserError(_("Sélectionne d'abord les articles à étiqueter."))
        return self._action_print_labels()

    def action_recompute_auto_price_selection(self):
        """Recalcul en masse depuis l'écran « Prix de vente à revoir », suivi
        de l'impression des étiquettes des articles dont le prix a bougé.

        Le recalcul les fait sortir du filtre de l'écran : sans enchaînement
        automatique, la sélection est perdue au rechargement et l'étiquette
        périmée reste en rayon — c'est le prix affiché qui ment, pas la caisse.
        On n'imprime QUE les articles dont le prix a réellement changé : les
        autres ont déjà la bonne étiquette, les réimprimer serait du papier
        perdu et un doute sur ce qui est à recoller.
        """
        avant = {t.id: t.list_price for t in self}
        self._compute_auto_price_for_templates()
        bouges = self.filtered(
            lambda t: abs(t.list_price - avant[t.id]) > self._AUTO_PRICE_TOL)
        message = _("%s prix de vente recalculé(s).") % len(bouges)
        suivant = {"type": "ir.actions.act_window_close"}
        if bouges:
            message += "\n- " + "\n- ".join(
                f"{t.name} : {avant[t.id]:.2f} → {t.list_price:.2f}" for t in bouges)
            message += _("\n\nL'impression des étiquettes s'ouvre sur ces "
                         "%s article(s).") % len(bouges)
            suivant = bouges._action_print_labels()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Prix de vente recalculés"), "message": message,
                       "type": "success", "sticky": True,
                       "next": suivant},
        }

    # ------------------------------------------------------------
    # LA RÈGLE, EN UN SEUL ENDROIT
    # ------------------------------------------------------------
    def _auto_price_target(self):
        """Ce que la règle donnerait aujourd'hui : (coût, prix de vente,
        fournisseur retenu), ou None si elle ne s'applique pas.

        Isolée pour que l'écran « Prix de vente à revoir » et le recalcul
        s'appuient sur le MÊME calcul. Dupliquée, la règle aurait dérivé : la
        liste aurait fini par annoncer un prix que le bouton n'aurait pas
        produit.
        """
        self.ensure_one()
        if not self.x_auto_pricing_enabled:
            return None
        sellerinfos = self.seller_ids.filtered(       # ✨ on ignore les promos
            lambda s: s.price > 0 and not s.is_promo_price
        )
        if not sellerinfos:
            return None
        cheapest = min(sellerinfos, key=lambda s: s.price)
        categ = self.categ_id
        if categ.x_margin_percent or categ.x_margin_zero_confirmed:
            margin = categ.x_margin_percent
        else:
            margin = DEFAULT_MARGIN_PERCENT
        return cheapest.price, round(cheapest.price * (1 + margin / 100.0), 2), cheapest

    # ------------------------------------------------------------
    # CALCUL PRINCIPAL DU PRIX AUTO
    # ------------------------------------------------------------
    def _compute_auto_price_for_templates(self):
        for template in self:
            cible = template._auto_price_target()
            if not cible:
                continue
            cost, new_price, cheapest = cible

            changed = False

            # Mise à jour du coût réel du produit
            if abs((template.standard_price or 0.0) - cost) > 0.0001:
                template.standard_price = cost
                changed = True

            # Mise à jour du prix de vente réel
            if abs((template.list_price or 0.0) - new_price) > 0.0001:
                template.list_price = new_price
                changed = True

            # Le suivi doit refléter le dernier calcul RÉUSSI, pas seulement
            # ceux qui ont modifié un prix. Un produit déjà au bon prix restait
            # sans fournisseur ni date : impossible de distinguer « calculé,
            # déjà correct » de « jamais traité », y compris sur l'étiquette 3x7
            # qui imprime « Fourn: » et « MAJ: ».
            #
            # On compare le suivi aux valeurs calculées plutôt que d'estampiller
            # systématiquement : sans ça, le cron quotidien réécrirait chaque
            # jour tous les produits en auto-pricing, pour rien.
            suivi_obsolete = (
                abs((template.x_last_auto_cost or 0.0) - cost) > 0.0001
                or abs((template.x_last_auto_price or 0.0) - new_price) > 0.0001
                or template.x_last_auto_supplier_id != cheapest.partner_id
            )

            if changed or suivi_obsolete:
                template.x_last_auto_cost = cost
                template.x_last_auto_price = new_price
                template.x_last_auto_supplier_id = cheapest.partner_id
                template.x_last_auto_date = fields.Datetime.now()

    # ------------------------------------------------------------
    # Bouton manuel
    # ------------------------------------------------------------
    def action_recompute_auto_price(self):
        self._compute_auto_price_for_templates()
        return True

    # ------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------
    @api.model
    def _cron_recompute_auto_prices(self):
        products = self.search([
            ("x_auto_pricing_enabled", "=", True),
            ("active", "=", True)
        ])
        products._compute_auto_price_for_templates()
