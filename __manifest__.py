# -*- coding: utf-8 -*-
{
    "name": "Product Auto Pricing (Cheapest Supplier + Margin)",
    "version": "16.0.1.0.0",
    "summary": "Calcule automatiquement le prix de vente à partir du fournisseur le moins cher et de la marge par catégorie.",
    "author": "Benjamin + ChatGPT",
    "license": "LGPL-3",
    "depends": ["product"],
    "data": [
        "views/product_category_view.xml",
        "views/product_template_view.xml",
        "data/ir_cron_auto_pricing.xml",
    ],
    "installable": True,
    "application": False,
}
