# 📋 Documentation technique — `odoo-product-auto-pricing`

**Module Odoo 16 Community** qui calcule automatiquement le prix de vente d'un produit à partir du fournisseur le moins cher (hors promo) et de la marge définie par catégorie.

---

## 🎯 Objectif

**Formule :** `prix_vente = coût_min_hors_promo × (1 + marge_catégorie / 100)`

---

## 🏗️ Architecture

### Modèles Odoo étendus

| Modèle | Champ ajouté | Type | Rôle |
|--------|--------------|------|------|
| `product.supplierinfo` | `is_promo_price` | Boolean | Exclut ce prix du calcul |
| `product.category` | `x_margin_percent` | Float (défaut 30%) | Marge appliquée |
| `product.template` | `x_auto_pricing_enabled` | Boolean | Active le recalcul |
| `product.template` | `x_last_auto_cost` | Float (readonly) | Audit |
| `product.template` | `x_last_auto_price` | Float (readonly) | Audit |
| `product.template` | `x_last_auto_supplier_id` | M2O res.partner (readonly) | Audit |
| `product.template` | `x_last_auto_date` | Datetime (readonly) | Audit |

### Méthodes principales

- `_compute_auto_price_for_templates()` — logique de calcul (filtre promo, min, marge)
- `action_recompute_auto_price()` — bouton manuel sur fiche produit
- `_cron_recompute_auto_prices()` — cron quotidien (désactivé par défaut)

### Vues XML

| Vue | Héritage | Rôle |
|-----|----------|------|
| `view_supplierinfo_form_auto_pricing` | `product.product_supplierinfo_form_view` | Ajoute `is_promo_price` au form |
| `view_supplierinfo_tree_auto_pricing` | `product.product_supplierinfo_tree_view` | Ajoute colonne `is_promo_price` optionnelle dans le tableau |
| `view_product_template_form_auto_pricing` | `product.product_template_form_view` | Groupe "Auto-pricing" avec champs audit + bouton |
| `product_category_view` | Vue catégorie | Ajoute champ `x_margin_percent` |

### Cron

- **ID :** `ir_cron_auto_pricing`
- **Fréquence :** quotidien
- **Modèle cible :** `product.template`
- **Méthode :** `model._cron_recompute_auto_prices()`
- **État par défaut :** désactivé (`active=False`)

---

## 📂 Structure du repo

```
odoo-product-auto-pricing/
├── __init__.py
├── __manifest__.py          # v16.0.1.0.0, depends=["product"]
├── README.md
├── DOCS.md                  # Ce fichier
├── simulate.py              # Simulation standalone (0 dépendance)
├── data/
│   └── ir_cron_auto_pricing.xml
├── models/
│   ├── __init__.py
│   └── product_auto_pricing.py
├── views/
│   ├── product_category_view.xml
│   └── product_template_view.xml
└── tools/                   # Outils externes (pas encore connectés à Odoo)
    ├── importers.py         # Adaptateurs XLSX (Alpha, Beta, Gamma)
    ├── simulate_import.py
    ├── scraper_biofresh.py  # Playwright, login + fetch
    └── sample_data/*.xlsx
```

---

## ✅ Tests validés

| Scénario | Résultat |
|----------|----------|
| Installation du module sur IPELLE | ✅ OK |
| Création catégorie avec marge | ✅ Visible, éditable |
| Champ `is_promo_price` dans tableau fournisseurs | ✅ Visible (après patch vue tree) |
| Bouton "Recalculer le prix (auto)" | ✅ Fonctionnel |
| Calcul avec 2 fournisseurs | ✅ Coût min retenu |
| Exclusion prix promo | ✅ Fournisseur promo ignoré |
| Champs audit remplis | ✅ Supplier / cost / price / date |
| Simulation standalone (6 scénarios) | ✅ Tous passent |

**Test en production sur IPELLE (24/04/2026) :**
- Produit : "Test pomme"
- Catégorie : "Test Auto-Pricing" (marge 1000% pour amplifier)
- Fournisseurs : BIODYVINO (2€), BIOFLORE (3€)
- Résultat : 2 × 11 = 22€ ✅

---

## 🔧 Déploiement

### Environnement de production

- **Serveur :** Raspberry Pi 4 (Ubuntu 22.04)
- **Odoo :** 16 Community via Docker
- **DB :** PostgreSQL 14, base `IPELLE`
- **Container Odoo :** `odoo16-odoo-1`
- **Container DB :** `odoo16-db-1`
- **Emplacement module :** `/home/Benjamin/odoo16/extra-addons/odoo-product-auto-pricing/`

### Commandes de maintenance

```bash
# Upgrade le module après modif XML
docker exec odoo16-odoo-1 odoo -u odoo-product-auto-pricing -d IPELLE --stop-after-init

# Redémarrer Odoo
cd /home/Benjamin/odoo16 && docker compose restart odoo

# Vérifier installation
docker exec odoo16-db-1 psql -U odoo -d IPELLE -c "
SELECT name, state, latest_version
FROM ir_module_module
WHERE name = 'odoo-product-auto-pricing';
"

# Vérifier champ is_promo_price en DB
docker exec odoo16-db-1 psql -U odoo -d IPELLE -c "
SELECT column_name FROM information_schema.columns
WHERE table_name = 'product_supplierinfo' AND column_name = 'is_promo_price';
"
```

---

## 📌 Points d'attention

### Nom technique confus

Il existe **deux noms** très similaires :
- ✅ **`odoo-product-auto-pricing`** — celui qui tourne en prod sur IPELLE
- ❌ `product_auto_pricing` — ancien nom, ne pas confondre

### Patch vue tree (ajouté le 24/04/2026)

Le champ `is_promo_price` était initialement uniquement dans la vue **form** de `product.supplierinfo`. Un patch a été ajouté pour l'afficher aussi dans la vue **tree** (tableau inline dans l'onglet Achat du produit) avec `optional="show"`.

---

## 🚧 Roadmap — Ce qui n'est PAS fait

| Composant | Priorité |
|-----------|----------|
| Script d'import RPC (Biofresh → `supplierinfo`) | 🔴 Haute |
| Intégration scraper Biofresh dans IMPORTERS | 🟠 Moyenne |
| Matching EAN / LEAN (code-barres) dans Odoo | 🟠 Moyenne |
| Wizard Odoo d'import XLSX | 🟡 Basse |
| Tests unitaires | 🟡 Basse |
| Activer le cron en prod (après validation) | 🔴 À faire |
| Marge par défaut à ajuster (30% ≠ 1000%) | 🔴 À faire |

---

## 📝 Historique Git

- **Repo :** `github.com/benvala-png/odoo-product-auto-pricing`
- **PR #1 :** Implémentation initiale + patch vue tree — mergée via squash le 24/04/2026

---

*Dernière mise à jour : 24 avril 2026*
