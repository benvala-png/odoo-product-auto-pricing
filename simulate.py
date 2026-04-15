#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulation standalone de la logique product_auto_pricing.
Aucune dépendance Odoo requise.
"""

from datetime import datetime


# ---------------------------------------------------------------------------
# Modèles simplifiés (mock Odoo)
# ---------------------------------------------------------------------------

class SupplierInfo:
    def __init__(self, name, price, is_promo=False):
        self.partner_name = name
        self.price = price
        self.is_promo_price = is_promo

    def __repr__(self):
        promo = " [PROMO]" if self.is_promo_price else ""
        return f"{self.partner_name}: {self.price:.2f}€{promo}"


class ProductCategory:
    def __init__(self, name, margin_percent=30.0):
        self.name = name
        self.x_margin_percent = margin_percent


class ProductTemplate:
    def __init__(self, name, category, auto_pricing=True):
        self.name = name
        self.categ_id = category
        self.x_auto_pricing_enabled = auto_pricing
        self.seller_ids = []
        self.standard_price = 0.0
        self.list_price = 0.0
        self.x_last_auto_cost = 0.0
        self.x_last_auto_price = 0.0
        self.x_last_auto_supplier_id = None
        self.x_last_auto_date = None

    def add_supplier(self, name, price, is_promo=False):
        self.seller_ids.append(SupplierInfo(name, price, is_promo))
        return self

    def _compute_auto_price(self):
        """Réplique exacte de la logique Odoo."""
        if not self.x_auto_pricing_enabled:
            return "auto-pricing désactivé"

        sellerinfos = [s for s in self.seller_ids if s.price > 0 and not s.is_promo_price]
        if not sellerinfos:
            return "aucun prix non-promo disponible"

        cheapest = min(sellerinfos, key=lambda s: s.price)
        cost = cheapest.price
        margin = self.categ_id.x_margin_percent or 0.0
        new_price = round(cost * (1 + margin / 100.0), 2)

        changed = False
        if abs((self.standard_price or 0.0) - cost) > 0.0001:
            self.standard_price = cost
            changed = True
        if abs((self.list_price or 0.0) - new_price) > 0.0001:
            self.list_price = new_price
            changed = True

        if changed:
            self.x_last_auto_cost = cost
            self.x_last_auto_price = new_price
            self.x_last_auto_supplier_id = cheapest.partner_name
            self.x_last_auto_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return "prix mis à jour"
        return "aucun changement (prix déjà correct)"


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

def run(product):
    SEP = "-" * 52
    print(f"\n{'=' * 52}")
    print(f"  Produit   : {product.name}")
    print(f"  Catégorie : {product.categ_id.name}  "
          f"(marge {product.categ_id.x_margin_percent}%)")
    print(f"  Fournisseurs :")
    for s in product.seller_ids:
        print(f"    • {s}")
    print(SEP)

    result = product._compute_auto_price()
    print(f"  Résultat  : {result}")
    print(SEP)
    print(f"  standard_price (coût)   : {product.standard_price:.2f} €")
    print(f"  list_price (vente)      : {product.list_price:.2f} €")
    print(f"  Fournisseur retenu      : {product.x_last_auto_supplier_id or '—'}")
    print(f"  Date calcul             : {product.x_last_auto_date or '—'}")
    print(f"{'=' * 52}")


# ---------------------------------------------------------------------------
# Scénarios de test
# ---------------------------------------------------------------------------

cat_informatique = ProductCategory("Informatique", margin_percent=30.0)
cat_bureau       = ProductCategory("Bureautique",  margin_percent=15.0)
cat_vide         = ProductCategory("Sans marge",   margin_percent=0.0)

# Scénario 1 : cas nominal — 3 fournisseurs, le moins cher est retenu
p1 = ProductTemplate("Clavier mécanique", cat_informatique)
p1.add_supplier("Fournisseur A", 45.00)
p1.add_supplier("Fournisseur B", 38.50)   # ← moins cher
p1.add_supplier("Fournisseur C", 52.00)
run(p1)

# Scénario 2 : prix promo ignoré — le 2e moins cher doit être retenu
p2 = ProductTemplate("Souris sans fil", cat_informatique)
p2.add_supplier("Fournisseur A", 12.00, is_promo=True)  # promo → ignoré
p2.add_supplier("Fournisseur B", 18.00)                 # ← retenu
p2.add_supplier("Fournisseur C", 22.00)
run(p2)

# Scénario 3 : tous les prix sont promo → aucun calcul
p3 = ProductTemplate("Écran 27\"", cat_informatique)
p3.add_supplier("Fournisseur A", 150.00, is_promo=True)
p3.add_supplier("Fournisseur B", 145.00, is_promo=True)
run(p3)

# Scénario 4 : auto-pricing désactivé
p4 = ProductTemplate("Imprimante laser", cat_bureau, auto_pricing=False)
p4.add_supplier("Fournisseur A", 89.00)
run(p4)

# Scénario 5 : marge à 0% → prix de vente = coût
p5 = ProductTemplate("Ramette papier", cat_vide)
p5.add_supplier("Fournisseur A", 4.99)
run(p5)

# Scénario 6 : prix déjà correct → pas de mise à jour de l'audit
p6 = ProductTemplate("Stylo bille", cat_bureau)
p6.add_supplier("Fournisseur A", 1.00)
p6.standard_price = 1.00
p6.list_price = round(1.00 * 1.15, 2)
run(p6)
