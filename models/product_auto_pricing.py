# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

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
    # ── Suivi des hausses de prix d'achat ────────────────────────────────
    # Marqué AU MOMENT où un prix d'achat change réellement, et non déduit
    # après coup : la date d'écriture d'une fiche fournisseur ne veut rien dire
    # (810 fiches réécrites en un passage le 27/08/2026 sans qu'un seul prix
    # bouge). Seul un changement de valeur constaté fait foi.
    x_achat_a_revoir = fields.Boolean(
        string="Prix d'achat modifié", default=False, index=True, copy=False,
        help="Un prix d'achat a changé et le prix de vente n'a pas été revu "
             "depuis. Se lève au clic sur « Vu » ou en appliquant la règle.")
    x_achat_precedent = fields.Float(
        string="Achat avant", readonly=True, copy=False, digits="Product Price")
    x_achat_nouveau = fields.Float(
        string="Achat après", readonly=True, copy=False, digits="Product Price")
    x_achat_variation = fields.Float(
        string="Variation %", compute="_compute_achat_variation", store=True)
    # Une fiche vide qui se remplit n'est pas une hausse de 0 % : c'est un prix
    # qui n'existait pas. Sans cette distinction, le cas le plus fréquent après
    # une reprise de données — la fiche restée vide depuis l'import Lineosoft —
    # tombait en bas d'une liste triée par variation, et hors du filtre
    # « hausses ». Vu sur le Chevron affiné le 2026-08-28.
    x_achat_nature = fields.Selection(
        [("nouveau", "Prix nouveau"), ("hausse", "Hausse"), ("baisse", "Baisse")],
        string="Nature", compute="_compute_achat_variation", store=True)
    x_achat_change_le = fields.Datetime(
        string="Modifié le", readonly=True, copy=False)
    x_achat_fournisseur_id = fields.Many2one(
        "res.partner", string="Fournisseur", readonly=True, copy=False)

    # Ce que la règle donnerait, pour TOUT article — indicatif hors
    # auto-pricing, et laissé vide quand les unités ne concordent pas.
    x_pv_regle = fields.Float(
        string="PV selon la règle", compute="_compute_pv_regle",
        digits="Product Price")
    x_pv_regle_ecart = fields.Float(
        string="Écart au PV affiché", compute="_compute_pv_regle",
        digits="Product Price")
    x_pv_motif = fields.Char(
        string="Motif", compute="_compute_pv_motif",
        help="Ce qui met cette ligne dans la liste. Les deux motifs peuvent "
             "se cumuler.")
    x_pv_regle_fiable = fields.Boolean(
        string="Unités concordantes", compute="_compute_pv_regle",
        help="Faux quand le rapport prix de vente / prix d'achat sort de la "
             "plage plausible : l'article est acheté au carton et vendu à la "
             "pièce, ou l'inverse. La règle ne veut alors rien dire.")

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

    # Hors de cette plage, le prix d'achat et le prix de vente ne parlent pas
    # de la même quantité (8 articles sur 1 927 au 2026-08-28 : charbon acheté
    # au carton vendu à la pièce, cerneaux au sac vendus au kilo…).
    _COEF_PLANCHER, _COEF_PLAFOND = 0.9, 4.0

    @api.depends("x_achat_precedent", "x_achat_nouveau")
    def _compute_achat_variation(self):
        for template in self:
            avant, apres = template.x_achat_precedent, template.x_achat_nouveau
            if not avant:
                template.x_achat_variation = 0.0
                template.x_achat_nature = "nouveau" if apres else False
                continue
            template.x_achat_variation = round(100.0 * (apres - avant) / avant, 1)
            template.x_achat_nature = "hausse" if apres > avant else "baisse"

    @api.depends("list_price", "categ_id", "seller_ids.price",
                 "seller_ids.is_promo_price")
    def _compute_pv_regle(self):
        for template in self:
            regle = template._pv_regle()
            if not regle:
                template.x_pv_regle = 0.0
                template.x_pv_regle_ecart = 0.0
                template.x_pv_regle_fiable = False
                continue
            cout, prix, _f = regle
            coef = (template.list_price / cout) if cout else 0.0
            fiable = template._COEF_PLANCHER <= coef <= template._COEF_PLAFOND
            template.x_pv_regle_fiable = fiable
            template.x_pv_regle = prix if fiable else 0.0
            template.x_pv_regle_ecart = (prix - template.list_price) if fiable else 0.0

    @api.depends("x_achat_a_revoir", "x_achat_nature", "x_achat_variation",
                 "x_auto_price_stale")
    def _compute_pv_motif(self):
        """Deux déclencheurs mènent au même geste — revoir un prix de vente —
        donc à un seul écran. Le motif dit lequel a parlé, et il peut y en
        avoir deux."""
        for template in self:
            motifs = []
            if template.x_achat_a_revoir:
                if template.x_achat_nature == "nouveau":
                    motifs.append(_("prix d'achat nouveau"))
                elif template.x_achat_nature:
                    motifs.append(_("prix d'achat %+.1f %%") % template.x_achat_variation)
            if template.x_auto_price_stale:
                motifs.append(_("ne suit plus la règle"))
            template.x_pv_motif = " · ".join(motifs)

    def _marquer_achat_modifie(self, avant, apres, fournisseur):
        """Retient qu'un prix d'achat a bougé, avec sa valeur d'avant.

        Si le produit est déjà marqué, on garde le PREMIER « avant » : ce qui
        intéresse est l'écart depuis la dernière fois qu'on a regardé, pas
        depuis l'avant-dernière hausse.
        """
        for template in self:
            valeurs = {"x_achat_a_revoir": True,
                       "x_achat_nouveau": apres,
                       "x_achat_change_le": fields.Datetime.now(),
                       "x_achat_fournisseur_id": fournisseur.id if fournisseur else False}
            if not template.x_achat_a_revoir:
                valeurs["x_achat_precedent"] = avant
            template.write(valeurs)

    def _suivre_cout_achat(self, prix, fiche):
        """Le coût du produit suit le prix d'achat qu'on vient d'enregistrer.

        POURQUOI ICI, et pas dans le recalcul auto-pricing : celui-ci met à jour
        le coût ET le prix de vente d'un même geste. Benjamin l'a coupé le
        15/08/2026 pour ne pas passer son temps à réimprimer et replacer des
        étiquettes — et a donc aussi, sans le vouloir, figé les coûts. Résultat :
        la marge se calculait sur des coûts périmés, et sur 96 % du catalogue
        (2 237 fiches sur 2 320 hors auto-pricing) elle ne suivait rien du tout.

        Les deux mises à jour n'ont pourtant rien à voir :
          - le COÛT ne se voit nulle part en rayon. Rien à réimprimer, aucun
            prix client modifié, aucune écriture comptable (`manual_periodic`).
            Il doit suivre l'information dès qu'elle arrive.
          - le PRIX DE VENTE est une décision, qui coûte des étiquettes. Il
            reste manuel, via l'écran « à revoir » que `_marquer_achat_modifie`
            alimente juste à côté.

        POURQUOI LE PRIX DE LA FICHE QU'ON ÉCRIT, et pas le moins cher : 742
        produits ont plusieurs fournisseurs, avec 9 à 11 % d'écart moyen. Prendre
        le moins cher suppose qu'on achète toujours au meilleur prix, ce que
        l'écran de veille contredit (colonne « moins cher ailleurs »). Le prix
        qu'on vient de saisir vient d'une facture : c'est ce qu'on a réellement
        payé. Décidé le 2026-08-29.

        Deux refus d'écriture, tous deux journalisés plutôt que silencieux :
          - unité de la fiche différente de celle du produit : on ne convertit
            pas, on ne devine pas ;
          - coût supérieur au prix de vente : signature d'un prix de
            conditionnement saisi comme prix unitaire (Woody Bintochan à 81,30 €
            l'unité pour un article vendu 7,95 € ; Cerneaux de noix à 77,78 €/kg
            vendus 15,07 €). Une de ces fiches a déjà contaminé un coût — le
            Ka'ré porte 89,38 € de coût pour une vente à 9,25 €.
        """
        for template in self:
            if not prix or prix <= 0:
                continue
            uom_fiche = fiche.product_uom or template.uom_po_id or template.uom_id
            if uom_fiche != template.uom_id:
                _logger.info(
                    "Coût non repris sur %s : fiche en %s, produit en %s",
                    template.display_name, uom_fiche.name, template.uom_id.name)
                continue
            if template.list_price and prix > template.list_price:
                _logger.warning(
                    "Coût non repris sur %s : prix d'achat %.2f > prix de vente "
                    "%.2f — probable prix de conditionnement",
                    template.display_name, prix, template.list_price)
                continue
            if abs((template.standard_price or 0.0) - prix) <= 0.0001:
                continue
            _logger.info("Coût suivi sur %s : %.2f -> %.2f (%s)",
                         template.display_name, template.standard_price or 0.0,
                         prix, fiche.partner_id.display_name)
            template.standard_price = prix

    def action_achat_vu(self):
        """« J'ai regardé, je garde mon prix. » Ne touche à aucun prix."""
        self.write({"x_achat_a_revoir": False})
        return True

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
        # Les inscrits passent par le calcul complet (coût, prix, suivi) ; les
        # autres reçoivent seulement le prix de la règle, et uniquement là où
        # elle a un sens — un article acheté au carton et vendu à la pièce
        # n'est pas repricé au hasard.
        inscrits = self.filtered("x_auto_pricing_enabled")
        inscrits._compute_auto_price_for_templates()
        for template in (self - inscrits).filtered(
                lambda t: t.x_pv_regle_fiable and t.x_pv_regle > 0):
            template.list_price = template.x_pv_regle
        self.filtered("x_achat_a_revoir").write({"x_achat_a_revoir": False})
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
    def _pv_regle(self):
        """Ce que la règle donnerait pour CE produit, inscrit ou non en
        auto-pricing : (coût, prix de vente, fournisseur retenu), ou None si
        aucun prix d'achat n'est connu.

        Séparée du contrôle d'inscription pour que l'écran « Prix d'achat
        modifiés » puisse afficher la cible de n'importe quel article sans
        pour autant l'enrôler dans le recalcul automatique. La règle reste à
        UN seul endroit : dupliquée, elle aurait dérivé, et la liste aurait
        fini par annoncer un prix que le bouton n'aurait pas produit.
        """
        self.ensure_one()
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

    def _auto_price_target(self):
        """La règle, mais seulement pour les produits inscrits en auto-pricing.

        C'est cette porte-là que franchissent le recalcul et l'écran
        historique ; `_pv_regle` reste ouverte à tout le catalogue.
        """
        self.ensure_one()
        return self._pv_regle() if self.x_auto_pricing_enabled else None

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

            # Le prix de vente vient d'être remis au niveau de la règle : la
            # question posée par la hausse du prix d'achat est répondue.
            if template.x_achat_a_revoir:
                template.x_achat_a_revoir = False

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


class ProductSupplierinfo(models.Model):
    """C'est ici qu'on sait qu'un prix d'achat a bougé — nulle part ailleurs.

    Après coup, plus rien ne le dit : Odoo ne garde pas l'ancien prix, et la
    date d'écriture de la fiche est réécrite par n'importe quel passage en lot.
    Le seul instant où l'information existe est celui de l'écriture.
    """
    _inherit = "product.supplierinfo"

    _ECART_SIGNIFICATIF = 0.005   # sous le centime, c'est du bruit d'arrondi

    def _signaler(self, avant_par_id):
        for fiche in self:
            if fiche.is_promo_price or not fiche.product_tmpl_id:
                continue                       # la règle ignore les promos
            avant = avant_par_id.get(fiche.id, 0.0)
            if abs((fiche.price or 0.0) - avant) <= self._ECART_SIGNIFICATIF:
                continue
            fiche.product_tmpl_id._marquer_achat_modifie(
                avant, fiche.price, fiche.partner_id)
            # Le prix de vente part en décision ; le coût, lui, suit tout de
            # suite : il ne se voit pas en rayon et fausse la marge tant qu'il
            # traîne.
            fiche.product_tmpl_id._suivre_cout_achat(fiche.price, fiche)

    @api.model_create_multi
    def create(self, vals_list):
        fiches = super().create(vals_list)
        # Un article qui n'avait aucun prix d'achat en reçoit un : le prix de
        # vente mérite un regard autant que sur une hausse.
        fiches._signaler({f.id: 0.0 for f in fiches})
        return fiches

    def write(self, vals):
        if "price" not in vals:
            return super().write(vals)
        avant = {fiche.id: fiche.price or 0.0 for fiche in self}
        resultat = super().write(vals)
        self._signaler(avant)
        return resultat
