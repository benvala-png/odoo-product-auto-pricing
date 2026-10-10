# product_auto_pricing (Odoo 16)

> **In English —** Small shops change supplier prices all the time, and sale prices drift out of line. This module computes each product's sale price from its cheapest non-promo supplier plus a per-category margin, flags every product whose price no longer matches the rule, and lets staff recompute and reprint shelf labels in one step. It never silently overwrites a price.

*Documentation below is in French.*

Addon Odoo 16 qui calcule le prix de vente d'un produit à partir du
**fournisseur le moins cher** (hors promo) et de la **marge définie par
catégorie**, et signale quand un prix affiché ne correspond plus à cette
règle — sans jamais le corriger tout seul en silence.

---

## Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| Marge par catégorie | Chaque catégorie produit définit un taux de marge (%), appliqué au coût fournisseur le plus bas |
| Prix promo fournisseur | Une ligne fournisseur peut être marquée « Prix promo » pour être ignorée du calcul |
| Auto-pricing par produit | Recalcul automatique activable/désactivable article par article |
| Bouton manuel | Recalcul immédiat depuis la fiche produit |
| Cron quotidien | Recalcule le coût **et** le prix de vente des articles inscrits — **désactivé par défaut**, voir « État actuel » |
| Suivi des prix d'achat | Un changement de prix fournisseur (nouveau, hausse, baisse) est marqué au moment où il survient, avec l'ancien et le nouveau prix |
| Le coût suit toujours | `standard_price` (le coût, invisible en rayon) est mis à jour dès qu'un prix d'achat change — que le produit soit ou non en auto-pricing |
| Écran « Prix de vente à revoir » | Liste unique les articles dont le prix d'achat a bougé OU dont le prix de vente ne suit plus la règle ; recalcule et enchaîne l'impression des étiquettes |
| Simulation « et si » | `x_pv_regle` calcule ce que la règle donnerait pour **tout** article, même hors auto-pricing, à titre indicatif |
| Garde-fou d'unités | Le prix simulé est masqué quand le rapport prix de vente / prix d'achat est hors plage plausible (article acheté au carton, vendu à la pièce, ou l'inverse) |
| Audit | Dernier coût, prix, fournisseur choisi et date du dernier calcul réussi sont enregistrés |

---

## État actuel (au 2026-09)

Le cron `Auto-pricing (cheapest supplier + margin)` est **désactivé**
(`active=False` dans `data/ir_cron_auto_pricing.xml`) depuis le 15/08/2026 :
Benjamin l'a coupé pour ne pas avoir à réimprimer et recoller des étiquettes
en continu. Conséquence : sur les articles **hors** auto-pricing (la grande
majorité du catalogue), le coût ne suit plus automatiquement les factures —
c'est pour ça que `_suivre_cout_achat()` (voir plus bas) a été ajoutée en
dehors du chemin auto-pricing.

Seule une minorité de fiches (autour de 80 sur plus de 2300, au dernier
comptage) est inscrite en auto-pricing (`x_auto_pricing_enabled=True`) ; pour
elles, le recalcul reste **manuel**, via le bouton sur la fiche produit ou
l'écran « Prix de vente à revoir ».

---

## Installation

1. Copier le dossier `product_auto_pricing` dans un répertoire présent dans `addons_path`
2. Redémarrer Odoo
3. **Apps > Mettre à jour la liste des applications**
4. Rechercher `Product Auto Pricing` et cliquer sur **Installer**

**Dépendances :** `product` et `purchase` (tous deux inclus dans Odoo)

---

## Configuration

### 1. Marge par catégorie

`Inventaire > Configuration > Catégories de produits` (le même écran existe
sous Achats et sous Facturation)

- Ouvrir une catégorie
- Renseigner **Marge automatique (%)** (défaut : 30 %)
- Une marge à **0 %** doit être confirmée en cochant **Marge à 0% volontaire**
  (`x_margin_zero_confirmed`), sinon elle est traitée comme « non configurée »
  et remplacée par 30 % au calcul — utile pour les consignes, qui doivent
  vraiment être vendues sans marge

### 2. Prix promo fournisseur

Sur la fiche produit, onglet **Achat**, ligne fournisseur : cocher **Prix
promo** pour exclure ce prix du calcul automatique.

### 3. Activer l'auto-pricing sur un produit

Sur la fiche produit, groupe **Auto-pricing** :

- Cocher **Auto-pricing activé**
- Bouton **Recalculer le prix (auto)** pour un calcul immédiat

### 4. Le cron

`Paramètres > Technique > Actions planifiées > Auto-pricing (cheapest
supplier + margin)` — désactivé par défaut, voir « État actuel » ci-dessus.
S'il est réactivé : il écrase silencieusement tout prix de vente corrigé
manuellement sur un produit `x_auto_pricing_enabled=True` — désactiver ce
flag sur un produit dont le prix doit rester fixé à la main.

---

## Logique de calcul

**La règle vit à un seul endroit** : `_pv_regle()`. Toutes les autres
méthodes (recalcul auto, écran « à revoir », bouton manuel) l'appellent —
elle n'est jamais dupliquée, pour ne jamais diverger de ce qu'affiche
réellement l'écran.

```
prix_vente = coût_fournisseur_min_hors_promo × (1 + marge_catégorie / 100)
```

1. Parmi les lignes fournisseur à `price > 0` et `is_promo_price = False`, retient la moins chère
2. Applique la marge de la catégorie (30 % si non configurée et non confirmée à 0 %)
3. `_compute_auto_price_for_templates()` (cron + bouton manuel + recalcul de masse) met à jour `standard_price` et `list_price` **uniquement si les valeurs changent** (seuil 0,0001), et estampille systématiquement le suivi (fournisseur, coût, prix, date) dès que le calcul aboutit — pas seulement s'il modifie un prix, sinon un article déjà au bon prix reste indiscernable d'un article jamais traité (l'étiquette 3×7 de `product_label_extra_format` affiche ce suivi)

> Si aucun prix non-promo n'existe, le produit est ignoré sans erreur.

### Le coût suit les factures, le prix de vente non

Deux mises à jour bien distinctes, déclenchées par `product.supplierinfo.write()` /
`create()` dès qu'un prix fournisseur change réellement (comparé à l'ancienne
valeur, jamais à la date d'écriture — une fiche peut être réécrite sans que
son prix bouge) :

- **Le coût** (`standard_price`) suit **immédiatement**, sur **tout** article,
  inscrit en auto-pricing ou non : il ne se voit pas en rayon, rien à
  réimprimer, aucune écriture comptable. Deux refus, journalisés : unité de la
  fiche différente de celle du produit (pas de conversion devinée), ou coût
  qui dépasserait le prix de vente (signature d'un prix de carton saisi comme
  prix unitaire).
- **Le prix de vente** est une **décision** qui coûte une étiquette : il reste
  manuel. Un changement de prix d'achat marque seulement l'article comme
  `x_achat_a_revoir` — visible dans l'écran « Prix de vente à revoir ».

### L'écran « Prix de vente à revoir »

Deux déclencheurs distincts alimentent la même liste (motif affiché dans la
colonne « Motif », les deux peuvent se cumuler) :

- un **prix d'achat a changé** (nouveau, hausse, ou baisse) ;
- le **prix de vente ne suit plus la règle**, pour un article en auto-pricing.

Recalculer coche les lignes sélectionnées puis enchaîne automatiquement
l'impression des étiquettes des articles dont le prix a réellement bougé
(jamais des autres — pas de papier perdu). **Vu, je garde mon prix** sort une
ligne sans rien modifier, utile pour une baisse de prix d'achat qu'on ne veut
pas répercuter côté client.

---

## Champs ajoutés

### `product.category`

| Champ | Type | Description |
|---|---|---|
| `x_margin_percent` | Float | Marge automatique (%) appliquée au coût fournisseur |
| `x_margin_zero_confirmed` | Boolean | Confirme qu'une marge à 0 % est volontaire (sinon traitée comme « non configurée ») |

### `product.template`

| Champ | Type | Description |
|---|---|---|
| `x_auto_pricing_enabled` | Boolean | Active le recalcul automatique du prix |
| `x_last_auto_cost` / `x_last_auto_price` | Float | Dernier coût / prix calculés par le cron ou le bouton |
| `x_last_auto_supplier_id` | Many2one | Dernier fournisseur le moins cher retenu |
| `x_last_auto_date` | Datetime | Date du dernier calcul **réussi** (même sans changement de prix) |
| `x_achat_a_revoir` | Boolean | Un prix d'achat a changé, le prix de vente n'a pas été revu depuis |
| `x_achat_precedent` / `x_achat_nouveau` | Float | Prix d'achat avant/après le changement signalé |
| `x_achat_variation` | Float (computed, stored) | Variation en % entre avant et après |
| `x_achat_nature` | Selection (computed, stored) | « Prix nouveau » / « Hausse » / « Baisse » |
| `x_achat_change_le` | Datetime | Date du changement de prix d'achat |
| `x_achat_fournisseur_id` | Many2one | Fournisseur à l'origine du changement |
| `x_pv_regle` / `x_pv_regle_ecart` | Float (computed) | Ce que la règle donnerait pour cet article, inscrit ou non, et l'écart au prix affiché |
| `x_pv_regle_fiable` | Boolean (computed) | Faux si le rapport prix de vente / prix d'achat sort de la plage plausible (0,9 à 4,0) |
| `x_pv_motif` | Char (computed) | Résumé du ou des motifs qui placent l'article dans l'écran « à revoir » |
| `x_auto_price_target` / `x_auto_price_gap` | Float (computed) | Cible et écart, uniquement pour les articles en auto-pricing |
| `x_auto_price_stale` | Boolean (computed, searchable) | Le prix de vente affiché ne correspond plus à la règle auto-pricing |

### `product.supplierinfo`

| Champ | Type | Description |
|---|---|---|
| `is_promo_price` | Boolean | Exclut ce prix du calcul automatique |

---

## Utilisé par / dépend de

- **`product_label_extra_format`** — dépend de ce module, affiche `x_last_auto_supplier_id`/`x_last_auto_date` sur le format d'étiquette 3×7 et présélectionne ce format depuis l'écran « Prix de vente à revoir »
- **`supplier_enrichment`** — ajoute trois écrans sous le menu **Prix** défini ici (`menu_prix`), et alimente les prix fournisseurs qui déclenchent le suivi de ce module

---

## Structure du module

```
product_auto_pricing/
├── __init__.py
├── __manifest__.py
├── DOCS.md                         # Doc technique plus ancienne — partiellement
│                                    # dépassée par ce README sur l'écran "à revoir"
│                                    # et le suivi du coût (ajoutés fin août 2026)
├── data/
│   └── ir_cron_auto_pricing.xml    # Action planifiée, désactivée (voir État actuel)
├── models/
│   ├── __init__.py
│   └── product_auto_pricing.py     # SupplierInfo, ProductCategory, ProductTemplate
├── views/
│   ├── product_category_view.xml       # Marge sur la fiche catégorie
│   ├── product_template_view.xml       # Groupe auto-pricing + colonne promo
│   └── product_price_review_view.xml   # Écran "Prix de vente à revoir" + menu Prix
├── tools/                           # Scripts autonomes, hors chargement Odoo :
│   ├── importers.py                 #   import de tarifs fournisseurs xlsx
│   └── sample_data/                 #   fichiers xlsx d'exemple pour les tests
├── simulate.py                      # Rejoue la logique de calcul hors Odoo (mock)
└── .env.example                     # Modèle de .env pour des outils externes
```

---

## Pièges connus

- **Une marge à 0 % non confirmée n'est pas 0 %.** Sans `x_margin_zero_confirmed`, elle est silencieusement remplacée par 30 % au calcul.
- **Un prix de colis saisi comme prix unitaire fausse tout.** Le module refuse d'écrire un coût qui dépasserait le prix de vente affiché, et journalise le refus — mais la fiche fournisseur reste fausse tant qu'elle n'est pas corrigée à la main.
- **`x_pv_regle` peut être fiable pour un article qui n'est pas en auto-pricing.** C'est volontaire (simulation), mais ça ne veut pas dire que le prix va changer tout seul : seul `x_auto_pricing_enabled=True` déclenche un recalcul réel.
- **Le cron réactivé écrase un prix corrigé à la main** sur tout article resté inscrit en auto-pricing.
