#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper Biofresh (ecommerce.biofresh.be)
Utilise Playwright pour contourner la protection anti-bot.

Pré-requis (sur ta machine) :
    pip install playwright python-dotenv
    playwright install chromium

Identifiants : fichier .env à la racine du projet :
    BIOFRESH_EMAIL=ton@email.com
    BIOFRESH_PASSWORD=tonmotdepasse

Usage :
    python3 tools/scraper_biofresh.py                    # test sur EAN fictifs
    python3 tools/scraper_biofresh.py 8428201060555 ...  # EAN en argument
"""

import os
import sys
import json
import re
import time
from pathlib import Path

# Charge .env si présent
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass  # python-dotenv optionnel si les vars d'env sont déjà définies

BASE_URL     = "https://ecommerce.biofresh.be"
LOGIN_URL    = f"{BASE_URL}/Account/Login"
SEARCH_URL   = f"{BASE_URL}/Products?search={{ean}}"
COOKIES_FILE = Path(__file__).parent / ".biofresh_session.json"

SUPPLIER_NAME = "Biofresh"


# ---------------------------------------------------------------------------
# Session / Login
# ---------------------------------------------------------------------------

def save_cookies(context):
    cookies = context.cookies()
    COOKIES_FILE.write_text(json.dumps(cookies))


def load_cookies(context):
    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text())
        context.add_cookies(cookies)
        return True
    return False


def login(page, email: str, password: str) -> bool:
    """
    Se connecte sur Biofresh. Retourne True si succès.
    Détecte automatiquement les champs du formulaire.
    """
    print(f"  Connexion en cours ({email})...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # Cherche les champs email/password (noms courants ASP.NET)
    for selector in ["input[name='Email']", "input[type='email']", "input[name='UserName']"]:
        if page.locator(selector).count() > 0:
            page.fill(selector, email)
            break
    else:
        print("  ERREUR : champ email introuvable sur la page de login")
        return False

    for selector in ["input[name='Password']", "input[type='password']"]:
        if page.locator(selector).count() > 0:
            page.fill(selector, password)
            break
    else:
        print("  ERREUR : champ password introuvable sur la page de login")
        return False

    # Soumet le formulaire
    page.keyboard.press("Enter")
    page.wait_for_load_state("domcontentloaded")

    # Vérifie si le login a réussi (plus de champ password = connecté)
    if page.locator("input[type='password']").count() == 0:
        print("  Connecté.")
        return True
    else:
        print("  ERREUR : login échoué (mauvais identifiants ?)")
        return False


def is_logged_in(page) -> bool:
    """Vérifie si la session est toujours active."""
    page.goto(f"{BASE_URL}/Products", wait_until="domcontentloaded")
    return page.locator("input[type='password']").count() == 0


# ---------------------------------------------------------------------------
# Extraction du prix
# ---------------------------------------------------------------------------

def extract_price_from_page(page) -> dict | None:
    """
    Extrait le prix et les infos produit depuis une page détail Biofresh.
    Retourne None si le produit n'est pas trouvé.
    """
    # Attendre que le contenu soit chargé
    try:
        page.wait_for_selector("body", timeout=5000)
    except Exception:
        return None

    html = page.content()

    # Prix principal (ex: "2,29 EUR" ou "2.29 EUR")
    price = None
    for pattern in [
        r'Prix\s+brut\s*[:\s]*([0-9]+[,\.][0-9]+)\s*EUR',   # "Prix brut : 2,39 EUR"
        r'<[^>]*class="[^"]*price[^"]*"[^>]*>.*?([0-9]+[,\.][0-9]+)\s*EUR',
        r'([0-9]+[,\.][0-9]+)\s*EUR\s*/\s*(?:Pi[eè]ce|Boite|Kg|L)',  # "2,29 EUR / Pièce"
    ]:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                price = float(raw)
                break
            except ValueError:
                continue

    if price is None:
        return None

    # Détection promo : réduction > 0 ou badge promo
    is_promo = False
    promo_patterns = [
        r'R[eé]duction\s*[:\s]*([0-9]+[,\.][0-9]+)\s*%',  # "Réduction : 4,00%"
        r'class="[^"]*promo[^"]*"',
    ]
    for pattern in promo_patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            if "promo" in pattern:
                is_promo = True
            else:
                try:
                    reduction = float(m.group(1).replace(",", "."))
                    is_promo = reduction > 0
                except ValueError:
                    pass
            break

    # Nom produit
    name = ""
    m = re.search(r'<h[12][^>]*>\s*([^<]+)\s*</h[12]>', html)
    if m:
        name = m.group(1).strip()

    return {
        "price":    price,
        "is_promo": is_promo,
        "name":     name,
    }


# ---------------------------------------------------------------------------
# Recherche par EAN
# ---------------------------------------------------------------------------

def fetch_price_by_ean(page, ean: str) -> dict | None:
    """
    Cherche un produit par EAN et retourne son prix normalisé.
    Retourne None si produit introuvable.
    """
    url = SEARCH_URL.format(ean=ean)
    page.goto(url, wait_until="domcontentloaded")
    current_url = page.url

    # Cas 1 : la recherche redirige directement vers la fiche produit
    if "/Details" in current_url:
        data = extract_price_from_page(page)
        if data:
            return {
                "ean":           ean,
                "supplier_name": SUPPLIER_NAME,
                "price":         data["price"],
                "is_promo":      data["is_promo"],
                "min_qty":       1.0,
                "_name":         data["name"],
            }

    # Cas 2 : page de résultats → cherche le premier lien produit
    product_links = page.locator("a[href*='/Products/Details']").all()
    if not product_links:
        return None  # produit introuvable

    product_links[0].click()
    page.wait_for_load_state("domcontentloaded")
    data = extract_price_from_page(page)
    if not data:
        return None

    return {
        "ean":           ean,
        "supplier_name": SUPPLIER_NAME,
        "price":         data["price"],
        "is_promo":      data["is_promo"],
        "min_qty":       1.0,
        "_name":         data["name"],
    }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def scrape(eans: list[str]) -> list[dict]:
    from playwright.sync_api import sync_playwright

    email    = os.getenv("BIOFRESH_EMAIL")
    password = os.getenv("BIOFRESH_PASSWORD")

    if not email or not password:
        print("ERREUR : variables BIOFRESH_EMAIL et BIOFRESH_PASSWORD manquantes dans .env")
        sys.exit(1)

    results   = []
    not_found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # headless=False pour voir le navigateur
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            locale="fr-BE",
        )
        page = context.new_page()

        # Tente de réutiliser la session existante
        logged_in = False
        if load_cookies(context):
            if is_logged_in(page):
                print("Session existante réutilisée.")
                logged_in = True

        if not logged_in:
            logged_in = login(page, email, password)
            if logged_in:
                save_cookies(context)

        if not logged_in:
            browser.close()
            return []

        print(f"\nRecherche de {len(eans)} EAN(s)...\n")
        SEP = "-" * 56

        for i, ean in enumerate(eans, 1):
            print(f"  [{i}/{len(eans)}] {ean}", end=" → ")
            try:
                row = fetch_price_by_ean(page, ean)
                time.sleep(0.5)  # pause courte pour ne pas surcharger le serveur
            except Exception as e:
                print(f"ERREUR ({e})")
                not_found.append(ean)
                continue

            if row:
                promo = " [PROMO]" if row["is_promo"] else ""
                print(f"{row['price']:.2f} EUR{promo}  ({row['_name']})")
                results.append(row)
            else:
                print("introuvable")
                not_found.append(ean)

        browser.close()

    print(f"\n  ✓ {len(results)} prix récupérés")
    if not_found:
        print(f"  ✗ {len(not_found)} EAN non trouvés : {not_found}")

    return results


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # EAN en arguments ou liste de test par défaut
    eans = sys.argv[1:] or [
        "8428201060555",  # ARTEMIS Clous de Girofle (vu dans la capture)
        "9999999999999",  # EAN fictif → doit retourner "introuvable"
    ]

    rows = scrape(eans)

    if rows:
        print(f"\n{'=' * 56}")
        print("  Résultat final (→ seller_ids Odoo)")
        print(f"{'=' * 56}")
        for r in rows:
            promo = " [PROMO]" if r["is_promo"] else ""
            print(f"  {r['ean']}  {r['price']:>8.2f} EUR{promo}")
        print(f"{'=' * 56}")
