# -*- coding: utf-8 -*-
"""
Système d'adaptateurs pour importer les tarifs fournisseurs (xlsx)
vers le format product.supplierinfo d'Odoo.

Chaque fournisseur a son propre adaptateur qui déclare :
  - le nom des colonnes dans son fichier
  - l'index de l'onglet et de la ligne d'en-tête
  - les éventuelles surcharges de parsing

Format normalisé en sortie (une ligne = un prix fournisseur) :
  {
    "ean":           str,   # EAN-13 (clé de matching Odoo)
    "supplier_name": str,
    "price":         float,
    "is_promo":      bool,
    "min_qty":       float,
  }
"""

import re
import openpyxl


# ---------------------------------------------------------------------------
# Classe de base
# ---------------------------------------------------------------------------

class BaseSupplierImporter:
    """
    Surcharger les attributs de classe pour configurer un fournisseur.
    Surcharger les méthodes parse_* pour des formats non standards.
    """

    supplier_name: str = ""   # affiché dans les logs et le résultat
    sheet_index:   int = 0    # index de l'onglet (0 = premier)
    header_row:    int = 0    # index de la ligne d'en-tête (0-based)

    # Noms de colonnes dans le fichier du fournisseur
    ean_col:       str = ""
    price_col:     str = ""
    promo_col:     str | None = None   # colonne optionnelle
    min_qty_col:   str | None = None   # colonne optionnelle

    # -------------------------------------------------------------------
    # Parsing des valeurs (surcharger si format non standard)
    # -------------------------------------------------------------------

    def parse_ean(self, value) -> str | None:
        """Retourne l'EAN sous forme de chaîne, ou None si invalide."""
        if value is None:
            return None
        s = str(value).strip().split(".")[0]   # retire la décimale si int lu comme float
        s = re.sub(r"[^\d]", "", s)            # garde uniquement les chiffres
        if not s:
            return None
        return s.zfill(13)                     # zero-pad à 13 chiffres

    def parse_price(self, value) -> float | None:
        """Retourne le prix en float, ou None si invalide."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        # Gère "38,50 €" / "38.50 EUR" / "38,50"
        s = str(value).replace(",", ".").strip()
        s = re.sub(r"[^\d.]", "", s)
        try:
            return float(s)
        except ValueError:
            return None

    def parse_promo(self, value) -> bool:
        """Retourne True si le prix est marqué promo."""
        if value is None:
            return False
        s = str(value).strip().lower()
        return s in ("oui", "yes", "true", "1", "x", "promo")

    def parse_min_qty(self, value) -> float:
        price = self.parse_price(value)
        return price if price is not None else 1.0

    # -------------------------------------------------------------------
    # Chargement
    # -------------------------------------------------------------------

    def load(self, filepath: str) -> list[dict]:
        """
        Lit le fichier xlsx et retourne une liste de dicts normalisés.
        Les lignes sans EAN valide ou sans prix valide sont ignorées (avec warning).
        """
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.worksheets[self.sheet_index]
        rows = list(ws.iter_rows(values_only=True))

        if self.header_row >= len(rows):
            raise ValueError(f"header_row={self.header_row} dépasse le nombre de lignes ({len(rows)})")

        headers = [str(h).strip() if h is not None else "" for h in rows[self.header_row]]

        def col(name):
            try:
                return headers.index(name)
            except ValueError:
                raise ValueError(
                    f"[{self.supplier_name}] Colonne introuvable : '{name}'\n"
                    f"  Colonnes disponibles : {headers}"
                )

        idx_ean   = col(self.ean_col)
        idx_price = col(self.price_col)
        idx_promo = col(self.promo_col)   if self.promo_col   else None
        idx_qty   = col(self.min_qty_col) if self.min_qty_col else None

        results = []
        skipped = 0

        for row in rows[self.header_row + 1:]:
            ean   = self.parse_ean(row[idx_ean])
            price = self.parse_price(row[idx_price])

            if not ean or price is None or price <= 0:
                skipped += 1
                continue

            results.append({
                "ean":           ean,
                "supplier_name": self.supplier_name,
                "price":         price,
                "is_promo":      self.parse_promo(row[idx_promo]) if idx_promo is not None else False,
                "min_qty":       self.parse_min_qty(row[idx_qty]) if idx_qty is not None else 1.0,
            })

        if skipped:
            print(f"  ⚠  [{self.supplier_name}] {skipped} ligne(s) ignorée(s) (EAN ou prix manquant)")

        return results


# ---------------------------------------------------------------------------
# Adaptateurs fournisseurs
# ---------------------------------------------------------------------------

class FournisseurAlpha(BaseSupplierImporter):
    """
    Format : onglet 1, en-têtes ligne 1
    Colonnes : Code EAN | Désignation | Prix HT | Promotion | Qté mini
    Prix au format float standard.
    """
    supplier_name = "Fournisseur Alpha"
    ean_col       = "Code EAN"
    price_col     = "Prix HT"
    promo_col     = "Promotion"
    min_qty_col   = "Qté mini"


class FournisseurBeta(BaseSupplierImporter):
    """
    Format : onglet 2 (index 1), en-têtes ligne 3 (index 2)
    Colonnes : GTIN | Libellé | Tarif | Offre spéciale
    Prix au format "38,50 EUR" (virgule + devise).
    """
    supplier_name = "Fournisseur Beta"
    sheet_index   = 1
    header_row    = 2
    ean_col       = "GTIN"
    price_col     = "Tarif"
    promo_col     = "Offre spéciale"

    def parse_price(self, value) -> float | None:
        """Format spécifique : "38,50 EUR" """
        if value is None:
            return None
        s = str(value).replace(",", ".").replace("EUR", "").strip()
        try:
            return float(s)
        except ValueError:
            return None


class FournisseurGamma(BaseSupplierImporter):
    """
    Format : onglet 1, en-têtes ligne 1
    Colonnes : ean | product_name | unit_price
    Pas de colonne promo. EAN parfois sans zéros initiaux.
    """
    supplier_name = "Fournisseur Gamma"
    ean_col       = "ean"
    price_col     = "unit_price"


# ---------------------------------------------------------------------------
# Registre : associe un nom de fournisseur à son adaptateur
# ---------------------------------------------------------------------------

IMPORTERS: dict[str, BaseSupplierImporter] = {
    "alpha": FournisseurAlpha(),
    "beta":  FournisseurBeta(),
    "gamma": FournisseurGamma(),
}
