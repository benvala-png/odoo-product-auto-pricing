# product_auto_pricing (Odoo 16)

Addon Odoo 16 qui calcule automatiquement le prix de vente d'un produit à partir du **fournisseur le moins cher** (hors promo) et de la **marge définie par catégorie**.

---

## Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| Marge par catégorie | Chaque catégorie produit peut définir un taux de marge (%) appliqué automatiquement |
| Prix promo fournisseur | Un prix fournisseur peut être marqué "promo" pour être ignoré dans le calcul |
| Auto-pricing par produit | L'auto-pricing peut être activé/désactivé produit par produit |
| Bouton manuel | Recalcul immédiat depuis la fiche produit |
| Cron automatique | Recalcul planifiable quotidiennement (désactivé par défaut) |
| Audit | Dernier coût, prix, fournisseur choisi et date du calcul sont enregistrés |

---

## Installation

1. Copier le dossier `product_auto_pricing` dans un répertoire présent dans `addons_path`
2. Redémarrer Odoo
3. **Apps > Mettre à jour la liste des applications**
4. Rechercher `Product Auto Pricing` et cliquer sur **Installer**

**Dépendances :** module `product` (inclus dans Odoo)

---

## Configuration

### 1. Marge par catégorie

`Inventaire > Configuration > Catégories de produits` (ou via le formulaire produit)

- Ouvrir une catégorie
- Renseigner le champ **Marge automatique (%)** (défaut : 30 %)

### 2. Prix promo fournisseur

Sur la fiche produit, onglet **Achat** :

- Ouvrir une ligne fournisseur
- Cocher **Prix promo** pour exclure ce prix du calcul automatique

### 3. Activer l'auto-pricing sur un produit

Sur la fiche produit, groupe **Auto-pricing** :

- Cocher **Auto-pricing activé**
- Cliquer sur **Recalculer le prix (auto)** pour un calcul immédiat

### 4. Activer le cron

`Paramètres > Technique > Actions planifiées > Auto-pricing (cheapest supplier + margin)`

- Activer l'action et ajuster la fréquence si besoin (défaut : 1 jour)

---

## Logique de calcul

```
prix_vente = coût_fournisseur_min × (1 + marge_catégorie / 100)
```

1. Récupère tous les prix fournisseurs du produit où `price > 0` et `is_promo_price = False`
2. Sélectionne le moins cher (`cheapest`)
3. Calcule le nouveau prix de vente avec la marge de la catégorie
4. Met à jour `standard_price` (coût) et `list_price` (prix de vente) **uniquement si les valeurs changent** (seuil : 0.0001)
5. Enregistre le fournisseur choisi, le coût, le prix et la date dans les champs d'audit

> Si aucun prix non-promo n'existe, le produit est ignoré sans erreur.

---

## Champs ajoutés

### `product.category`

| Champ | Type | Description |
|---|---|---|
| `x_margin_percent` | Float | Marge automatique (%) appliquée au coût fournisseur |

### `product.template`

| Champ | Type | Description |
|---|---|---|
| `x_auto_pricing_enabled` | Boolean | Active le recalcul automatique du prix |
| `x_last_auto_cost` | Float | Dernier coût fournisseur utilisé |
| `x_last_auto_price` | Float | Dernier prix de vente calculé |
| `x_last_auto_supplier_id` | Many2one | Dernier fournisseur le moins cher retenu |
| `x_last_auto_date` | Datetime | Date et heure du dernier calcul ayant modifié le prix |

### `product.supplierinfo`

| Champ | Type | Description |
|---|---|---|
| `is_promo_price` | Boolean | Exclut ce prix du calcul automatique |

---

## Structure du module

```
product_auto_pricing/
├── __init__.py
├── __manifest__.py
├── data/
│   └── ir_cron_auto_pricing.xml   # Action planifiée (désactivée par défaut)
├── models/
│   ├── __init__.py
│   └── product_auto_pricing.py    # Modèles : SupplierInfo, ProductCategory, ProductTemplate
└── views/
    ├── product_category_view.xml  # Ajout du champ marge sur la catégorie
    └── product_template_view.xml  # Groupe auto-pricing + vue supplierinfo
```
