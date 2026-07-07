# 📋 Documentation technique — `product_auto_pricing`

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
| `product.category` | `x_margin_zero_confirmed` | Boolean (défaut False) | Confirme qu'une marge à 0% est volontaire — voir "Piège marge 0%" ci-dessous |
| `product.template` | `x_auto_pricing_enabled` | Boolean | Active le recalcul |
| `product.template` | `x_last_auto_cost` | Float (readonly) | Audit |
| `product.template` | `x_last_auto_price` | Float (readonly) | Audit |
| `product.template` | `x_last_auto_supplier_id` | M2O res.partner (readonly) | Audit |
| `product.template` | `x_last_auto_date` | Datetime (readonly) | Audit |

### Méthodes principales

- `_compute_auto_price_for_templates()` — logique de calcul (filtre promo, min, marge)
- `action_recompute_auto_price()` — bouton manuel sur fiche produit, aussi appelé par `supplier_enrichment.action_confirm` après upsert d'un `supplierinfo`
- `_cron_recompute_auto_prices()` — cron quotidien (**actif depuis le 2026-07-07**, voir "Historique")

### Vues XML

| Vue | Héritage | Rôle |
|-----|----------|------|
| `view_supplierinfo_form_auto_pricing` | `product.product_supplierinfo_form_view` | Ajoute `is_promo_price` au form |
| `view_supplierinfo_tree_auto_pricing` | `product.product_supplierinfo_tree_view` | Ajoute colonne `is_promo_price` optionnelle dans le tableau |
| `view_product_template_form_auto_pricing` | `product.product_template_form_view` | Groupe "Auto-pricing" avec champs audit + bouton |
| `product_category_view` | Vue catégorie | Ajoute `x_margin_percent` + `x_margin_zero_confirmed` (visible seulement si marge = 0) |

### Cron

- **ID :** `ir_cron_auto_pricing`
- **Fréquence :** quotidien
- **Modèle cible :** `product.template`
- **Méthode :** `model._cron_recompute_auto_prices()`
- **État :** **actif** depuis le 2026-07-07 (était désactivé par défaut à l'install — voir "Historique / Audit")

---

## 📂 Structure du repo

```
product_auto_pricing/
├── __init__.py
├── __manifest__.py          # v16.0.1.0.0, depends=["product"]
├── README.md                 # Guide d'installation / configuration côté utilisateur
├── DOCS.md                   # Ce fichier — référence technique
├── simulate.py                # Simulation standalone (0 dépendance Odoo)
├── data/
│   └── ir_cron_auto_pricing.xml
├── models/
│   ├── __init__.py
│   └── product_auto_pricing.py
├── views/
│   ├── product_category_view.xml
│   └── product_template_view.xml
└── tools/                    # Outils externes (pas encore connectés à Odoo)
    ├── importers.py          # Adaptateurs XLSX (Alpha, Beta, Gamma)
    ├── simulate_import.py
    ├── scraper_biofresh.py   # Playwright, login + fetch
    └── sample_data/*.xlsx
```

---

## 🔧 Déploiement (Lenovo, depuis le 2026-07-07)

- **Serveur :** Lenovo (Ubuntu 24.04), plus le Raspberry Pi d'origine
- **Odoo :** 16 Community via Docker
- **DB :** PostgreSQL 14, base `IPELLE`
- **Container Odoo :** `odoo16-restore-odoo-1`
- **Container DB :** `odoo16-restore-db-1`
- **Emplacement module :** `/home/odoo/odoo16-restore/extra-addons/product_auto_pricing/`
- **Docker compose :** `/home/odoo/odoo16-restore/docker-compose.yml`

### Commandes de maintenance

```bash
cd /home/odoo/odoo16-restore

# Upgrade le module après modif XML/Python
docker compose exec -T odoo odoo -u product_auto_pricing -d IPELLE --stop-after-init

# Redémarrer Odoo (nécessaire après modif Python — le -u seul ne recharge pas
# le code déjà en mémoire du process principal)
docker compose restart odoo

# Vérifier installation
docker compose exec -T db psql -U odoo -d IPELLE -c "
SELECT name, state, latest_version
FROM ir_module_module
WHERE name = 'product_auto_pricing';
"

# Vérifier l'état du cron
docker compose exec -T db psql -U odoo -d IPELLE -c "
SELECT active, lastcall, nextcall FROM ir_cron WHERE id = 25;
"
```

---

## 📌 Points d'attention / pièges connus

### Nom technique — historique, plus de confusion aujourd'hui

Le module s'appelait `odoo-product-auto-pricing` (tiret invalide comme technical name Odoo — toléré par le loader mais empêchait tout autre module de le référencer proprement dans `depends`). **Renommé en `product_auto_pricing`** lors de la reconstitution sur Lenovo (2026-07-07). Le nom du **repo GitHub** est resté `odoo-product-auto-pricing` (cosmétique, sans conséquence fonctionnelle) — ne pas renommer le dossier du module dans un futur déploiement sans refaire ce renommage.

### Piège marge à 0% — `x_margin_zero_confirmed`

`x_margin_percent` est un `Float` avec `default=30.0`, donc jamais `None` après création — impossible de distinguer en Python "jamais configuré" de "volontairement mis à 0". Avant le 2026-07-07, le code faisait `margin = x_margin_percent or DEFAULT_MARGIN_PERCENT` : une catégorie à 0% (ex. consignes vendues sans marge) se retrouvait silencieusement remontée à 30%.

**Fix** : `x_margin_zero_confirmed` (Boolean, défaut `False`) sur `product.category`, visible dans le form uniquement quand la marge affichée est 0. Tant qu'il n'est pas coché, le comportement ne change pas (fallback 30% toujours appliqué) — **aucun changement rétroactif pour les catégories existantes**. Pour qu'une catégorie soit vraiment vendue à 0% de marge, cocher cette case en plus de mettre `x_margin_percent = 0`.

Sur IPELLE (2026-07-07), 2 catégories étaient à 0% (`Consignes/Vidanges`, `divers`) sans aucun produit `x_auto_pricing_enabled` dedans — donc sans impact réel à ce jour. **Reste à trancher avec le magasin** si l'une des deux doit effectivement rester à 0% le jour où l'auto-pricing y est activé.

### Le cron écrase les prix corrigés manuellement

`_compute_auto_price_for_templates()` ne vérifie jamais si `list_price` a été modifié manuellement depuis le dernier calcul auto — un prochain passage du cron **réécrit silencieusement** tout produit `x_auto_pricing_enabled=True`, y compris si quelqu'un a corrigé le prix à la main entre-temps. Pas de protection dans le code : si un produit doit garder un prix manuel durablement, désactiver `x_auto_pricing_enabled` dessus, pas juste corriger `list_price`.

### Prix qui se figent si la marge de catégorie change sans recalcul

`x_last_auto_price`/`list_price` ne se mettent à jour que quand `_compute_auto_price_for_templates()` tourne (bouton ou cron). Si `x_margin_percent` d'une catégorie change entre-temps (édition manuelle) et que le cron était désactivé, les produits de cette catégorie gardent un prix calculé sur l'**ancienne** marge, sans aucun signal visible que c'est périmé — le seul indice est de comparer `x_last_auto_price` à `cost × (1 + marge_actuelle/100)`. Trouvé concrètement sur IPELLE le 2026-07-07 (5 produits sur 13 concernés, corrigé en activant le cron).

### `min()` sur prix ex-æquo, arrondi bancaire, update non-batch

Voir `MODULES_TECHNIQUE.md` §7 pour ces points mineurs (déterministes mais à connaître) — non modifiés lors de l'audit du 2026-07-07, jugés non prioritaires.

---

## 🕵️ Audit du 2026-07-07 — réconciliation Git

Avant l'audit fonctionnel, une réconciliation Git a été nécessaire :

- Le code réel du module (copié depuis le Pi, avec le scraper Biofresh, les importeurs XLSX, `simulate.py`) vivait sur une **branche orpheline** `claude/implement-todo-item-5eWcB` — poussée sur GitHub mais **jamais mergée** dans `main`/`master`.
- `master` avait sa **propre ligne divergente** (PR #1 : ajout de `x_last_auto_date` + patch vue tree, puis `DOCS.md`) — invisible localement tant qu'un `git fetch --prune` n'avait pas été fait.
- **Réconcilié** : fast-forward de `main` vers le code réel, puis merge de `master` dans `main` pour récupérer `DOCS.md` (converge sans conflit — les deux lignes avaient indépendamment ajouté `x_last_auto_date`). Branche orpheline supprimée (locale + GitHub), `default_branch` du repo GitHub basculé sur `main`.

**Réflexe pour la suite** : avant toute modification sur ce repo (ou tout autre module de ce projet), faire `git fetch --prune origin` et comparer `main`/`master`/branches distantes avant de committer — ce n'était pas un cas isolé.

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
| **Cron en conditions réelles sur IPELLE (2026-07-07)** | ✅ 5 produits périmés recalculés correctement, 2 correctifs manuels écrasés comme attendu, 3 produits déjà cohérents non ré-écrits |

**Test historique (24/04/2026, sur le Pi) :**
- Produit "Test pomme", catégorie "Test Auto-Pricing" (marge 1000%), fournisseurs BIODYVINO (2€) / BIOFLORE (3€) → 2 × 11 = 22€ ✅

---

## 🚧 Roadmap — Ce qui n'est PAS fait

| Composant | Priorité |
|-----------|----------|
| Script d'import RPC (Biofresh → `supplierinfo`) | 🔴 Haute |
| Intégration scraper Biofresh dans IMPORTERS | 🟠 Moyenne |
| Matching EAN / LEAN (code-barres) dans Odoo | 🟠 Moyenne |
| Wizard Odoo d'import XLSX | 🟡 Basse |
| Tests unitaires | 🟡 Basse |
| Revoir les 2 produits dont le prix manuel a été écrasé par le cron (`Priméal - Couscous au fleurs`, `Origami - Semoule De Blé Dur`) avec le magasin | 🟠 Moyenne |
| Trancher `x_margin_zero_confirmed` pour `Consignes/Vidanges` et `divers` | 🟡 Basse (dormant tant qu'aucun produit n'y est activé) |

---

## 📝 Historique Git

- **Repo :** `github.com/benvala-png/odoo-product-auto-pricing` (nom historique, module renommé en `product_auto_pricing` — voir plus haut)
- **Branche par défaut :** `main` (basculée depuis `master` le 2026-07-07)
- **PR #1** (24/04/2026, sur `master`) : ajout `x_last_auto_date` + patch vue tree
- **Ligne `claude/implement-todo-item-5eWcB`** (avril-mai 2026, jamais mergée avant le 2026-07-07) : scraper Biofresh, adaptateurs d'import XLSX, `simulate.py`
- **2026-07-07** : réconciliation des deux lignes dans `main` (voir "Audit du 2026-07-07" plus haut), ajout de `x_margin_zero_confirmed`, cron activé

---

*Dernière mise à jour : 2026-07-07*
