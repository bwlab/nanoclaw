#!/usr/bin/env python3
"""Scrape aziende di Cirié da companyreports.it (4 pagine) e salva in CSV."""

import csv
import re
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "it-IT,it;q=0.9",
}

BASE_URL = "https://www.companyreports.it"
LIST_URLS = [
    f"{BASE_URL}/comune/cirie",
    f"{BASE_URL}/comune/cirie/2",
    f"{BASE_URL}/comune/cirie/3",
    f"{BASE_URL}/comune/cirie/4",
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

MAX_RETRIES = 4
BASE_DELAY = 3


def fetch_with_retry(url: str) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 429:
                wait = BASE_DELAY * (2 ** attempt)
                print(f"    429 - attendo {wait}s (tentativo {attempt+1}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = BASE_DELAY * (2 ** attempt)
                print(f"    Errore {e} - retry in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  ERRORE: {e}")
    return None


def get_company_links_from_page(url: str) -> list[dict]:
    """Estrae i link alle aziende dalla pagina lista."""
    companies = []
    resp = fetch_with_retry(url)
    if not resp:
        return companies

    soup = BeautifulSoup(resp.text, "html.parser")
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        # Skip link di navigazione
        if any(x in href for x in ["/comune/", "/regione/", "/provincia/", "/settori",
                                     "/statistiche", "/servizi", "/listino", "/assistenza",
                                     "/contatti", "/registrati", "/catasto", "/areaclienti"]):
            continue
        if href in ("", "/", BASE_URL, f"{BASE_URL}/"):
            continue

        # Link azienda: contiene il nome e punta a companyreports.it
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        if BASE_URL in full_url and full_url not in seen_urls:
            # Solo il primo link per ogni URL (ragione sociale, ignora fatturato e INFO)
            if text and not text.startswith("€") and text != "INFO":
                seen_urls.add(full_url)
                companies.append({"ragione_sociale_lista": text, "url": full_url})

    return companies


def fetch_detail(url: str) -> dict:
    """Scarica i dettagli di un'azienda dalla pagina di dettaglio."""
    detail = {
        "partita_iva": "",
        "codice_fiscale": "",
        "ragione_sociale": "",
        "codice_ateco": "",
        "descrizione_ateco": "",
        "indirizzo": "",
        "citta": "",
        "fatturato": "",
        "anno_fatturato": "",
        "utile": "",
        "anno_utile": "",
        "costo_personale": "",
        "anno_costo_personale": "",
        "n_dipendenti": "",
        "stato_attivita": "",
        "forma_giuridica": "",
    }

    resp = fetch_with_retry(url)
    if not resp:
        return detail

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Header: P.IVA, CF, Ragione Sociale, Codice ATECO
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if "Partita IVA" in t and "Codice Fiscale" in t:
            piva = re.search(r"Partita IVA:\s*(\d{11})", t)
            if piva:
                detail["partita_iva"] = piva.group(1)
            cf = re.search(r"Codice Fiscale:\s*(\d{11})", t)
            if cf:
                detail["codice_fiscale"] = cf.group(1)
            rs = re.search(r"Ragione Sociale:\s*(.+?)(?:\s*Codice ATECO|$)", t)
            if rs:
                detail["ragione_sociale"] = rs.group(1).strip()
            ateco = re.search(r"Codice ATECO:\s*([\d.]+)\s*-\s*(.+?)(?:\s*Anteprima|$)", t)
            if ateco:
                detail["codice_ateco"] = ateco.group(1)
                detail["descrizione_ateco"] = ateco.group(2).strip()
            break

    # Blocco dati economici
    for div in soup.find_all(["div", "table"]):
        t = div.get_text(" ", strip=True)
        if "Indirizzo" in t and "Fatturato" in t and len(t) < 2000:
            # Indirizzo
            ind = re.search(r"Indirizzo\s+(.+?)\s*(?:Fatturato|$)", t)
            if ind:
                addr = ind.group(1).strip()
                # Separa indirizzo e città
                city_match = re.search(r"-\s*(.+?)(?:\s*\(\s*\w+\s*\)\s*$|\s*$)", addr)
                detail["indirizzo"] = addr
                if city_match:
                    detail["citta"] = city_match.group(1).strip()

            # Fatturato
            fatt = re.search(r"Fatturato\s+€\s*([\d.,]+)\s*\((\d{4})\)", t)
            if fatt:
                detail["fatturato"] = fatt.group(1)
                detail["anno_fatturato"] = fatt.group(2)

            # Utile
            utile = re.search(r"Utile\s+€\s*(-?[\d.,]+)\s*\((\d{4})\)", t)
            if utile:
                detail["utile"] = utile.group(1)
                detail["anno_utile"] = utile.group(2)

            # Costo del personale
            costo = re.search(r"Costo del personale\s+€\s*([\d.,]+)\s*\((\d{4})\)", t)
            if costo:
                detail["costo_personale"] = costo.group(1)
                detail["anno_costo_personale"] = costo.group(2)

            # N. Dipendenti
            dip = re.search(r"N\.\s*Dipendenti\s+(.+?)(?:\s*Stato|\s*$)", t)
            if dip:
                detail["n_dipendenti"] = dip.group(1).strip()

            # Stato Attività
            stato = re.search(r"Stato Attivit[àa]\s+(\w+)", t)
            if stato:
                detail["stato_attivita"] = stato.group(1)

            # Forma giuridica
            forma = re.search(r"Forma giuridica\s+(.+?)(?:\s*Codice Ateco|\s*Attivit[àa]|\s*$)", t)
            if forma:
                detail["forma_giuridica"] = forma.group(1).strip()

            break

    return detail


def main():
    output_file = "companyreports_cirie.csv"
    fieldnames = [
        "ragione_sociale", "partita_iva", "codice_fiscale",
        "indirizzo", "citta", "forma_giuridica",
        "codice_ateco", "descrizione_ateco",
        "fatturato", "anno_fatturato",
        "utile", "anno_utile",
        "costo_personale", "anno_costo_personale",
        "n_dipendenti", "stato_attivita",
        "link",
    ]

    # Step 1: raccogli tutti i link dalle 4 pagine
    all_companies = []
    for page_url in LIST_URLS:
        print(f"Scarico lista: {page_url}")
        companies = get_company_links_from_page(page_url)
        print(f"  -> {len(companies)} aziende trovate")
        all_companies.extend(companies)
        time.sleep(2)

    # Deduplica per URL
    seen = set()
    unique = []
    for c in all_companies:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    all_companies = unique

    print(f"\nTotale aziende uniche: {len(all_companies)}")

    # Controlla se ci sono aziende già scaricate
    already_done = {}
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row.get("partita_iva"):
                    already_done[row["link"]] = row
    except FileNotFoundError:
        pass

    remaining = [c for c in all_companies if c["url"] not in already_done]
    print(f"Già scaricate: {len(already_done)}, da scaricare: {len(remaining)}")

    # Step 2: scarica i dettagli
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        # Riscrivi le già fatte
        for row in already_done.values():
            writer.writerow({k: row.get(k, "") for k in fieldnames})

        for i, company in enumerate(remaining, 1):
            print(f"[{i}/{len(remaining)}] {company['ragione_sociale_lista']}...")
            detail = fetch_detail(company["url"])

            row = {
                "ragione_sociale": detail["ragione_sociale"] or company["ragione_sociale_lista"],
                "partita_iva": detail["partita_iva"],
                "codice_fiscale": detail["codice_fiscale"],
                "indirizzo": detail["indirizzo"],
                "citta": detail["citta"],
                "forma_giuridica": detail["forma_giuridica"],
                "codice_ateco": detail["codice_ateco"],
                "descrizione_ateco": detail["descrizione_ateco"],
                "fatturato": detail["fatturato"],
                "anno_fatturato": detail["anno_fatturato"],
                "utile": detail["utile"],
                "anno_utile": detail["anno_utile"],
                "costo_personale": detail["costo_personale"],
                "anno_costo_personale": detail["anno_costo_personale"],
                "n_dipendenti": detail["n_dipendenti"],
                "stato_attivita": detail["stato_attivita"],
                "link": company["url"],
            }
            writer.writerow(row)
            f.flush()

            time.sleep(BASE_DELAY)

    print(f"\nCompletato! File salvato: {output_file}")


if __name__ == "__main__":
    main()
