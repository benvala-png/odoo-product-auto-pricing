# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    # ------------------------------------------------------------
    # CALCUL PRINCIPAL DU PRIX AUTO
    # ------------------------------------------------------------
    def _compute_auto_price_for_templates(self):
        for template in self:
            if not template.x_auto_pricing_enabled:
                continue

            # ✨ On ignore les prix promo !
            sellerinfos = template.seller_ids.filtered(
                lambda s: s.price > 0 and not s.is_promo_price
            )
            if not sellerinfos:
                # Aucun prix non-promo → on ne fait rien
                continue

            # Chercher le fournisseur non promo le moins cher
            cheapest = min(sellerinfos, key=lambda s: s.price)
            cost = cheapest.price

            margin = template.categ_id.x_margin_percent or 0.0
            new_price = round(cost * (1 + margin / 100.0), 2)

            changed = False

            # Mise à jour du coût réel du produit
            if abs((template.standard_price or 0.0) - cost) > 0.0001:
                template.standard_price = cost
                changed = True

            # Mise à jour du prix de vente réel
            if abs((template.list_price or 0.0) - new_price) > 0.0001:
                template.list_price = new_price
                changed = True

            if changed:
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
