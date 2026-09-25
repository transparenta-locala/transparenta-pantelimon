"""
Monitor Transparență Bugetară — Primăria Pantelimon
====================================================
Script de monitorizare automată: trage date din data.gov.ro (export SEAP oficial)
și transparenta.eu, detectează red flags și generează raport HTML.

Utilizare:
    python monitor_pantelimon.py          # rulează analiza și generează raportul
    python monitor_pantelimon.py --email  # rulează și trimite email dacă sunt flags noi

Dependențe: pip install requests beautifulsoup4 openpyxl
"""

import json
import os
import re
import smtplib
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    TTL_SEAP_CONTRACTE_DAYS,
    TTL_HCL_DAYS,
    TTL_CURTEA_CONTURI_DAYS,
    TTL_ANI_DAYS,
    TTL_TED_DAYS,
    TTL_MOL_DAYS,
    TTL_PNRR_DAYS,
    TTL_ONRC_DAYS,
    TTL_NOMINATIM_DAYS,
    TTL_ANAF_V9_DAYS,
    PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON,
    PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON,
    PRAGURI_LEGALE_VERIFICATE_LA,
    PRAGURI_LEGALE_SURSA,
)

# Optional: risc_firma.py — indicatori financiari firme furnizoare (SQLite cache, TTL 30 zile)
try:
    from risc_firma import fetch_firma_anaf as _fetch_firma_anaf
    from risc_firma import get_risk_panel_html as _get_risk_panel_html
    from risc_firma import evaluate_shell_risk as _evaluate_shell_risk
    _RISC_FIRMA_OK = True
except ImportError:
    _RISC_FIRMA_OK = False

# ==============================================================================
# CONFIGURARE — EDITEAZĂ ACESTE VALORI
# ==============================================================================

CONFIG = {
    # Identificatori Primăria Pantelimon
    "cui": "4420759",
    "nume_entitate": "Orașul Pantelimon",
    "judet": "Ilfov",

    # Praguri legale achiziție publică (RON, conform Legii 98/2016 actualizate)
    "prag_servicii_furnizare": PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON,
    "prag_lucrari": PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON,
    "marja_fragmentare_pct": 0.97,        # dacă valoarea e >97% din prag → suspect

    # Câte luni în urmă căutăm contracte
    "luni_analiza": 12,

    # Fișiere locale
    "fisier_stare": "stare_anterioara.json",   # pentru a detecta items noi
    "fisier_raport": "raport_transparenta.html",

    # Email (opțional — lasă gol dacă nu vrei alerte email)
    "email_from": "",          # ex: "monitorizare.pantelimon@gmail.com"
    "email_to": "",            # ex: "contact@transparenta-pantelimon.eu"
    "email_smtp": "smtp.gmail.com",
    "email_port": 587,
    "email_parola": "",        # recomandăm App Password Google, nu parola reală
    "contact_url": "https://github.com/transparenta-locala/transparenta-pantelimon/issues",

    # openapi.ro — date acționariat/administrator firme (opțional, gratuit 100 cereri/lună)
    # Înregistrare gratuită: https://openapi.ro/ro → Fă-ți un cont → generează cheie API
    "openapi_ro_key": "",          # ex: "abc123xyz..."

    # Fișier cache firme (evită re-interogarea acelorași CUI-uri la rulări consecutive)
    "fisier_cache_firme": "cache_firme.json",

    # §3.1 / §3.2 — cuvânt de căutat pe Curtea de Conturi + ANI integritate.eu
    "uat_search": "Pantelimon",
}


_LUCR_KEYWORDS = (
    "lucrari", "reparatii", "reabilitare", "modernizare", "constructi",
    "construire", "executie", "reamenajare", "amenajare", "deviere",
    "demolare", "restaurare", "consolidare", "extindere", "infrastructura",
)


def _text_fara_diacritice(value: str) -> str:
    """Normalizează textul pentru clasificări robuste, fără a altera afișarea."""
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(value or "").lower())
        if not unicodedata.combining(char)
    )


def _este_contract_lucrari(contract: dict) -> bool:
    """Clasificare conservatoare pe titlu/CPV pentru alegerea pragului legal."""
    text = _text_fara_diacritice(" ".join(str(contract.get(key, "") or "") for key in (
        "titlu", "denumire_cpv", "cpv_descriere", "categorie",
    )))
    return any(keyword in text for keyword in _LUCR_KEYWORDS)


def _prag_pentru_contract(contract: dict, config: dict = None) -> tuple:
    """Returnează (prag RON, etichetă categorie) pentru un contract."""
    cfg = config or CONFIG
    if _este_contract_lucrari(contract):
        return cfg["prag_lucrari"], "lucrări"
    return cfg["prag_servicii_furnizare"], "produse/servicii"

# ==============================================================================
# SURSE DE DATE
# ==============================================================================

DATAGOV_BASE = "https://data.gov.ro/api/3/action"
TRANSPARENTA_BASE = "https://transparenta.eu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MonitorCivic/1.0; civic transparency)",
    "Accept": "application/json, text/html",
    "Content-Type": "application/json",
}

# ==============================================================================
# 1. DATE BUGET DIN TRANSPARENTA.EU
# ==============================================================================

def fetch_budget_transparenta(cui: str) -> dict:
    """
    Extrage datele financiare din transparenta.eu (sursă: ANAF/MF).
    Returnează dict cu venituri, cheltuieli, evoluție YoY.
    """
    print(f"  [transparenta.eu] Fetchuiesc date buget pentru CUI {cui}...")
    url = f"{TRANSPARENTA_BASE}/entities/{cui}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # Extragem din meta description: "Venituri X mil. RON, Cheltuieli Y mil. RON..."
        meta_desc = ""
        for tag in soup.find_all("meta"):
            if tag.get("name") == "description" or tag.get("property") == "og:description":
                meta_desc = tag.get("content", "")
                break

        # Parse simplu din description
        result = {
            "sursa": "transparenta.eu / ANAF",
            "url": url,
            "descriere_bruta": meta_desc,
            "an": datetime.now().year,
            "venituri_mil_ron": None,
            "cheltuieli_mil_ron": None,
            "balanta_mil_ron": None,
        }

        # Extragem valorile numerice din description
        import re
        numere = re.findall(r"[\d,\.]+\s*mil\.?\s*RON", meta_desc)
        if len(numere) >= 2:
            def parse_ron(s):
                s = s.replace("mil.", "").replace("RON", "").replace("\xa0", "").strip()
                s = s.replace(",", ".")
                return float(s)
            result["venituri_mil_ron"] = parse_ron(numere[0])
            result["cheltuieli_mil_ron"] = parse_ron(numere[1])
            if len(numere) >= 3:
                result["balanta_mil_ron"] = parse_ron(numere[2])

        # Extragem și YoY din pagina HTML
        yoy_patterns = re.findall(r"([+-][\d,\.]+%)\s*YoY", r.text)
        result["yoy_venituri"] = yoy_patterns[0] if len(yoy_patterns) > 0 else "N/A"
        result["yoy_cheltuieli"] = yoy_patterns[1] if len(yoy_patterns) > 1 else "N/A"

        print(f"    ✓ Venituri: {result['venituri_mil_ron']} mil. RON  |  Cheltuieli: {result['cheltuieli_mil_ron']} mil. RON")
        return result

    except Exception as e:
        print(f"    ✗ Eroare transparenta.eu: {e}")
        return {"eroare": str(e), "sursa": "transparenta.eu"}


# ==============================================================================
# 2. DATE CONTRACTE DIN DATA.GOV.RO (export oficial SEAP trimestrial)
# ==============================================================================

def fetch_contracts_seap(
    cui: str,
    luni: int = 12,
    cache_db: str = "seap_contracte_cache.db",
    ttl_zile: int = TTL_SEAP_CONTRACTE_DAYS,
) -> tuple:
    """
    Descarcă contractele Primăriei Pantelimon din data.gov.ro — exportul oficial
    trimestrial al SEAP publicat de ANAP. Mult mai fiabil decât API-ul direct SEAP.
    Returnează (lista_contracte, lista_debug) pentru diagnosticare.

    Foloseşte SQLite cache cu TTL ttl_zile (implicit TTL_SEAP_CONTRACTE_DAYS) —
    exportul trimestrial SEAP nu se schimbă de la o rulare zilnică la alta.
    """
    import sqlite3
    import json as json_mod
    from datetime import timedelta as _timedelta

    def _init_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seap_contracte (
                cache_key TEXT PRIMARY KEY, extras_la TEXT, date_json TEXT, debug_json TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get(conn, key):
        row = conn.execute(
            "SELECT date_json, debug_json, extras_la FROM seap_contracte WHERE cache_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        date_json, debug_json, extras_la = row
        try:
            if datetime.now() - datetime.fromisoformat(extras_la) < _timedelta(days=ttl_zile):
                return json_mod.loads(date_json), json_mod.loads(debug_json)
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, key, contracte, debug_log):
        conn.execute(
            "INSERT OR REPLACE INTO seap_contracte (cache_key, extras_la, date_json, debug_json) VALUES (?,?,?,?)",
            (key, datetime.now().isoformat(), json_mod.dumps(contracte, ensure_ascii=False), json_mod.dumps(debug_log, ensure_ascii=False))
        )
        conn.commit()

    cache_key = f"{cui}_{luni}"
    conn = _init_cache(cache_db)
    cached = _cache_get(conn, cache_key)
    if cached is not None:
        conn.close()
        print(f"  [data.gov.ro] Contracte pentru CUI {cui} (din cache, TTL {ttl_zile}z)")
        return cached

    contracte, debug_log = _fetch_contracts_seap_live(cui, luni)
    _cache_set(conn, cache_key, contracte, debug_log)
    conn.close()
    return contracte, debug_log


def _fetch_contracts_seap_live(cui: str, luni: int = 12) -> tuple:
    """Logica de fetch propriu-zisă pentru fetch_contracts_seap(), fără cache."""
    import io, time
    try:
        import openpyxl
    except ImportError:
        print("    \u2717 openpyxl lipsă. Rulează: pip install openpyxl")
        return [], ["openpyxl lipsă"]

    IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"
    # Fișierele "Contracte" sunt ~22MB; "Achizitii directe" sunt ~57MB.
    # Runnerul GitHub Actions are 7GB RAM și openpyxl read_only iterează lazy,
    # deci putem procesa și fișierul mare. Plafon generos doar ca siguranță.
    MAX_FILE_MB = 80 if IS_CI else 200

    debug_log = [f"IS_CI={IS_CI} MAX_FILE_MB={MAX_FILE_MB}MB cui={cui}"]
    print(f"  [data.gov.ro] Caut contracte pentru CUI {cui} (IS_CI={IS_CI}, max={MAX_FILE_MB}MB)...")

    an_curent = datetime.now().year
    ani_de_verificat = sorted({an_curent - 1, an_curent})  # ultimii 2 ani
    contracte = []
    surse_ok = 0

    for an in ani_de_verificat:
        package_id = f"achizitii-publice-{an}"
        try:
            r = requests.get(
                f"{DATAGOV_BASE}/package_show?id={package_id}",
                timeout=20, headers=HEADERS
            )
            if r.status_code != 200:
                msg = f"Pachet {an} HTTP {r.status_code}"
                print(f"    \u26a0 {msg}")
                debug_log.append(msg)
                continue
            resources = r.json()["result"]["resources"]
            debug_log.append(f"an={an} resources={len(resources)}")
        except Exception as e:
            msg = f"Pachet {an} eroare: {e}"
            print(f"    \u26a0 {msg}")
            debug_log.append(msg)
            continue

        # Selectăm DOAR fișierele de tip "Contracte" — mai mici și conțin tot ce ne trebuie.
        # Fișierele "Achizitii directe" sunt >50MB și exced limita CI.
        fisiere_relevante = []
        for res in resources:
            name = res.get("name", "").lower()
            url = res.get("url", "")
            if not (url.endswith(".xlsx") or url.endswith(".xls")):
                continue
            este_contracte = "contracte" in name and "modificare" not in name
            # Includem și achizitii directe în CI (plafonul MAX_FILE_MB acoperă acum ~57MB)
            este_directe = "direct" in name and "notific" not in name and "atribuire" not in name
            if este_contracte or este_directe:
                tip = "contract" if este_contracte else "achizitie-directa"
                fisiere_relevante.append((tip, url, res.get("name", "")))

        msg = f"an={an}: {len(fisiere_relevante)} fisiere selectate"
        print(f"    \u2192 {msg}")
        debug_log.append(msg)

        for tip_sursa, url, res_name in fisiere_relevante:
            t_start = time.time()
            try:
                # HEAD pentru dimensiune (data.gov.ro adesea nu trimite Content-Length)
                try:
                    head = requests.head(url, timeout=10, headers=HEADERS, allow_redirects=True)
                    content_len = int(head.headers.get("Content-Length", 0))
                    if content_len > MAX_FILE_MB * 1024 * 1024:
                        msg = f"SKIP {res_name}: HEAD={content_len//1024//1024}MB>{MAX_FILE_MB}MB"
                        print(f"    \u23ed {msg}")
                        debug_log.append(msg)
                        continue
                except Exception as he:
                    debug_log.append(f"HEAD failed {res_name}: {he}")

                # Descărcare cu streaming; timeout=(connect=10s, read=60s per chunk)
                resp = requests.get(url, timeout=(10, 60), headers=HEADERS, stream=True)
                if resp.status_code != 200:
                    msg = f"GET {res_name} HTTP {resp.status_code}"
                    debug_log.append(msg)
                    continue

                chunks = []
                downloaded = 0
                LIMIT = MAX_FILE_MB * 1024 * 1024
                for chunk in resp.iter_content(chunk_size=65536):
                    downloaded += len(chunk)
                    if downloaded > LIMIT:
                        msg = f"SKIP {res_name}: stream>{MAX_FILE_MB}MB la {downloaded//1024//1024}MB"
                        print(f"    \u23ed {msg}")
                        debug_log.append(msg)
                        chunks = []
                        break
                    chunks.append(chunk)
                resp.close()

                elapsed = time.time() - t_start
                if not chunks:
                    debug_log.append(f"EMPTY {res_name} elapsed={elapsed:.1f}s")
                    continue

                file_bytes = b"".join(chunks)
                size_mb = len(file_bytes) / 1024 / 1024
                debug_log.append(f"DL {res_name}: {size_mb:.1f}MB in {elapsed:.1f}s")
                print(f"    \u2713 Descărcat {res_name}: {size_mb:.1f}MB în {elapsed:.1f}s")

                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
                ws = wb.active
                rows_iter = ws.iter_rows(values_only=True)
                headers_row = next(rows_iter, None)
                if not headers_row:
                    wb.close()
                    debug_log.append(f"NO_HEADERS {res_name}")
                    continue

                hdrs = [str(h).strip() if h else "" for h in headers_row]

                def col_idx(*names):
                    for name in names:
                        for i, h in enumerate(hdrs):
                            if name.lower() in h.lower():
                                return i
                    return None

                idx_cui_ac   = col_idx("CUI autoritate")
                idx_proc     = col_idx("Tip procedura")
                idx_valoare  = col_idx("Valoare contract", "Valoare achizitie", "Valoare")
                idx_castig   = col_idx("Ofertant castigator", "Furnizor", "Castigator")
                idx_cui_casg = col_idx("CUI ofertant", "CUI furnizor")
                idx_data     = col_idx("Data contract", "Data achizitie", "Data publicare")
                idx_cpv      = col_idx("Denumire CPV", "Denumire produs", "Obiect")
                idx_numar    = col_idx("Numar contract", "Numar achizitie", "ID")

                debug_log.append(f"COLS {res_name}: cui_ac={idx_cui_ac} val={idx_valoare} castig={idx_castig}")

                if idx_cui_ac is None:
                    wb.close()
                    debug_log.append(f"NO_CUI_COL {res_name} hdrs={hdrs[:5]}")
                    continue

                rand_idx = 0
                found_here = 0
                for row in rows_iter:
                    rand_idx += 1
                    if not row or not row[idx_cui_ac]:
                        continue
                    _cui_row = str(row[idx_cui_ac]).strip()
                    if _cui_row.upper().startswith('RO'):
                        _cui_row = _cui_row[2:]
                    if _cui_row != str(cui).strip():
                        continue

                    found_here += 1
                    # Valoare
                    valoare = 0.0
                    if idx_valoare is not None and row[idx_valoare]:
                        try:
                            valoare = float(str(row[idx_valoare]).replace(",", ".").replace(" ", ""))
                        except (ValueError, TypeError):
                            pass

                    # Dată
                    data_str = ""
                    if idx_data is not None and row[idx_data]:
                        d = row[idx_data]
                        try:
                            data_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                        except Exception:
                            data_str = str(d)[:10]

                    tip_proc = str(row[idx_proc]).strip() if idx_proc is not None and row[idx_proc] else ""

                    # nr_ofertanti: deducem din tip procedură (nu e în export)
                    nr_ofertanti = 1
                    if any(kw in tip_proc.lower() for kw in ["deschis", "restrâns", "competitiv"]):
                        nr_ofertanti = 2  # cel puțin 2 în proceduri competitive

                    cid = f"{tip_sursa}-{an}-{rand_idx}"
                    contracte.append({
                        "id": cid,
                        "numar": str(row[idx_numar]).strip() if idx_numar is not None and row[idx_numar] else cid,
                        "titlu": str(row[idx_cpv]).strip() if idx_cpv is not None and row[idx_cpv] else "Nespecificat",
                        "valoare_ron": valoare,
                        "moneda": "RON",
                        "tip_procedura": tip_proc,
                        "data_publicare": data_str,
                        "castigator": str(row[idx_castig]).strip() if idx_castig is not None and row[idx_castig] else "Necunoscut",
                        "castigator_cui": str(row[idx_cui_casg]).strip() if idx_cui_casg is not None and row[idx_cui_casg] else "",
                        "nr_ofertanti": nr_ofertanti,
                        "sursa": f"data.gov.ro/{tip_sursa}/{an}",
                    })

                debug_log.append(f"SCAN {res_name}: rows={rand_idx} matches={found_here}")
                wb.close()
                surse_ok += 1

            except Exception as e:
                elapsed = time.time() - t_start
                msg = f"ERR {res_name} ({elapsed:.1f}s): {e}"
                print(f"    \u26a0 {msg}")
                debug_log.append(msg)

    summary = f"surse_ok={surse_ok} contracte={len(contracte)}"
    print(f"    \u2713 {summary}")
    debug_log.append(summary)

    if not contracte:
        print("    \u2717 Nu s-au găsit contracte reale în data.gov.ro.")

    return contracte, debug_log
# ==============================================================================
# 3. HOTĂRÂRI CONSILIU LOCAL — ANALIZĂ OCR
# ==============================================================================

HCL_URL_2025 = "https://www.primariapantelimon.ro/hotarari-2025/"
HCL_URL_2024 = "https://www.primariapantelimon.ro/hotarari-2024/"

# Cuvinte cheie care indică proceduri de urgență sau potențiale nereguli
HCL_RED_FLAG_KEYWORDS = {
    "urgenta_procedura": [
        "negociere fără publicare", "negociere fara publicare",
        "procedură de urgență", "procedura de urgenta",
        "atribuire directă", "atribuire directa",
        "fără licitație", "fara licitatie",
    ],
    "rectificare_bugetara": [
        "rectificare bugetară", "rectificare bugetara",
        "rectificare a bugetului", "modificare buget",
    ],
    "sedinta_extraordinara": [
        "convocare de îndată", "convocare de indata",
        "ședință extraordinară", "sedinta extraordinara",
    ],
}


def fetch_hcl_metadata(
    url: str,
    cache_db: str = "hcl_cache.db",
    ttl_zile: int = TTL_HCL_DAYS,
) -> list:
    """Extrage lista de HCL-uri (PDF-uri) de pe pagina primăriei.

    Foloseşte SQLite cache cu TTL ttl_zile (implicit TTL_HCL_DAYS) — pagina de
    hotărâri se actualizează la fiecare ședință a Consiliului Local.
    """
    import sqlite3
    import json as json_mod
    from datetime import timedelta as _timedelta

    def _init_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hcl_metadata (
                url TEXT PRIMARY KEY, extras_la TEXT, date_json TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get(conn, key):
        row = conn.execute(
            "SELECT date_json, extras_la FROM hcl_metadata WHERE url=?", (key,)
        ).fetchone()
        if not row:
            return None
        date_json, extras_la = row
        try:
            if datetime.now() - datetime.fromisoformat(extras_la) < _timedelta(days=ttl_zile):
                return json_mod.loads(date_json)
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, key, results):
        conn.execute(
            "INSERT OR REPLACE INTO hcl_metadata (url, extras_la, date_json) VALUES (?,?,?)",
            (key, datetime.now().isoformat(), json_mod.dumps(results, ensure_ascii=False))
        )
        conn.commit()

    conn = _init_cache(cache_db)
    cached = _cache_get(conn, url)
    if cached is not None:
        conn.close()
        print(f"    ✓ HCL {url} (din cache, TTL {ttl_zile}z)")
        return cached

    results = _fetch_hcl_metadata_live(url)
    _cache_set(conn, url, results)
    conn.close()
    return results


def _fetch_hcl_metadata_live(url: str) -> list:
    """Logica de fetch propriu-zisă pentru fetch_hcl_metadata(), fără cache."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠ Nu am putut accesa {url}: {e}")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if not any(kw in (text + href).lower() for kw in ["hcl", "hotarare", "hotărâre", ".pdf"]):
            continue
        if not href.lower().endswith(".pdf"):
            continue
        if not href.startswith("http"):
            href = "https://www.primariapantelimon.ro" + href
        tip = "extraordinara" if "extraordinar" in text.lower() or "extraordinar" in href.lower() else "ordinara"
        results.append({
            "titlu": text[:120],
            "url": href,
            "tip": tip,
            "filename": href.split("/")[-1],
        })
    return results


def ocr_pdf_prima_pagina(url: str, max_pages: int = 3) -> str:
    """
    Descarcă PDF-ul și extrage textul în două moduri:
    1. PyMuPDF (fitz) — extrage text digital direct (fără OCR, rapid, fără Poppler)
    2. Dacă textul e prea scurt (PDF scanat), aplică OCR cu pytesseract pe imagini
    Returnează textul extras (lowercase) sau '' dacă eșuează.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""

    try:
        r = requests.get(url, headers=HEADERS, timeout=40)
        if r.status_code != 200:
            return ""

        pdf_bytes = r.content
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_total = ""

        # Pas 1: extrage text digital (funcționează pentru PDF-uri native)
        for page_num in range(min(max_pages, len(doc))):
            text_total += doc[page_num].get_text() + "\n"

        # Pas 2: dacă textul e prea scurt → PDF scanat → aplică OCR
        if len(text_total.strip()) < 100:
            try:
                import pytesseract
                from PIL import Image
                import io
                # Setăm calea Tesseract explicit pentru Windows (dacă nu e în PATH)
                for _tp in [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                    r"C:\Users\HP\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
                ]:
                    if os.path.exists(_tp):
                        pytesseract.pytesseract.tesseract_cmd = _tp
                        break
                text_total = ""
                for page_num in range(min(max_pages, len(doc))):
                    page = doc[page_num]
                    # Renderizează pagina ca imagine (200 DPI)
                    mat = fitz.Matrix(200/72, 200/72)
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_bytes))
                    text_total += pytesseract.image_to_string(img, lang="ron+eng") + "\n"
            except Exception as ocr_err:
                print(f"      ⚠ OCR fallback eșuat: {ocr_err}")

        doc.close()
        return text_total.lower()
    except Exception as e:
        print(f"      ⚠ Extragere text PDF eșuată: {e}")
        return ""


def analizeaza_hcl(stare_anterioara: dict) -> dict:
    """
    Analizează hotărârile Consiliului Local:
    1. Metadata (fără OCR): rata ședințelor extraordinare
    2. OCR (doar HCL-uri noi față de rularea anterioară): caută cuvinte cheie red flag

    Returnează dict cu statistici și lista de red flags HCL.
    """
    print("  [HCL] Analizez hotărârile Consiliului Local...")

    ocr_disponibil = False
    try:
        import fitz  # PyMuPDF
        ocr_disponibil = True
        # Verifică și dacă tesseract e disponibil pentru PDF-uri scanate
        try:
            import pytesseract
            # Setăm calea Tesseract explicit pentru Windows (dacă nu e în PATH)
            _tesseract_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                r"C:\Users\HP\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
            ]
            for _tp in _tesseract_paths:
                if os.path.exists(_tp):
                    pytesseract.pytesseract.tesseract_cmd = _tp
                    break
            pytesseract.get_tesseract_version()
            print("    ✓ OCR complet disponibil (PyMuPDF + Tesseract)")
        except Exception:
            print("    ✓ Extragere text PDF disponibilă (PyMuPDF — text digital)")
            print("      ℹ  Tesseract indisponibil — PDF-urile scanate vor fi sărite")
    except ImportError:
        print("    ⚠ OCR indisponibil — analiză doar din metadata/nume fișiere")
        print("      → Rulează instaleaza_ocr.bat pentru a activa analiza completă")

    hcl_list = []
    for url in [HCL_URL_2025, HCL_URL_2024]:
        found = fetch_hcl_metadata(url)
        hcl_list.extend(found)
        print(f"    → {url.split('/')[-2]}: {len(found)} HCL-uri găsite")

    if not hcl_list:
        print("    ✗ Nu s-au putut obține HCL-urile.")
        return {"flags": [], "statistici": {}, "hcl_list": []}

    total = len(hcl_list)
    extraordinare = [h for h in hcl_list if h["tip"] == "extraordinara"]
    ordinare = [h for h in hcl_list if h["tip"] == "ordinara"]
    pct_extra = round(len(extraordinare) / total * 100) if total else 0

    print(f"    → Total: {total} HCL | Ordinare: {len(ordinare)} | Extraordinare: {len(extraordinare)} ({pct_extra}%)")

    flags_hcl = []

    # FLAG 1: Rată ridicată de ședințe extraordinare (§2.6 — funcție pură)
    flags_hcl.extend(detect_sedinte_extraordinare({
        "total_hcl": total,
        "extraordinare": len(extraordinare),
        "pct_extraordinare": pct_extra,
    }))

    # FLAG 2: OCR pe HCL-urile noi
    if ocr_disponibil:
        hcl_vazute = set(stare_anterioara.get("hcl_urls_vazute", []))
        hcl_noi = [h for h in hcl_list if h["url"] not in hcl_vazute]
        print(f"    → OCR: {len(hcl_noi)} HCL-uri noi de procesat")

        for hcl in hcl_noi[:10]:  # max 10 per rulare pentru a nu depăși timeout
            print(f"      OCR: {hcl['titlu'][:60]}...")
            text = ocr_pdf_prima_pagina(hcl["url"], max_pages=2)
            if not text:
                continue

            for tip_flag, keywords in HCL_RED_FLAG_KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        flags_hcl.append({
                            "tip": f"hcl_{tip_flag}",
                            "severitate": "MAJOR",
                            "titlu": f"HCL: {tip_flag.replace('_', ' ').title()} detectat",
                            "descriere": (
                                f"Cuvânt cheie '{kw}' detectat în: {hcl['titlu']}. "
                                f"Verificați documentul pentru detalii."
                            ),
                            "contract_id": hcl["filename"],
                            "valoare": 0,
                            "furnizor": "Consiliul Local Pantelimon",
                            "data": datetime.now().strftime("%Y-%m-%d"),
                            "tip_procedura": hcl["tip"],
                        })
                        break

    statistici = {
        "total_hcl": total,
        "ordinare": len(ordinare),
        "extraordinare": len(extraordinare),
        "pct_extraordinare": pct_extra,
        "ocr_disponibil": ocr_disponibil,
    }

    print(f"    ✓ Analiză HCL finalizată. Red flags HCL: {len(flags_hcl)}")
    return {"flags": flags_hcl, "statistici": statistici, "hcl_list": hcl_list}


# ==============================================================================
# §3.1  CURTEA DE CONTURI — rapoarte de audit UAT
# ==============================================================================

def fetch_curtea_de_conturi(
    uat_nume: str = "Pantelimon",
    cache_db: str = "curtea_conturi_cache.db",
    ttl_zile: int = TTL_CURTEA_CONTURI_DAYS,
    timeout: int = 20,
) -> list:
    """§3.1 Caută rapoarte de audit Curtea de Conturi pentru UAT.

    Strategia: caută pe curteadeconturi.ro după numele UAT + filtrează
    rezultatele HTML cu BeautifulSoup. Returnează lista de rapoarte găsite.
    Foloseşte SQLite cache cu TTL TTL_CURTEA_CONTURI_DAYS (rapoartele CC apar anual).

    Args:
        uat_nume:  Numele UAT de căutat (ex: "Pantelimon")
        cache_db:  Cale fișier SQLite cache
        ttl_zile:  TTL cache în zile
        timeout:   Timeout HTTP în secunde

    Returns:
        list [{titlu, url, an, tip, data_publicare}]
        Scrie curtea_de_conturi.json cu rezultatele.
    """
    import sqlite3
    import json as json_mod
    import re
    from datetime import datetime, timedelta

    SEARCH_URL = "https://www.curteadeconturi.ro/Publicatii/Rapoarte_de_audit"
    UA = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"

    # ── Cache SQLite ──────────────────────────────────────────────
    def _init_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_rapoarte (
                uat       TEXT,
                extras_la TEXT,
                date_json TEXT
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS cc_uat_idx ON cc_rapoarte(uat)
        """)
        conn.commit()
        return conn

    def _cache_get(conn, uat: str):
        row = conn.execute(
            "SELECT date_json, extras_la FROM cc_rapoarte WHERE uat=?", (uat,)
        ).fetchone()
        if not row:
            return None
        date_json, extras_la = row
        try:
            if datetime.now() - datetime.fromisoformat(extras_la) < timedelta(days=ttl_zile):
                return json_mod.loads(date_json)
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, uat: str, rapoarte: list):
        conn.execute(
            "INSERT OR REPLACE INTO cc_rapoarte (uat, extras_la, date_json) VALUES (?,?,?)",
            (uat, datetime.now().isoformat(), json_mod.dumps(rapoarte, ensure_ascii=False))
        )
        conn.commit()

    # ── Fetch și parse HTML ───────────────────────────────────────
    def _fetch_rapoarte(uat: str) -> list:
        """Caută rapoartele pe curteadeconturi.ro."""
        try:
            from bs4 import BeautifulSoup as BS
            import urllib.request, urllib.parse

            # Pagina principală rapoarte de audit
            req = urllib.request.Request(
                SEARCH_URL,
                headers={"User-Agent": UA, "Accept": "text/html"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            soup = BS(html, "html.parser")
            rapoarte = []

            # Căutăm linkuri care conțin UAT-ul (case-insensitive)
            uat_lower = uat.lower()
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = a["href"]
                if uat_lower not in text.lower() and uat_lower not in href.lower():
                    continue
                if not href.startswith("http"):
                    href = "https://www.curteadeconturi.ro" + href

                # Extrage anul din text sau href (4 cifre consecutiv)
                ani = re.findall(r'\b(20\d{2})\b', text + " " + href)
                an = max(ani) if ani else ""

                rapoarte.append({
                    "titlu":           text[:200],
                    "url":             href,
                    "an":              an,
                    "tip":             "Raport audit",
                    "data_publicare":  an + "-01-01" if an else "",
                    "sursa":           "curteadeconturi.ro",
                })

            # Fallback: căutare generică dacă pagina principală nu conține UAT
            if not rapoarte:
                search_url = (
                    "https://www.curteadeconturi.ro/search?q="
                    + urllib.parse.quote(uat + " audit")
                )
                req2 = urllib.request.Request(
                    search_url,
                    headers={"User-Agent": UA, "Accept": "text/html"}
                )
                try:
                    with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                        html2 = resp2.read().decode("utf-8", errors="replace")
                    soup2 = BS(html2, "html.parser")
                    for a in soup2.find_all("a", href=True):
                        text = a.get_text(strip=True)
                        href = a["href"]
                        if uat_lower not in text.lower():
                            continue
                        if not href.startswith("http"):
                            href = "https://www.curteadeconturi.ro" + href
                        ani = re.findall(r'\b(20\d{2})\b', text + " " + href)
                        an = max(ani) if ani else ""
                        rapoarte.append({
                            "titlu":          text[:200],
                            "url":            href,
                            "an":             an,
                            "tip":            "Raport audit (search)",
                            "data_publicare": an + "-01-01" if an else "",
                            "sursa":          "curteadeconturi.ro/search",
                        })
                except Exception:
                    pass

            return rapoarte

        except ImportError:
            # BeautifulSoup nu e disponibilă — returnăm lista goală cu avertisment
            print("  ⚠️  §3.1 CC: BeautifulSoup lipsă (pip install beautifulsoup4)")
            return []
        except Exception as exc:
            print(f"  ⚠️  §3.1 CC: eroare fetch curteadeconturi.ro — {exc}")
            return []

    # ── Main logic ───────────────────────────────────────────────
    conn = _init_cache(cache_db)
    rapoarte = _cache_get(conn, uat_nume)

    if rapoarte is None:
        print(f"  [CC] Fetch rapoarte audit pentru UAT '{uat_nume}'…")
        rapoarte = _fetch_rapoarte(uat_nume)
        _cache_set(conn, uat_nume, rapoarte)
        print(f"  ✓ CC: {len(rapoarte)} rapoarte găsite → cache actualizat")
    else:
        print(f"  ✓ CC: {len(rapoarte)} rapoarte (din cache) pentru '{uat_nume}'")

    conn.close()

    # Scriere curtea_de_conturi.json
    with open("curtea_de_conturi.json", "w", encoding="utf-8") as fout:
        json_mod.dump(rapoarte, fout, ensure_ascii=False, indent=2)

    return rapoarte


# ==============================================================================
# §3.2  ANI — declarații de avere aleși locali
# ==============================================================================

def fetch_declaratii_avere(
    uat: str = "Pantelimon",
    cache_db: str = "ani_cache.db",
    ttl_zile: int = TTL_ANI_DAYS,
    timeout: int = 20,
) -> list:
    """§3.2 Scraping declarații de avere aleși locali de pe integritate.eu (ANI).

    Caută pe https://www.integritate.eu/Search?cuvinte={uat} și extrage
    lista de aleși cu linkuri la declarațiile PDF.

    Notă GDPR: afișează doar funcții publice + nume; NU CNP / adresă personală.

    Args:
        uat:       Cuvânt de căutat (ex: "Pantelimon")
        cache_db:  Cale fișier SQLite cache
        ttl_zile:  TTL cache în zile
        timeout:   Timeout HTTP în secunde

    Returns:
        list [{nume, functie, an, url_declaratie, tip}]
        Scrie ani_declaratii.json cu rezultatele.
    """
    import sqlite3
    import json as json_mod
    import re
    from datetime import datetime, timedelta

    SEARCH_URL = f"https://www.integritate.eu/Search?cuvinte={uat}"
    UA = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"

    # ── Cache SQLite ──────────────────────────────────────────────
    def _init_ani_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ani_declaratii (
                uat       TEXT,
                extras_la TEXT,
                date_json TEXT
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ani_uat_idx ON ani_declaratii(uat)
        """)
        conn.commit()
        return conn

    def _cache_get(conn, uat_key: str):
        row = conn.execute(
            "SELECT date_json, extras_la FROM ani_declaratii WHERE uat=?", (uat_key,)
        ).fetchone()
        if not row:
            return None
        date_json, extras_la = row
        try:
            if datetime.now() - datetime.fromisoformat(extras_la) < timedelta(days=ttl_zile):
                return json_mod.loads(date_json)
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, uat_key: str, declaratii: list):
        conn.execute(
            "INSERT OR REPLACE INTO ani_declaratii (uat, extras_la, date_json) VALUES (?,?,?)",
            (uat_key, datetime.now().isoformat(), json_mod.dumps(declaratii, ensure_ascii=False))
        )
        conn.commit()

    # ── Fetch și parse HTML ───────────────────────────────────────
    def _fetch_declaratii(uat_key: str) -> list:
        try:
            from bs4 import BeautifulSoup as BS
            import urllib.request, urllib.parse

            url = f"https://www.integritate.eu/Search?cuvinte={urllib.parse.quote(uat_key)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "text/html"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            soup = BS(html, "html.parser")
            declaratii = []

            # Structura tipică integritate.eu: tabele sau divuri cu
            # coloana Nume, Funcție, Tip declarație, An, link PDF
            for row in soup.find_all(["tr", "div"], class_=re.compile(r"result|row|item", re.I)):
                cells = row.find_all(["td", "span", "div"])
                if len(cells) < 2:
                    continue
                text_row = " | ".join(c.get_text(strip=True) for c in cells)
                if not text_row.strip():
                    continue

                # Link PDF
                link = row.find("a", href=re.compile(r"\.pdf", re.I))
                pdf_url = ""
                if link:
                    href = link.get("href", "")
                    pdf_url = href if href.startswith("http") else "https://www.integritate.eu" + href

                # Extrage an
                ani = re.findall(r'\b(20\d{2})\b', text_row)
                an = max(ani) if ani else ""

                # Tip declaratie
                tip = "declaratie_avere"
                if re.search(r"interese", text_row, re.I):
                    tip = "declaratie_interese"

                declaratii.append({
                    "text_row":        text_row[:300],
                    "url_declaratie":  pdf_url,
                    "an":              an,
                    "tip":             tip,
                    "sursa":           "integritate.eu",
                })

            return declaratii

        except ImportError:
            print("  ⚠️  §3.2 ANI: BeautifulSoup lipsă (pip install beautifulsoup4)")
            return []
        except Exception as exc:
            print(f"  ⚠️  §3.2 ANI: eroare fetch integritate.eu — {exc}")
            return []

    # ── Main logic ───────────────────────────────────────────────
    conn = _init_ani_cache(cache_db)
    declaratii = _cache_get(conn, uat)

    if declaratii is None:
        print(f"  [ANI] Fetch declarații avere pentru '{uat}'…")
        declaratii = _fetch_declaratii(uat)
        _cache_set(conn, uat, declaratii)
        print(f"  ✓ ANI: {len(declaratii)} declarații găsite → cache actualizat")
    else:
        print(f"  ✓ ANI: {len(declaratii)} declarații (din cache) pentru '{uat}'")

    conn.close()

    # Scriere ani_declaratii.json
    with open("ani_declaratii.json", "w", encoding="utf-8") as fout:
        json_mod.dump(declaratii, fout, ensure_ascii=False, indent=2)

    return declaratii


# ==============================================================================
# §3.4  TED EUROPA — anunțuri europene asociate cumpărătorului
# ==============================================================================

def search_ted_for_buyer(
    cif_buyer: str,
    year: int = None,
    cache_db: str = "ted_cache.db",
    ttl_zile: int = TTL_TED_DAYS,
    timeout: int = 30,
) -> list:
    """§3.4 Caută anunțuri TED Europa pentru un cumpărător identificat prin CIF.

    Pentru 2026–2027, pragurile Directivei 2014/24/UE sunt 216.000 EUR fără TVA
    pentru produse/servicii atribuite de autorități locale și 5.404.000 EUR fără
    TVA pentru lucrări. Funcția inventariază anunțurile TED; absența unui rezultat
    nu este tratată singură drept dovadă a încălcării obligațiilor de publicare.

    Args:
        cif_buyer: CIF-ul cumpărătorului (ex: "4420759")
        year:      An de filtrat (implicit: anul curent)
        cache_db:  Cale fișier SQLite cache
        ttl_zile:  TTL cache în zile (implicit 7 — anunțuri apar zilnic)
        timeout:   Timeout HTTP în secunde

    Returns:
        list [{notice_id, title, publication_date, value_eur, procedure_type, url}]
        Scrie ted_notices.json cu rezultatele.
    """
    import sqlite3
    import json as json_mod
    from datetime import datetime, timedelta
    import urllib.request, urllib.parse

    if year is None:
        year = datetime.now().year

    UA = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"
    TED_API = "https://ted.europa.eu/api/v3.0/notices/search"

    # ── Cache ────────────────────────────────────────────────────
    def _init_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ted_notices (
                cache_key TEXT PRIMARY KEY,
                extras_la TEXT,
                date_json TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get(conn, key):
        row = conn.execute(
            "SELECT date_json, extras_la FROM ted_notices WHERE cache_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        try:
            if datetime.now() - datetime.fromisoformat(row[1]) < timedelta(days=ttl_zile):
                return json_mod.loads(row[0])
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, key, data):
        conn.execute(
            "INSERT OR REPLACE INTO ted_notices (cache_key, extras_la, date_json) VALUES (?,?,?)",
            (key, datetime.now().isoformat(), json_mod.dumps(data, ensure_ascii=False))
        )
        conn.commit()

    # ── Fetch TED API ─────────────────────────────────────────────
    def _fetch_ted(cif: str, an: int) -> list:
        params = urllib.parse.urlencode({
            "q":      f'BUYER-NATIONALID="{cif}"',
            "fields": "notice-id,short-description,publication-date,estimated-value-setting,procedure-type",
            "scope":  3,
            "limit":  100,
        })
        url = f"{TED_API}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json_mod.loads(resp.read().decode("utf-8"))
            notices = data.get("notices", data.get("results", []))
            rezultate = []
            for n in notices:
                pub_date = n.get("publication-date", n.get("publicationDate", ""))
                # Filtrăm după an dacă e specificat
                if pub_date and str(an) not in pub_date:
                    continue
                val = n.get("estimated-value-setting", {})
                val_eur = val.get("amount", 0) if isinstance(val, dict) else 0
                notice_id = n.get("notice-id", n.get("noticeId", ""))
                rezultate.append({
                    "notice_id":        notice_id,
                    "title":            n.get("short-description", n.get("title", ""))[:200],
                    "publication_date": pub_date,
                    "value_eur":        val_eur,
                    "procedure_type":   n.get("procedure-type", ""),
                    "url":              f"https://ted.europa.eu/en/notice/{notice_id}" if notice_id else "",
                    "sursa":            "ted.europa.eu",
                })
            return rezultate
        except Exception as exc:
            print(f"  ⚠️  §3.4 TED: eroare fetch — {exc}")
            return []

    # ── Main logic ───────────────────────────────────────────────
    cache_key = f"{cif_buyer}_{year}"
    conn = _init_cache(cache_db)
    notices = _cache_get(conn, cache_key)

    if notices is None:
        print(f"  [TED] Fetch anunțuri pentru CIF {cif_buyer}, an {year}…")
        notices = _fetch_ted(cif_buyer, year)
        _cache_set(conn, cache_key, notices)
        print(f"  ✓ TED: {len(notices)} anunțuri găsite → cache actualizat")
    else:
        print(f"  ✓ TED: {len(notices)} anunțuri (din cache) pentru CIF {cif_buyer}/{year}")

    conn.close()

    with open("ted_notices.json", "w", encoding="utf-8") as fout:
        json_mod.dump(notices, fout, ensure_ascii=False, indent=2)

    return notices


# ==============================================================================
# §3.5  MONITORUL OFICIAL LOCAL — rectificări bugetare și HCL
# ==============================================================================

def fetch_mol_primarie(
    url: str = "https://www.primariapantelimon.ro/mol/",
    cache_db: str = "mol_cache.db",
    ttl_zile: int = TTL_MOL_DAYS,
    timeout: int = 20,
) -> list:
    """§3.5 Scraping Monitorul Oficial Local al primăriei.

    Caută rectificări bugetare și HCL-uri cu sume concrete. Foloseşte
    BeautifulSoup pentru extragere linkuri + texte.

    Args:
        url:       URL pagina MOL primărie
        cache_db:  Cale fișier SQLite cache
        ttl_zile:  TTL cache în zile (implicit TTL_MOL_DAYS)
        timeout:   Timeout HTTP în secunde

    Returns:
        list [{titlu, url, data, tip, suma_ron}]
        Scrie mol_primarie.json cu rezultatele.
    """
    import sqlite3
    import json as json_mod
    import re
    from datetime import datetime, timedelta
    import urllib.request

    UA = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"

    # ── Cache ─────────────────────────────────────────────────────
    def _init_cache(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mol_entries (
                url_cheie TEXT PRIMARY KEY,
                extras_la TEXT,
                date_json TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get(conn, url_cheie):
        row = conn.execute(
            "SELECT date_json, extras_la FROM mol_entries WHERE url_cheie=?", (url_cheie,)
        ).fetchone()
        if not row:
            return None
        try:
            if datetime.now() - datetime.fromisoformat(row[1]) < timedelta(days=ttl_zile):
                return json_mod.loads(row[0])
        except (ValueError, TypeError):
            pass
        return None

    def _cache_set(conn, url_cheie, data):
        conn.execute(
            "INSERT OR REPLACE INTO mol_entries (url_cheie, extras_la, date_json) VALUES (?,?,?)",
            (url_cheie, datetime.now().isoformat(), json_mod.dumps(data, ensure_ascii=False))
        )
        conn.commit()

    # ── Fetch și parse ────────────────────────────────────────────
    def _fetch_mol(mol_url: str) -> list:
        try:
            from bs4 import BeautifulSoup as BS
            req = urllib.request.Request(
                mol_url,
                headers={"User-Agent": UA, "Accept": "text/html"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            soup = BS(html, "html.parser")
            intrari = []

            # Pattern: linkuri cu cuvinte-cheie bugetar
            kw_bugetar = re.compile(
                r"rectific|HCL|hotarare|hotărâre|buget|anexa|aprobare", re.I
            )
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = a["href"]
                if not kw_bugetar.search(text) and not kw_bugetar.search(href):
                    continue
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(mol_url, href)

                # Extrage sumă RON din text (ex: "2.300.000 RON" sau "2,3M RON")
                suma_ron = 0.0
                match_ron = re.search(
                    r'([\d\.,]+)\s*(?:milioane?|M)?\s*RON',
                    text, re.I
                )
                if match_ron:
                    try:
                        nr_str = match_ron.group(1).replace(".", "").replace(",", ".")
                        suma_ron = float(nr_str)
                        if re.search(r"milio|M\s*RON", match_ron.group(0), re.I):
                            suma_ron *= 1_000_000
                    except ValueError:
                        pass

                # Tip
                tip = "rectificare_buget" if re.search(r"rectific", text, re.I) else "hcl"

                # Data din text sau href (dd.mm.yyyy sau yyyy-mm-dd)
                data_str = ""
                dm = re.search(r'\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b', text)
                if dm:
                    data_str = f"{dm.group(3)}-{dm.group(2):>02}-{dm.group(1):>02}"

                intrari.append({
                    "titlu":    text[:200],
                    "url":      href,
                    "data":     data_str,
                    "tip":      tip,
                    "suma_ron": suma_ron,
                    "sursa":    "mol.primariapantelimon.ro",
                })

            return intrari

        except ImportError:
            print("  ⚠️  §3.5 MOL: BeautifulSoup lipsă (pip install beautifulsoup4)")
            return []
        except Exception as exc:
            print(f"  ⚠️  §3.5 MOL: eroare fetch {url} — {exc}")
            return []

    # ── Main logic ────────────────────────────────────────────────
    conn = _init_cache(cache_db)
    intrari = _cache_get(conn, url)

    if intrari is None:
        print(f"  [MOL] Fetch Monitorul Oficial Local…")
        intrari = _fetch_mol(url)
        _cache_set(conn, url, intrari)
        print(f"  ✓ MOL: {len(intrari)} intrări găsite → cache actualizat")
    else:
        print(f"  ✓ MOL: {len(intrari)} intrări (din cache)")

    conn.close()

    with open("mol_primarie.json", "w", encoding="utf-8") as fout:
        json_mod.dump(intrari, fout, ensure_ascii=False, indent=2)

    return intrari


def fetch_pnrr_projects(
    cif_beneficiar: str = "4420759",
    cache_db: str = "pnrr_cache.db",
    ttl_zile: int = TTL_PNRR_DAYS,
    timeout: int = 30,
) -> list:
    """§3.3 Caută proiectele PNRR ale unui UAT pe proiecte.pnrr.gov.ro.

    Endpoint public oficial. Returnează lista proiectelor cu titlu, valoare,
    status, program. Cache SQLite TTL 7 zile.

    Args:
        cif_beneficiar: CUI-ul primăriei (fără prefix RO).
        cache_db:       Calea la fișierul SQLite cache.
        ttl_zile:       Durata validității cache în zile.
        timeout:        Timeout HTTP în secunde.

    Returns:
        list[dict] cu proiectele găsite, sau [] la eroare.
    """
    import json as json_mod
    import sqlite3
    import urllib.request
    import urllib.parse
    from datetime import datetime, timedelta

    BASE_URL = "https://proiecte.pnrr.gov.ro"
    USER_AGENT = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"
    OUTPUT_FILE = "pnrr_projects.json"

    # ── Cache SQLite ──────────────────────────────────────────────────────────
    def _init_cache(db):
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pnrr_projects (
                cache_key   TEXT PRIMARY KEY,
                extras_la   TEXT,
                date_json   TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get(conn, key):
        row = conn.execute(
            "SELECT extras_la, date_json FROM pnrr_projects WHERE cache_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        try:
            extras = datetime.fromisoformat(row[0])
            if datetime.now() - extras > timedelta(days=ttl_zile):
                return None
            return json_mod.loads(row[1])
        except (ValueError, TypeError):
            return None

    def _cache_set(conn, key, data):
        conn.execute(
            "INSERT OR REPLACE INTO pnrr_projects VALUES (?,?,?)",
            (key, datetime.now().isoformat(), json_mod.dumps(data, ensure_ascii=False))
        )
        conn.commit()

    # ── Fetch API PNRR ────────────────────────────────────────────────────────
    def _fetch_pnrr(cif):
        """Încearcă API JSON, fallback la scraping HTML."""
        proiecte = []

        # Endpoint 1: API JSON oficial (dacă există)
        api_url = f"{BASE_URL}/api/projects?beneficiary={urllib.parse.quote(cif)}"
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json_mod.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(data, list):
                    proiecte = data
                elif isinstance(data, dict):
                    proiecte = data.get("projects", data.get("results", data.get("data", [])))
            if proiecte:
                return _normalizeaza(proiecte)
        except Exception:
            pass

        # Endpoint 2: pagina de căutare HTML
        search_url = f"{BASE_URL}/proiecte?beneficiar={urllib.parse.quote(cif)}"
        try:
            from html.parser import HTMLParser

            class _PNRRParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.proiecte = []
                    self._in_project = False
                    self._crt = {}
                    self._tag_stack = []

                def handle_starttag(self, tag, attrs):
                    attrs_d = dict(attrs)
                    cls = attrs_d.get("class", "")
                    if "project" in cls.lower() or "card" in cls.lower():
                        self._in_project = True
                        self._crt = {}
                    self._tag_stack.append(tag)

                def handle_endtag(self, tag):
                    if self._tag_stack:
                        self._tag_stack.pop()
                    if self._in_project and self._crt.get("titlu"):
                        self.proiecte.append(dict(self._crt))
                        self._in_project = False
                        self._crt = {}

                def handle_data(self, data):
                    if not self._in_project:
                        return
                    txt = data.strip()
                    if not txt:
                        return
                    if not self._crt.get("titlu"):
                        self._crt["titlu"] = txt[:200]
                    elif "RON" in txt or "EUR" in txt:
                        self._crt["valoare_text"] = txt

            req2 = urllib.request.Request(
                search_url,
                headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req2, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            parser = _PNRRParser()
            parser.feed(html)
            proiecte = parser.proiecte
        except Exception:
            pass

        return _normalizeaza(proiecte)

    def _normalizeaza(raw):
        """Normalizează structura proiectelor la un format consistent."""
        rezultat = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            rezultat.append({
                "titlu":        p.get("titlu") or p.get("title") or p.get("name") or "",
                "cod":          p.get("cod") or p.get("code") or p.get("project_code") or "",
                "valoare_ron":  p.get("valoare_ron") or p.get("value") or p.get("budget") or 0,
                "status":       p.get("status") or p.get("state") or "",
                "program":      p.get("program") or p.get("programme") or "",
                "beneficiar":   p.get("beneficiar") or p.get("beneficiary") or "",
                "link":         p.get("link") or p.get("url") or "",
                "extras_la":    datetime.now().strftime("%Y-%m-%d"),
            })
        return rezultat

    # ── Main logic ────────────────────────────────────────────────────────────
    cache_key = f"pnrr_{cif_beneficiar}"
    conn = _init_cache(cache_db)
    proiecte = _cache_get(conn, cache_key)

    if proiecte is None:
        print(f"  [PNRR] Fetch proiecte.pnrr.gov.ro pentru CIF {cif_beneficiar}…")
        proiecte = _fetch_pnrr(cif_beneficiar)
        _cache_set(conn, cache_key, proiecte)
        print(f"  ✓ PNRR: {len(proiecte)} proiecte → cache actualizat")
    else:
        print(f"  ✓ PNRR: {len(proiecte)} proiecte (din cache)")

    conn.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fout:
        json_mod.dump(proiecte, fout, ensure_ascii=False, indent=2)

    return proiecte


def calculeaza_scor_transparenta(toate_flags: list, contracte: list, statistici_hcl: dict) -> dict:
    """Calculează un indice euristic 0–100; nu este un rating oficial al UAT."""
    ponderi = {
        "achizitii_directe": 0.30,
        "ofertant_unic": 0.20,
        "sedinte_extraordinare": 0.15,
        "fragmentare": 0.15,
        "documente_publicate": 0.10,
        "raspuns_544": 0.10,
    }
    # 1. Achizitii directe CRITIC (30%) — fiecare flag CRITIC scade cu 3p
    n_critic = sum(1 for f in toate_flags if f.get("severitate") == "CRITIC")
    s_achizitii = max(0, 100 - n_critic * 3)
    # 2. Ofertant unic dominant (20%) — procent contracte cu un singur ofertant
    if contracte:
        n_unic = sum(1 for c in contracte if c.get("nr_ofertanti") == 1)
        pct_unic = n_unic / len(contracte) * 100
        s_ofertant = max(0, 100 - pct_unic * 2)
    else:
        s_ofertant = 70
    # 3. Sedinte extraordinare (15%) — scad direct cu procentul
    pct_extra = statistici_hcl.get("pct_extraordinare", 0)
    s_extra = max(0, 100 - pct_extra)
    # 4. Fragmentare contracte (15%) — fiecare flag FRAGMENTARE scade cu 10p
    n_fragment = sum(1 for f in toate_flags if f.get("tip") == "FRAGMENTARE")
    s_fragment = max(0, 100 - n_fragment * 10)
    # 5. Documente publicate (10%) — pagina financiara e goala (confirmat manual)
    s_documente = 30
    # 6. Raspuns la cereri 544/2001 (10%) — necunoscut, default conservator
    s_raspuns = 50
    componente = {
        "achizitii_directe": round(s_achizitii),
        "ofertant_unic": round(s_ofertant),
        "sedinte_extraordinare": round(s_extra),
        "fragmentare": round(s_fragment),
        "documente_publicate": s_documente,
        "raspuns_544": s_raspuns,
    }
    scor_final = sum(componente[k] * ponderi[k] for k in ponderi)
    return {
        "scor": round(scor_final),
        "componente": componente,
        "ponderi": {k: round(v * 100) for k, v in ponderi.items()},
        "componente_estimate": ["documente_publicate", "raspuns_544"],
        "metodologie": (
            "Indice euristic, neoficial. Fiecare componentă este un punctaj 0–100, "
            "apoi se aplică ponderea publicată. Componentele documente_publicate și "
            "raspuns_544 sunt estimări manuale și nu sunt măsurate automat."
        ),
        "data": datetime.now().strftime("%Y-%m-%d"),
    }


def numara_contracte_cu_semnale(flags: list, contracte: list) -> int:
    """Numără contracte unice referite de flaguri, ignorând indicatorii globali."""
    ids_valide = {str(c.get("id", "")) for c in contracte if c.get("id") not in (None, "")}
    gasite = set()
    for flag in flags:
        raw = str(flag.get("contract_id") or "")
        for contract_id in raw.split(","):
            contract_id = contract_id.strip()
            if contract_id in ids_valide:
                gasite.add(contract_id)
    return len(gasite)




# ==============================================================================
# 4. ALGORITMI DE DETECȚIE RED FLAGS (contracte SEAP)
# ==============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# §2.1  Detector fragmentare temporară
# ──────────────────────────────────────────────────────────────────────────────

def detect_fragmentare_temporara(contracte: list, config: dict) -> list:
    """
    §2.1 — Fragmentare temporară: contracte individuale sub-prag ale aceluiași furnizor
    cu titlu similar, în fereastră de 90 de zile, cu sumă combinată > prag legal.
    Diferit de Algoritm 3 (perechi consecutive): agregă TOATE contractele din fereastră.
    Acceptă atât schema internă (valoare_ron/castigator_cui) cât și schema export (valoare/cui).
    """
    import re as _re2
    from collections import defaultdict as _ddict2
    _rev_re = _re2.compile(r'\s*\(Rev\.\d+\)\s*', _re2.IGNORECASE)
    def _val(c):
        return float(c.get("valoare_ron") or c.get("valoare") or 0)

    def _data_str(c):
        return (c.get("data_publicare") or c.get("data") or "").strip()

    grupe = _ddict2(list)
    for c in contracte:
        cui = (c.get("castigator_cui") or c.get("cui") or "").strip()
        if not cui:
            continue
        titlu_canonic = _rev_re.sub("", c.get("titlu", "")).strip().lower()
        prefix = " ".join(titlu_canonic.split()[:4])
        if not prefix:
            continue
        try:
            data_c = datetime.strptime(_data_str(c)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        prag, categorie = _prag_pentru_contract(c, config)
        grupe[(cui, prefix, categorie, prag)].append((data_c, c))

    flags = []
    for (cui, prefix, categorie, prag), items in grupe.items():
        if len(items) < 2:
            continue
        items_sorted = sorted(items, key=lambda x: x[0])

        best_fereastra = None
        best_suma = 0.0

        for i in range(len(items_sorted)):
            d_start = items_sorted[i][0]
            fereastra = [c for d, c in items_sorted[i:] if (d - d_start).days <= 90]
            sub_prag = [c for c in fereastra if _val(c) < prag]
            if len(sub_prag) < 2:
                continue
            suma = sum(_val(c) for c in sub_prag)
            if suma > prag and suma > best_suma:
                best_suma = suma
                best_fereastra = sub_prag

        if best_fereastra is None:
            continue

        furnizor = (best_fereastra[0].get("castigator") or
                    best_fereastra[0].get("firma") or cui)
        ids = ",".join((c.get("id") or "") for c in best_fereastra[:3])
        numar0 = best_fereastra[0].get("numar") or best_fereastra[0].get("id") or "–"
        d0 = _data_str(best_fereastra[0])
        d1 = _data_str(best_fereastra[-1])
        flags.append({
            "tip": "FRAGMENTARE_TEMPORARA",
            "severitate": "CRITIC",
            "titlu": (f"Semnal de fragmentare temporară: {len(best_fereastra)} contracte sub-prag, "
                       f"sumă combinată {_fmt_ron(best_suma)}"),
            "descriere": (
                f'Furnizor "{furnizor}" (CUI {cui}) a primit {len(best_fereastra)} contracte '
                f'individuale sub pragul de {_fmt_ron(prag)}, cu titluri similare '
                f'("{prefix[:50]}"), în fereastră de 90 de zile ({d0} – {d1}). '
                f'Sumă combinată: {_fmt_ron(best_suma)}, care depășește pragul legal. '
                f'Acesta este un semnal automat pentru categoria {categorie}, care necesită '
                f'verificarea obiectului și a valorii estimate totale. Art. 11 alin. (1) din '
                f'Legea 98/2016 interzice divizarea cu scopul evitării procedurilor aplicabile.'
            ),
            "contract_id": ids,
            "contract_numar": f"{numar0} + {len(best_fereastra) - 1} altele",
            "valoare": best_suma,
            "furnizor": furnizor,
            "cif_furnizor": cui,
            "data": d0,
            "tip_procedura": (best_fereastra[0].get("tip_procedura") or
                               best_fereastra[0].get("tip") or ""),
            "nr_contracte": len(best_fereastra),
            "categorie_contract": categorie,
            "prag_aplicat": prag,
        })
    return sorted(flags, key=lambda f: f["valoare"], reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# §2.2  Detector concentrare furnizor
# ──────────────────────────────────────────────────────────────────────────────

def detect_concentrare_furnizor(contracte: list, config: dict) -> list:
    """
    §2.2 — Concentrare furnizor: top 3 furnizori dețin > 60% din valoarea totală.
    Diferit de Algoritm 5 (FURNIZOR_DOMINANT per-firmă): analizează concentrarea agregată.
    Acceptă schema internă (valoare_ron/castigator_cui) și export (valoare/cui).
    """
    from collections import defaultdict as _ddict3
    valori = _ddict3(float)
    cui_to_name: dict = {}
    for c in contracte:
        cui = (c.get("castigator_cui") or c.get("cui") or "").strip()
        if not cui:
            continue
        val = float(c.get("valoare_ron") or c.get("valoare") or 0)
        valori[cui] += val
        if cui not in cui_to_name:
            cui_to_name[cui] = c.get("castigator") or c.get("firma") or cui

    total = sum(valori.values())
    if total <= 0 or len(valori) < 3:
        return []

    top3 = sorted(valori.items(), key=lambda x: x[1], reverse=True)[:3]
    suma_top3 = sum(v for _, v in top3)
    pct_top3 = suma_top3 / total * 100

    if pct_top3 < 60.0:
        return []

    severitate = "CRITIC" if pct_top3 > 80 else "MAJOR"
    top3_desc = ", ".join(
        f'"{cui_to_name.get(cui, cui)}" ({v / total * 100:.0f}%)'
        for cui, v in top3
    )
    return [{
        "tip": "CONCENTRARE_FURNIZOR",
        "severitate": severitate,
        "titlu": f"Concentrare ridicată: top 3 furnizori dețin {pct_top3:.0f}% din contracte",
        "descriere": (
            f"Primii 3 furnizori ({top3_desc}) dețin împreună {pct_top3:.0f}% "
            f"din valoarea totală contractată ({_fmt_ron(suma_top3)} din {_fmt_ron(total)}). "
            f"Concentrare ridicată indică posibile specificații preferențiale sau relații "
            f"privilegiate (art. 57-64 Legea 98/2016 — conflicte de interese). "
            f"Referință: concentrare top-3 > 60% din valoarea totală este considerată "
            f"indicator de risc pentru achizițiile publice ale UAT."
        ),
        "contract_id": "global",
        "contract_numar": "–",
        "valoare": suma_top3,
        "furnizor": "Multiple",
        "cif_furnizor": "",
        "data": datetime.now().strftime("%Y-%m-%d"),
        "tip_procedura": "Multiple",
        "top3_furnizori": [
            {"cui": cui, "valoare": v, "pct": round(v / total * 100, 1)}
            for cui, v in top3
        ],
    }]


# ──────────────────────────────────────────────────────────────────────────────
# §2.6  Detector ședințe extraordinare excesive (funcție pură testabilă)
# ──────────────────────────────────────────────────────────────────────────────

def detect_sedinte_extraordinare(statistici_hcl: dict) -> list:
    """
    §2.6 — Rată ridicată ședințe extraordinare (funcție pură, testabilă).
    Input: dict cu cheile total_hcl, extraordinare, pct_extraordinare.
    Prag: > 25% → MAJOR; >= 40% → CRITIC (Legea 52/2003, art. 7).
    """
    total = statistici_hcl.get("total_hcl", 0)
    n_extra = statistici_hcl.get("extraordinare", 0)
    pct_extra = statistici_hcl.get("pct_extraordinare", 0)

    if total < 3 or pct_extra <= 25:
        return []

    severitate = "CRITIC" if pct_extra >= 40 else "MAJOR"
    return [{
        "tip": "SEDINTE_EXTRAORDINARE_EXCESIVE",
        "severitate": severitate,
        "titlu": f"Rată ridicată de ședințe extraordinare: {pct_extra}%",
        "descriere": (
            f"Din {total} ședințe de Consiliu Local analizate, {n_extra} ({pct_extra}%) "
            f"sunt 'extraordinare cu convocare de îndată'. Ponderea este un indicator "
            f"statistic pentru verificarea motivării urgenței și a respectării etapelor de "
            f"transparență din Legea 52/2003, art. 7; nu dovedește evitarea consultării."
        ),
        "contract_id": "HCL-META",
        "contract_numar": "–",
        "valoare": 0,
        "furnizor": "Consiliul Local",
        "cif_furnizor": "",
        "data": datetime.now().strftime("%Y-%m-%d"),
        "tip_procedura": "Sedinta CL",
        "pct_extraordinare": pct_extra,
        "total_hcl": total,
    }]


# ──────────────────────────────────────────────────────────────────────────────
# §2.7  Detector publicare contract întârziată
# ──────────────────────────────────────────────────────────────────────────────

def detect_publicare_intarziata(contracte: list, zile_prag: int = 11) -> list:
    """
    §2.7 — Publicare tardivă: data_publicare − data_atribuire > zile_prag zile lucrătoare.
    Legea 98/2016, art. 219: publicare în max 11 zile lucrătoare de la semnarea contractului.
    Contractele fără câmpul data_atribuire sunt sarite (câmp opțional, va fi adăugat
    în schema SEAP când fetch-ul permite extragerea datei de atribuire).
    Necesită pachetul `holidays` (pip install holidays).
    """
    try:
        import holidays as _holidays
        _ro_holidays = _holidays.Romania()
    except ImportError:
        _ro_holidays = set()

    def _zile_lucratoare(d_start, d_end):
        if d_end <= d_start:
            return 0
        zile = 0
        d = d_start
        while d < d_end:
            if d.weekday() < 5 and d not in _ro_holidays:
                zile += 1
            d += timedelta(days=1)
        return zile

    flags = []
    for c in contracte:
        data_attr_str = (c.get("data_atribuire") or "").strip()
        data_pub_str  = (c.get("data_publicare") or c.get("data") or "").strip()
        if not data_attr_str or not data_pub_str:
            continue
        try:
            d_attr = datetime.strptime(data_attr_str[:10], "%Y-%m-%d")
            d_pub  = datetime.strptime(data_pub_str[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if d_pub <= d_attr:
            continue
        zl = _zile_lucratoare(d_attr, d_pub)
        if zl <= zile_prag:
            continue
        v = float(c.get("valoare_ron") or c.get("valoare") or 0)
        if v < 10_000:
            continue
        severitate = "CRITIC" if zl > 30 else "MAJOR" if zl > 20 else "MEDIU"
        flags.append({
            "tip": "PUBLICARE_INTARZIATA",
            "severitate": severitate,
            "titlu": f"Contract publicat cu {zl} zile lucrătoare întârziere",
            "descriere": (
                f'Contractul "{(c.get("titlu") or "")[:60]}" ({_fmt_ron(v)}) '
                f'atribuit la {data_attr_str} a fost publicat în SEAP la {data_pub_str}: '
                f'{zl} zile lucrătoare întârziere (prag legal: {zile_prag} z.l.). '
                f'Legea 98/2016, art. 219 impune publicarea în cel mult 11 zile lucrătoare '
                f'de la data încheierii contractului. Publicarea tardivă diminuează '
                f'transparența și poate fi sancționată conform art. 224 L98/2016.'
            ),
            "contract_id": c.get("id") or "",
            "contract_numar": c.get("numar") or "",
            "valoare": v,
            "furnizor": c.get("castigator") or c.get("firma") or "",
            "cif_furnizor": c.get("castigator_cui") or c.get("cui") or "",
            "data": data_pub_str,
            "data_atribuire": data_attr_str,
            "tip_procedura": c.get("tip_procedura") or c.get("tip") or "",
            "zile_lucratoare_intarziere": zl,
        })
    return sorted(flags, key=lambda f: f["zile_lucratoare_intarziere"], reverse=True)


def detect_valori_identice_aceeasi_zi(contracte: list,
                                       min_firme: int = 2,
                                       min_valoare_ron: float = 100_000) -> list:
    """§2.1-audit — Contracte cu valoare EXACT identică atribuite la firme DIFERITE
    în aceeași zi. Indicator clasic de împărțire artificială a unui lot.

    Acceptă schema internă (valoare_ron / castigator_cui / data_publicare)
    și schema export (valoare / cui / data).
    """
    from collections import defaultdict as _dd2
    from datetime import datetime as _dt2

    def _val(c):
        return c.get("valoare_ron") or c.get("valoare") or 0.0

    def _cui(c):
        return c.get("castigator_cui") or c.get("cui") or ""

    def _data(c):
        raw = c.get("data_publicare") or c.get("data") or ""
        return raw[:10]

    def _firma(c):
        return c.get("castigator") or c.get("firma") or ""

    grupe = _dd2(list)
    for c in contracte:
        val = float(_val(c))
        cui = _cui(c)
        data = _data(c)
        if not data or not cui or val < min_valoare_ron:
            continue
        try:
            _dt2.strptime(data, "%Y-%m-%d")
        except ValueError:
            continue
        grupe[(data, val)].append(c)

    flags = []
    for (data, val), ctrs in grupe.items():
        firme_unice = {_cui(c) for c in ctrs}
        if len(firme_unice) < min_firme:
            continue
        firme_names = sorted({_firma(c) for c in ctrs})
        flags.append({
            "tip": "VALORI_IDENTICE_ACEEASI_ZI",
            "severitate": "CRITIC",
            "titlu": f"{len(ctrs)} contracte de valoare identică ({val:,.0f} RON) în aceeași zi",
            "descriere": (
                f"În data de {data}, {len(firme_unice)} firme diferite au primit contracte cu "
                f"valoare EXACT identică ({val:,.0f} RON fiecare). "
                f"Total: {val * len(ctrs):,.0f} RON. "
                f"Firme: {', '.join(firme_names[:5])}{'...' if len(firme_names) > 5 else ''}. "
                f"Pattern clasic de împărțire artificială a unui lot (art. 11 alin. (1) L98/2016)."
            ),
            "data": data,
            "valoare": val * len(ctrs),
            "valoare_per_contract": val,
            "nr_firme": len(firme_unice),
            "nr_contracte": len(ctrs),
            "firme": firme_names,
            "legi": ["L98/2016 art.11 (interzicerea fragmentării artificiale)"],
        })
    return sorted(flags, key=lambda f: f["valoare"], reverse=True)


def detect_burst_contracte(contracte: list,
                            prag_nr: int = 5,
                            min_valoare_ron: float = 50_000) -> list:
    """§2.2-audit — Detectează zile cu volum anormal de contracte (burst).

    Semnalează:
    - zile cu ≥ prag_nr contracte și valoare totală ≥ min_valoare_ron
    - weekend-uri cu contracte semnificative (valoare totală > 200.000 RON)

    Acceptă schema internă și schema export.
    """
    from collections import defaultdict as _dd3
    from datetime import datetime as _dt3

    def _val(c):
        return float(c.get("valoare_ron") or c.get("valoare") or 0)

    def _data(c):
        return (c.get("data_publicare") or c.get("data") or "")[:10]

    def _lista(ctrs):
        """Lista contractelor componente, pentru afișare expandabilă în raport."""
        out = []
        for c in ctrs:
            out.append({
                "firma": c.get("castigator") or c.get("furnizor") or c.get("ofertant") or "Necunoscut",
                "cui_firma": c.get("castigator_cui") or c.get("cui_ofertant") or c.get("cui") or "",
                "valoare": _val(c),
                "id": c.get("id") or "",
                "nr_seap": c.get("numar") or c.get("numar_contract") or c.get("id") or "",
                "procedura": c.get("tip_procedura") or c.get("procedura") or "",
                "titlu": c.get("titlu") or c.get("denumire") or "",
            })
        return out

    pe_zi = _dd3(list)
    for c in contracte:
        data = _data(c)
        if data and float(_val(c)) > 0:
            try:
                _dt3.strptime(data, "%Y-%m-%d")
                pe_zi[data].append(c)
            except ValueError:
                pass

    flags = []
    for data, ctrs in pe_zi.items():
        valoare_zi = sum(_val(c) for c in ctrs)
        try:
            zi_sapt = _dt3.strptime(data, "%Y-%m-%d").weekday()
        except ValueError:
            continue
        este_weekend = zi_sapt >= 5  # 5=Sâmbătă, 6=Duminică

        # Burst volum mare (≥ prag_nr contracte)
        if len(ctrs) >= prag_nr and valoare_zi >= min_valoare_ron:
            flags.append({
                "tip": "BURST_CONTRACTE",
                "severitate": "MAJOR" if len(ctrs) >= 10 else "MEDIU",
                "titlu": f"{len(ctrs)} contracte semnate într-o singură zi ({data})",
                "descriere": (
                    f"În {data} s-au semnat {len(ctrs)} contracte cu valoare totală "
                    f"{valoare_zi:,.0f} RON."
                    + (" Atribuire în weekend — zi nelucrătoare." if este_weekend else "")
                ),
                "data": data,
                "valoare": valoare_zi,
                "nr_contracte": len(ctrs),
                "weekend": este_weekend,
                "contracte": _lista(ctrs),
            })
        # Weekend cu valoare mare (chiar sub prag_nr)
        elif este_weekend and valoare_zi >= 200_000:
            flags.append({
                "tip": "BURST_CONTRACTE",
                "severitate": "MEDIU",
                "titlu": f"Contracte semnificative semnate în weekend ({data})",
                "descriere": (
                    f"În {data} (weekend) s-au semnat {len(ctrs)} contracte "
                    f"cu valoare totală {valoare_zi:,.0f} RON. "
                    f"Semnarea în zile nelucrătoare ridică întrebări despre urgența declarată."
                ),
                "data": data,
                "valoare": valoare_zi,
                "nr_contracte": len(ctrs),
                "weekend": True,
                "contracte": _lista(ctrs),
            })
    return sorted(flags, key=lambda f: f["valoare"], reverse=True)


def detect_semnare_zile_nelucratoare(contracte: list,
                                      min_valoare_ron: float = 50_000) -> list:
    """§2.7-audit — Contracte semnate în weekend sau sărbătoare legală românească.

    Acceptă schema internă (valoare_ron / data_publicare) și export (valoare / data).
    Folosește `holidays` cu fallback la set gol dacă pachetul nu e instalat.
    """
    from datetime import datetime as _dt4

    try:
        import holidays as _hol
        _ro_holidays = _hol.Romania()
    except ImportError:
        _ro_holidays = set()

    def _val(c):
        return float(c.get("valoare_ron") or c.get("valoare") or 0)

    def _data(c):
        return (c.get("data_publicare") or c.get("data") or "")[:10]

    def _firma(c):
        return c.get("castigator") or c.get("firma") or ""

    flags = []
    for c in contracte:
        val = _val(c)
        if val < min_valoare_ron:
            continue
        data_str = _data(c)
        if not data_str:
            continue
        try:
            d = _dt4.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        este_weekend = d.weekday() >= 5
        este_sarbatoare = d in _ro_holidays
        if not (este_weekend or este_sarbatoare):
            continue

        tip_zi = "weekend" if este_weekend else "sărbătoare legală"
        tip_sarbatoare = _ro_holidays.get(d, "") if este_sarbatoare else ""
        descriere_zi = f" ({tip_sarbatoare})" if tip_sarbatoare else ""

        flags.append({
            "tip": "SEMNARE_ZI_NELUCRATOARE",
            "severitate": "MEDIU",
            "titlu": f"Contract semnat în {tip_zi} — {data_str}",
            "descriere": (
                f"Contractul de {val:,.0f} RON"
                + (f' (firmă: {_firma(c)})' if _firma(c) else '')
                + f" a fost semnat în {tip_zi}{descriere_zi}. "
                f"Semnarea în zile nelucrătoare poate indica urgență nejustificată "
                f"sau proceduri grăbite pentru a evita controlul. "
                f"Verificați dacă a existat o situație de urgență documentată."
            ),
            "data": data_str,
            "valoare": val,
            "furnizor": _firma(c),
            "tip_zi": tip_zi,
            "weekend": este_weekend,
            "sarbatoare": este_sarbatoare,
        })
    return sorted(flags, key=lambda f: f["valoare"], reverse=True)


# Județe adiacente Ilfov (considerate acceptabile pentru servicii locale)
_JUDETE_ADIACENTE_ILFOV = frozenset({'IF', 'B', 'GR', 'CL', 'IL', 'PH', 'DB'})
# Cuvinte-cheie care indică servicii cu caracter local (în mod normal contractate din zonă)
_KEYWORDS_LOCAL = [
    'curatenie', 'paza', 'mentenanta', 'salubrizare', 'deszapezire',
    'iluminat', 'spatii verzi', 'spatii publice', 'cosit', 'deratizare',
    'dezinfectie', 'dezinsectie', 'gunoi', 'ghenare', 'salubritate',
]


def detect_crestere_brusca_valoare(contracte: list) -> list:
    """Algoritm 7 — valoarea unui contract a crescut mult între revizii.

    Compararea se face CRONOLOGIC. Varianta anterioară sorta versiunile după
    `valoare_ron` și raporta întotdeauna min→max ca pe o creștere, inclusiv când
    valoarea SCĂZUSE în timp: pe „DAV  GARDEN & SERVICE" afirma public „+300%,
    de la 1.15 mil. la 4.62 mil.", când în realitate contractul mersese invers —
    4.62 mil. (11.12.2025) → 1.15 mil. (27.02.2026). O afirmație publică
    inversată e exact genul de eroare care discreditează întreg raportul.

    Funcție pură, fără apeluri externe.
    """
    from collections import defaultdict as _dd

    grupuri = _dd(list)
    for contract in contracte or []:
        # gruparea include furnizorul: două firme diferite cu obiect identic
        # („Amenajare spații verzi") nu sunt versiuni ale aceluiași contract
        cheie = (normalizeaza_nume_firma(contract.get("castigator", "")),
                 _titlu_fara_revizie(contract.get("titlu", "")))
        grupuri[cheie].append(contract)

    flags = []
    for (_furnizor_nz, titlu_base), versiuni in grupuri.items():
        # Exporturile trimestriale republică același contract cu id-uri diferite.
        # Fără dedup, o „versiune" se compara cu propria ei copie.
        vazute, unice = set(), []
        for contract in versiuni:
            amprenta = (contract.get("data_publicare", ""),
                        round(contract.get("valoare_ron", 0) or 0, 2))
            if amprenta in vazute:
                continue
            vazute.add(amprenta)
            unice.append(contract)
        if len(unice) < 2:
            continue

        # ordine cronologică; la dată egală, valoarea mai mică e considerată prima
        cronologic = sorted(unice, key=lambda c: (c.get("data_publicare", ""),
                                                  c.get("valoare_ron", 0) or 0))
        prima, ultima = cronologic[0], cronologic[-1]
        v_initial = prima.get("valoare_ron", 0) or 0
        v_final = ultima.get("valoare_ron", 0) or 0

        # semnalăm doar creșteri reale în timp; o scădere nu e „creștere bruscă"
        if not (v_initial > 0 and v_final > v_initial * 1.5 and v_final > 50_000):
            continue

        crestere_pct = (v_final / v_initial - 1) * 100
        data_initiala = prima.get("data_publicare", "?")
        data_finala = ultima.get("data_publicare", "?")

        # Când ambele versiuni au aceeași dată de publicare nu putem stabili care
        # a fost prima, deci nu avem dreptul să afirmăm că valoarea „a crescut".
        # Diferența rămâne un semnal legitim, dar formulat fără direcție.
        if data_initiala == data_finala:
            titlu_flag = "Valori diferite pentru același contract, la aceeași dată"
            descriere = (f'Contractul „{titlu_base[:55]}" apare la aceeași dată ({data_finala}) '
                         f'cu două valori diferite: {_fmt_ron(v_initial)} și {_fmt_ron(v_final)} '
                         f'(diferență de {crestere_pct:.0f}%). Ordinea versiunilor nu poate fi '
                         f'stabilită din datele publicate. Merită verificat dacă este vorba de un '
                         f'act adițional, de loturi distincte sau de o eroare de raportare.')
        else:
            titlu_flag = "Creștere bruscă de valoare în revizie contract"
            descriere = (f'Contractul „{titlu_base[:55]}" a crescut cu {crestere_pct:.0f}% între versiuni: '
                         f'de la {_fmt_ron(v_initial)} ({data_initiala}) '
                         f'la {_fmt_ron(v_final)} ({data_finala}). '
                         f'Diferența este un semnal pentru verificarea actelor adiționale și a '
                         f'condițiilor de modificare prevăzute de Legea 98/2016; nu dovedește o abatere.')

        flags.append({
            "tip": "CRESTERE_BRUSCA_VALOARE",
            "severitate": "MAJOR" if crestere_pct < 200 else "CRITIC",
            "titlu": titlu_flag,
            "descriere": descriere,
            "contract_id": ultima.get("id", ""),
            "contract_numar": ultima.get("numar", ""),
            "valoare": v_final,
            "furnizor": ultima.get("castigator", ""),
            "data": ultima.get("data_publicare", ""),
            "tip_procedura": ultima.get("tip_procedura", ""),
        })
    return flags


def detect_geographic_anomaly(contracte: list, firme_openapi: dict) -> list:
    """
    §2.5 AUDIT.md — Servicii locale atribuite firmelor cu sediu departe de Ilfov.

    Necesită date din openapi.ro (CONFIG['openapi_ro_key']): câmpul 'judet' în firme_openapi.
    Dacă openapi.ro nu e configurat sau nu returnează 'judet', funcția returnează [].

    Acceptă schema internă (castigator_cui / valoare_ron) și export (cui / valoare).
    """
    flags = []
    for c in contracte:
        obiect = (c.get('titlu') or c.get('obiect') or '').lower()
        if not any(k in obiect for k in _KEYWORDS_LOCAL):
            continue

        cui = (c.get('castigator_cui') or c.get('cui') or '').strip().lstrip('RO')
        if not cui:
            continue
        info = firme_openapi.get(cui) or firme_openapi.get('RO' + cui)
        if not info:
            continue

        judet = (info.get('judet') or '').upper().strip()
        if not judet or judet in _JUDETE_ADIACENTE_ILFOV:
            continue  # fără date sau în zonă acceptabilă → nu e anomalie

        furnizor = (c.get('castigator') or c.get('furnizor') or '')
        valoare  = float(c.get('valoare_ron') or c.get('valoare') or 0)

        flags.append({
            'tip': 'GEOGRAFIE_ANORMALA',
            'severitate': 'MEDIU',
            'titlu': f'Servicii locale de la firmă din {judet}',
            'descriere': (
                f'Servicii de tip "{obiect[:60]}" atribuite firmei {furnizor[:55]} '
                f'cu sediu în {judet}. Serviciile locale se contractează de obicei '
                f'cu firme din Ilfov sau județele limitrofe.'
            ),
            'furnizor': furnizor,
            'cif_furnizor': cui,
            'valoare': valoare,
            'data': c.get('data_publicare') or c.get('data') or '',
            'contract_id': c.get('contract_id') or c.get('contract_numar') or '',
            'tip_procedura': c.get('tip_procedura') or '',
        })

    return sorted(flags, key=lambda f: f['valoare'], reverse=True)


def analizeaza_red_flags(contracte: list, config: dict) -> list:
    """
    Rulează detectorii automați pe lista de contracte.
    Returnează semnale de risc care necesită verificare, nu constatări juridice.
    """
    print("  [Analiză] Rulând algoritmi de detecție red flags...")
    flags = []

    prag_s = config["prag_servicii_furnizare"]
    prag_l = config["prag_lucrari"]
    marja = config["marja_fragmentare_pct"]

    # ── Algoritm 1: Contracte cu un singur ofertant ──────────────────────────
    for c in contracte:
        if c.get("nr_ofertanti", 0) == 1 and c["valoare_ron"] > 20_000:
            severitate = "MAJOR" if c["valoare_ron"] > 200_000 else "MEDIU"
            flags.append({
                "tip": "OFERTANT_UNIC",
                "severitate": severitate,
                "titlu": "Un singur ofertant raportat în date",
                "descriere": f'{c["castigator"]} a primit {_fmt_ron(c["valoare_ron"])} pentru '
                             f'„{c["titlu"][:55]}”, iar setul de date indică un singur ofertant. '
                             f'Indicatorul nu dovedește lipsa concurenței sau un preț incorect; '
                             f'documentația procedurii trebuie verificată.',
                "contract_id": c["id"],
                "contract_numar": c["numar"],
                "valoare": c["valoare_ron"],
                "furnizor": c["castigator"],
                "data": c["data_publicare"],
                "tip_procedura": c["tip_procedura"],
            })

    # ── Algoritm 1b: Achiziție directă individuală PESTE prag ───────────────
    for c in contracte:
        v = c["valoare_ron"]
        prag, categorie = _prag_pentru_contract(c, config)
        # Încadrarea categoriei este automată; semnalul trebuie verificat în documentația SEAP.
        if v > prag and ("direct" in c["tip_procedura"].lower() or c["tip_procedura"] == ""):
            nr_of = c.get("nr_ofertanti", 0)
            if nr_of >= 2:
                nota_ofertanti = (
                    f' Setul de date indică {nr_of} ofertanți; tipul exact al procedurii '
                    f'și documentele publicate în SEAP trebuie verificate.'
                )
            else:
                nota_ofertanti = ""
            flags.append({
                "tip": "ACHIZITIE_DIRECTA_PESTE_PRAG",
                "severitate": "CRITIC",
                "titlu": "Semnal: achiziție directă peste pragul aplicabil",
                "descriere": (f'{c["castigator"]} a primit {_fmt_ron(v)} pentru '
                              f'„{c["titlu"][:55]}”. Clasificarea automată: {categorie}; '
                              f'valoarea este cu {_fmt_ron(v - prag)} peste pragul de achiziție '
                              f'directă de {_fmt_ron(prag)} fără TVA. Încadrarea CPV, valoarea '
                              f'estimată și procedura efectivă trebuie verificate în SEAP.'
                              + nota_ofertanti),
                "contract_id": c["id"],
                "contract_numar": c["numar"],
                "valoare": v,
                "furnizor": c["castigator"],
                "data": c["data_publicare"],
                "tip_procedura": c["tip_procedura"],
                "categorie_contract": categorie,
                "prag_aplicat": prag,
            })

    # ── Algoritm 2: Valoare aproape de prag (fragmentare suspectă) ───────────
    for c in contracte:
        v = c["valoare_ron"]
        prag, tip_prag = _prag_pentru_contract(c, config)
        if v > 0:
            if prag * marja < v <= prag:
                flags.append({
                    "tip": "APROAPE_DE_PRAG",
                    "severitate": "MAJOR",
                    "titlu": "Semnal: valoare aproape de prag",
                    "descriere": (f'{c["castigator"]} a primit {_fmt_ron(v)} pentru {tip_prag} — '
                                 f'cu {_fmt_ron(prag - v)} sub pragul de achiziție directă '
                                 f'({_fmt_ron(prag)}, fără TVA). Apropierea de prag este doar un '
                                 f'indicator statistic; nu dovedește divizarea sau estimarea incorectă.'),
                    "contract_id": c["id"],
                    "contract_numar": c["numar"],
                    "valoare": v,
                    "furnizor": c["castigator"],
                    "data": c["data_publicare"],
                    "tip_procedura": c["tip_procedura"],
                    "categorie_contract": tip_prag,
                    "prag_aplicat": prag,
                })

    # ── Algoritm 3: Fragmentare (același furnizor, titluri similare, interval scurt) ─
    from collections import defaultdict
    pe_furnizor = defaultdict(list)
    for c in contracte:
        if c["castigator_cui"]:
            pe_furnizor[c["castigator_cui"]].append(c)

    for cui_f, lista in pe_furnizor.items():
        if len(lista) < 2:
            continue
        # Sortăm după dată
        lista_sorted = sorted(lista, key=lambda x: x["data_publicare"])
        for i in range(len(lista_sorted) - 1):
            a, b = lista_sorted[i], lista_sorted[i + 1]
            # Verificăm interval scurt (< 60 zile) și titluri similare
            try:
                da = datetime.strptime(a["data_publicare"], "%Y-%m-%d")
                db = datetime.strptime(b["data_publicare"], "%Y-%m-%d")
                zile_diferenta = abs((db - da).days)
            except ValueError:
                zile_diferenta = 999

            titlu_similar = (
                _similaritate_titlu(a["titlu"], b["titlu"]) > 0.4
                or "lot" in a["titlu"].lower() and "lot" in b["titlu"].lower()
            )
            valoare_combinata = a["valoare_ron"] + b["valoare_ron"]
            prag_a, categorie_a = _prag_pentru_contract(a, config)
            prag_b, categorie_b = _prag_pentru_contract(b, config)

            aceeasi_categorie = categorie_a == categorie_b and prag_a == prag_b
            ambele_sub_prag = a["valoare_ron"] < prag_a and b["valoare_ron"] < prag_a
            if (zile_diferenta < 60 and titlu_similar and aceeasi_categorie
                    and ambele_sub_prag and valoare_combinata > prag_a):
                flags.append({
                    "tip": "FRAGMENTARE",
                    "severitate": "CRITIC",
                    "titlu": "Semnal de posibilă fragmentare a contractelor",
                    "descriere": (f'{a["castigator"]} a primit 2 contracte similare în {zile_diferenta} zile, '
                                  f'cu o valoare combinată de {_fmt_ron(valoare_combinata)}. '
                                 f'Fiecare este sub pragul pentru {categorie_a} ({_fmt_ron(prag_a)}), '
                                 f'iar suma îl depășește. Similaritatea temporală și textuală este '
                                 f'un semnal automat; unitatea achizitoare și documentele trebuie verificate.'),
                    "contract_id": f"{a['id']},{b['id']}",
                    "contract_numar": f"{a['numar']} + {b['numar']}",
                    "valoare": valoare_combinata,
                    "furnizor": a["castigator"],
                    "data": a["data_publicare"],
                    "tip_procedura": a["tip_procedura"],
                    "categorie_contract": categorie_a,
                    "prag_aplicat": prag_a,
                })

    # ── Algoritm 4: Utilizare excesivă proceduri non-competitive ─────────────
    total = len(contracte)
    if total > 0:
        directe = [c for c in contracte if "direct" in c["tip_procedura"].lower()
                   or "negociere" in c["tip_procedura"].lower()]
        pct_directe = len(directe) / total * 100
        if pct_directe > 40:
            flags.append({
                "tip": "PROCEDURI_NON_COMPETITIVE",
                "severitate": "MAJOR",
                "titlu": "Exces de proceduri non-competitive",
                "descriere": (f'{len(directe)} din {total} contracte ({pct_directe:.0f}%) '
                             f'au fost atribuite fără licitație publică — media națională e sub 30%. '
                             f'Când primăria evită constant licitațiile, cetățenii nu pot verifica '
                             f'dacă banii publici au mers spre cele mai bune oferte disponibile.'),
                "contract_id": "global",
                "contract_numar": "–",
                "valoare": sum(c["valoare_ron"] for c in directe),
                "furnizor": "Multiple",
                "data": datetime.now().strftime("%Y-%m-%d"),
                "tip_procedura": "Multiple",
            })

    # ── Algoritm 5: Concentrare ridicată la furnizori ────────────────────────
    valori_pe_furnizor = defaultdict(float)
    for c in contracte:
        valori_pe_furnizor[c["castigator"]] += c["valoare_ron"]

    total_valoare = sum(c["valoare_ron"] for c in contracte)
    if total_valoare > 0:
        for furnizor, valoare in valori_pe_furnizor.items():
            pct = valoare / total_valoare * 100
            if pct > 35 and valoare > 500_000:
                flags.append({
                    "tip": "FURNIZOR_DOMINANT",
                    "severitate": "MEDIU",
                    "titlu": "Furnizor dominant în achizițiile publice",
                    "descriere": (f'{furnizor} a câștigat {pct:.0f}% din toate contractele '
                                 f'Primăriei Pantelimon: {_fmt_ron(valoare)} din {_fmt_ron(total_valoare)} total. '
                                 f'Un singur furnizor care domină achizițiile ridică semne de favoritism. '
                                 f'Merită investigat dacă există legături între această firmă și conducerea primăriei.'),
                    "contract_id": "global",
                    "contract_numar": "–",
                    "valoare": valoare,
                    "furnizor": furnizor,
                    "data": datetime.now().strftime("%Y-%m-%d"),
                    "tip_procedura": "Multiple",
                })


    # ── Algoritm 6: Contracte consecutive cu același furnizor (>3 în <30 zile) ──
    # Diferit de Algoritm 3 (fragmentare): aceasta detectează VOLUMUL, nu titlurile similare
    for cui_f, lista in pe_furnizor.items():
        if len(lista) < 4:
            continue
        lista_sorted = sorted(lista, key=lambda x: x["data_publicare"])
        # Căutăm ferestre de 30 zile cu >3 contracte
        for i in range(len(lista_sorted)):
            try:
                d_start = datetime.strptime(lista_sorted[i]["data_publicare"], "%Y-%m-%d")
            except ValueError:
                continue
            fereastra = [lista_sorted[i]]
            for j in range(i + 1, len(lista_sorted)):
                try:
                    dj = datetime.strptime(lista_sorted[j]["data_publicare"], "%Y-%m-%d")
                except ValueError:
                    continue
                if (dj - d_start).days <= 30:
                    fereastra.append(lista_sorted[j])
                else:
                    break
            if len(fereastra) >= 4:
                valoare_totala = sum(c["valoare_ron"] for c in fereastra)
                flags.append({
                    "tip": "CONTRACTE_CONSECUTIVE",
                    "severitate": "MAJOR",
                    "titlu": "Contracte consecutive excesive cu același furnizor",
                    "descriere": (f'{fereastra[0]["castigator"]} a primit {len(fereastra)} contracte '
                                 f'în numai 30 de zile ({fereastra[0]["data_publicare"]} — {fereastra[-1]["data_publicare"]}), '
                                 f'cu o valoare totală de {_fmt_ron(valoare_totala)}. '
                                 f'Un ritm atât de concentrat e neobișnuit și poate indica o relație privilegiată '
                                 f'cu această firmă sau împărțirea unui contract mare în bucăți mici.'),
                    "contract_id": ",".join(c["id"] for c in fereastra[:3]),
                    "contract_numar": f'{fereastra[0]["numar"]} + {len(fereastra)-1} altele',
                    "valoare": valoare_totala,
                    "furnizor": fereastra[0]["castigator"],
                    "data": fereastra[0]["data_publicare"],
                    "tip_procedura": fereastra[0]["tip_procedura"],
                })
                break  # O singură alertă per furnizor

    # ── Algoritm 7: Creștere bruscă de valoare Rev.2 / Rev.3 (>50%) ─────────────
    # Contractele revizuite (Rev.2, Rev.3) cu valoare mult mai mare decât originalul
    # sunt un indicator de supraestimare deliberată sau modificare abuzivă a contractului
    flags.extend(detect_crestere_brusca_valoare(contracte))

    # ── Algoritm 8: Valori rotunde — indicator statistic ────────────────────────
    # Contracte cu valori perfect rotunde (multiplu exact de 10.000) > 50K
    # indică posibilă alocare forfetară fără studiu de piață real
    for c in contracte:
        v = c["valoare_ron"]
        if v >= 50_000 and v % 10_000 == 0:
            # Excludem pragurile legale și alte valori-standard uzuale.
            praguri_standard = {prag_s, prag_l, 300_000, 500_000, 1_000_000, 2_000_000}
            if v not in praguri_standard:
                flags.append({
                    "tip": "VALOARE_ROTUNDA_SUSPECTA",
                    "severitate": "MEDIU",
                    "titlu": "Semnal statistic: valoare contractuală rotundă",
                    "descriere": (f'{c["castigator"]} a primit exact {_fmt_ron(v)} pentru '
                                 f'„{c["titlu"][:55]}”. Valoarea rotundă este un indicator euristic '
                                 f'pentru verificarea documentației de estimare; singură nu indică o abatere.'),
                    "contract_id": c["id"],
                    "contract_numar": c["numar"],
                    "valoare": v,
                    "furnizor": c["castigator"],
                    "data": c["data_publicare"],
                    "tip_procedura": c["tip_procedura"],
                })

    # ── Algoritm 9: Firme suspecte (ANAF + openapi.ro) ──────────────────────────
    # Detectează: firme inactive/radiate, firme nou înregistrate (<2 ani).
    # Îmbogățit cu date de acționariat/administrator din openapi.ro (dacă cheie configurată).
    cui_furnizori = list({c["castigator_cui"] for c in contracte if c.get("castigator_cui")})
    firme_openapi = {}   # inițializat cu {} — suprascris mai jos dacă cui_furnizori e populat
    firme_anaf = {}
    firme_onrc = {}
    if cui_furnizori and not config.get("_offline_mode"):
        fisier_cache = config.get("fisier_cache_firme", "cache_firme.json")
        # Date ANAF (status, dată înregistrare)
        firme_anaf = _get_firme_anaf_batch(cui_furnizori, fisier_cache)
        # Date openapi.ro (acționari, administrator, angajați) — opțional
        firme_openapi = _get_actionariat_openapi(
            cui_furnizori, config.get("openapi_ro_key", ""), fisier_cache
        )
        # Date ONRC (reprezentanți legali din OD_REPREZENTANTI_LEGALI.CSV) — gratis, oficial
        firme_onrc = _get_reprezentanti_onrc(cui_furnizori, fisier_cache)
        config["_firme_onrc"] = firme_onrc         # transmis la genereaza_raport_html
        config["_firme_openapi"] = firme_openapi   # transmis la genereaza_raport_html
        azi        = datetime.now()
        for c in contracte:
            cui_f = c.get("castigator_cui", "")
            if not cui_f:
                continue
            info = firme_anaf.get(cui_f)
            if not info:
                continue

            stare          = info.get("stare", "NECUNOSCUT")
            data_inf_str   = info.get("dataInregistrare") or ""
            furnizor       = c["castigator"]
            valoare        = c["valoare_ron"]
            termene_link   = _termene_url(cui_f)
            cui_display    = cui_f.lstrip("RO").lstrip("ro")

            # 9a: Firmă inactivă / radiată cu contract activ → CRITIC
            if stare in ("INACTIV", "RADIAT", "SUSPENDAT"):
                flags.append({
                    "tip": "FIRMA_INACTIVA",
                    "severitate": "CRITIC",
                    "titlu": f"Contract cu firmă {stare.lower()} la ANAF",
                    "descriere": (
                        f'<strong>{furnizor}</strong> (CUI {cui_display}) are statut '
                        f'<strong>{stare}</strong> în răspunsul ANAF consultat. Contractul '
                        f'„{c["titlu"][:50]}” a valorat {_fmt_ron(valoare)}. Statutul trebuie '
                        f'verificat la data atribuirii și a plății înaintea oricărei concluzii. '
                        + (f'<br><small style="color:#555">{_fmt_actionariat(firme_openapi.get(cui_f))}</small><br>' if firme_openapi.get(cui_f) else '')
                        + f'Verifică administrator și istoricul complet: '
                        f'<a href="{termene_link}" target="_blank" rel="noopener noreferrer">termene.ro →</a>'
                    ),
                    "contract_id": c["id"],
                    "contract_numar": c["numar"],
                    "valoare": valoare,
                    "furnizor": furnizor,
                    "cif_furnizor": cui_f,
                    "data": c["data_publicare"],
                    "tip_procedura": c["tip_procedura"],
                })

            # 9b: Firmă nou înregistrată (<24 luni la data contractului) și valoare >50K → MAJOR
            elif data_inf_str:
                try:
                    data_inf = datetime.strptime(data_inf_str[:10], "%Y-%m-%d")
                    try:
                        data_contract = datetime.strptime(c["data_publicare"][:10], "%Y-%m-%d")
                    except Exception:
                        data_contract = azi
                    varsta_luni = (data_contract.year - data_inf.year) * 12 +                                   (data_contract.month - data_inf.month)
                    if varsta_luni < 24 and valoare >= 50_000:
                        sev = "CRITIC" if valoare >= config["prag_servicii_furnizare"] else "MAJOR"
                        flags.append({
                            "tip": "FIRMA_NOU_CREATA",
                            "severitate": sev,
                            "titlu": f"Contract cu firmă de {varsta_luni} luni vechime",
                            "descriere": (
                                f'<strong>{furnizor}</strong> (CUI {cui_display}) a fost înregistrată pe '
                                f'{data_inf_str[:10]} — cu doar <strong>{varsta_luni} luni</strong> '
                                f'înainte de a primi un contract de {_fmt_ron(valoare)} pentru '
                                f'„{c["titlu"][:50]}". '
                                f'Vechimea redusă este un indicator pentru verificarea criteriilor '
                                f'de experiență și a capacității tehnice; nu dovedește o problemă. '
                                f'<a href="{termene_link}" target="_blank" rel="noopener noreferrer">Verifică pe termene.ro →</a>'
                            ),
                            "contract_id": c["id"],
                            "contract_numar": c["numar"],
                            "valoare": valoare,
                            "furnizor": furnizor,
                            "cif_furnizor": cui_f,
                            "data": c["data_publicare"],
                            "tip_procedura": c["tip_procedura"],
                            "varsta_luni": varsta_luni,
                        })
                except Exception:
                    pass

    # ── Algoritm 9c: Firmă radiată la ORC (confirmare openapi.ro) ───────────────
    # openapi.ro returnează câmpul `radiata: bool` care e mai fiabil decât
    # parsing-ul textului din ANAF. Adaugă flag suplimentar dacă nu e deja detectat.
    if cui_furnizori and firme_openapi:
        firme_deja_flagate = {f.get("cif_furnizor", "") for f in flags if f.get("tip") == "FIRMA_INACTIVA"}
        for c in contracte:
            cui_f = c.get("castigator_cui", "")
            if not cui_f or cui_f in firme_deja_flagate:
                continue
            info = firme_openapi.get(cui_f)
            if not info or not info.get("radiata"):
                continue
            furnizor    = c["castigator"]
            valoare     = c["valoare_ron"]
            cui_display = cui_f.lstrip("RO").lstrip("ro")
            flags.append({
                "tip": "FIRMA_INACTIVA",
                "severitate": "CRITIC",
                "titlu": "Contract cu firmă radiată la Registrul Comerțului",
                "descriere": (
                    f'Firma "{furnizor}" (CUI {cui_display}) este marcată ca <strong>RADIATĂ</strong> '
                    f'conform openapi.ro (sursă: ONRC). A primit contractul '
                    f'"{c["titlu"][:60]}" în valoare de {_fmt_ron(valoare)}. '
                    f'Data radierii și starea firmei la momentul atribuirii trebuie confirmate '
                    f'din sursa oficială; această potrivire automată nu stabilește validitatea contractului. '
                    + (_fmt_actionariat(info) + " " if _fmt_actionariat(info) else "")
                ),
                "contract_id": c["id"],
                "contract_numar": c["numar"],
                "valoare": valoare,
                "furnizor": furnizor,
                "cif_furnizor": cui_f,
                "data": c["data_publicare"],
                "tip_procedura": c["tip_procedura"],
            })

    # ── Algoritm 10: Declarație fiscală veche (>2 ani) cu contract activ ───────
    # Firma nu a mai depus declarație la ANAF de peste 2 ani dar e activă în SEAP
    if cui_furnizori and firme_openapi:
        azi = datetime.now()
        for c in contracte:
            cui_f = c.get("castigator_cui", "")
            if not cui_f:
                continue
            info = firme_openapi.get(cui_f)
            if not info:
                continue
            ultima = info.get("ultima_declaratie", "")
            if not ultima:
                continue
            try:
                data_ultima = datetime.strptime(ultima[:10], "%Y-%m-%d")
                ani_vechime = (azi - data_ultima).days / 365
                if ani_vechime >= 2 and c["valoare_ron"] >= 30_000:
                    furnizor    = c["castigator"]
                    valoare     = c["valoare_ron"]
                    cui_display = cui_f.lstrip("RO").lstrip("ro")
                    recom_link  = info.get("recom_url", _termene_url(cui_f))
                    flags.append({
                        "tip": "DECLARATIE_FISCALA_VECHE",
                        "severitate": "MAJOR",
                        "titlu": f"Firmă fără declarații fiscale de {ani_vechime:.0f} ani",
                        "descriere": (
                            f'Firma "{furnizor}" (CUI {cui_display}) nu a mai depus o declarație '
                            f'fiscală la ANAF din <strong>{ultima[:10]}</strong> '
                            f'({ani_vechime:.0f} ani în urmă), dar a primit contractul '
                            f'"{c["titlu"][:60]}" în valoare de {_fmt_ron(valoare)}. '
                            f'Vechimea informației fiscale justifică verificarea situației curente '
                            f'și a documentelor de calificare; nu dovedește neexecutarea sau existența '
                            f'unor obligații fiscale restante. '
                            + (_fmt_actionariat(info) + " " if _fmt_actionariat(info) else "")
                            + f'<a href="{recom_link}" target="_blank" rel="noopener noreferrer">Verifică la ONRC →</a>'
                        ),
                        "contract_id": c["id"],
                        "contract_numar": c["numar"],
                        "valoare": valoare,
                        "furnizor": furnizor,
                        "cif_furnizor": cui_f,
                        "data": c["data_publicare"],
                        "tip_procedura": c["tip_procedura"],
                    })
            except Exception:
                pass

    # ── Algoritm 11: Contract câștigat în prima lună de la înregistrarea firmei ─
    # Mai agresiv decât Alg 9b (<24 luni): detectează cazurile extreme (<30 zile)
    if cui_furnizori:
        for c in contracte:
            cui_f = c.get("castigator_cui", "")
            if not cui_f:
                continue
            anaf_info = firme_anaf.get(cui_f, {}) if cui_furnizori else {}
            data_inf_str = anaf_info.get("dataInregistrare") or ""
            if not data_inf_str:
                continue
            try:
                data_inf     = datetime.strptime(data_inf_str[:10], "%Y-%m-%d")
                data_contract = datetime.strptime(c["data_publicare"][:10], "%Y-%m-%d")
                zile_varsta   = (data_contract - data_inf).days
                if 0 <= zile_varsta <= 30 and c["valoare_ron"] >= 20_000:
                    furnizor    = c["castigator"]
                    valoare     = c["valoare_ron"]
                    cui_display = cui_f.lstrip("RO").lstrip("ro")
                    flags.append({
                        "tip": "CONTRACT_IN_PRIMA_LUNA",
                        "severitate": "CRITIC",
                        "titlu": f"Contract la {zile_varsta} zile de la înregistrarea firmei",
                        "descriere": (
                            f'Firma "{furnizor}" (CUI {cui_display}) a fost înregistrată pe '
                            f'<strong>{data_inf_str[:10]}</strong> și a primit contractul '
                            f'"{c["titlu"][:60]}" ({_fmt_ron(valoare)}) '
                            f'la doar <strong>{zile_varsta} zile</strong> după înregistrare. '
                            f'Vechimea redusă este un semnal care necesită verificarea capacității '
                            f'tehnice și a documentației; nu dovedește scopul înființării firmei. '
                            f'Legea 98/2016, art. 163-171 și art. 179-187. '
                            f'<a href="{_termene_url(cui_f)}" target="_blank" rel="noopener noreferrer">termene.ro →</a> '
                            f'<a href="https://www.recom.ro/companies_ro_company_detail.aspx?id={cui_display}" target="_blank" rel="noopener noreferrer">ONRC →</a>'
                        ),
                        "contract_id": c["id"],
                        "contract_numar": c["numar"],
                        "valoare": valoare,
                        "furnizor": furnizor,
                        "cif_furnizor": cui_f,
                        "data": c["data_publicare"],
                        "tip_procedura": c["tip_procedura"],
                        "zile_varsta": zile_varsta,
                    })
            except Exception:
                pass

    # ── Algoritm 12: Scor risc acumulat (firmă flagată de ≥3 algoritmi diferiți) ─
    # Cumulul de indicatori prioritizează verificarea, fără a stabili vinovăția.
    from collections import Counter, defaultdict
    flags_per_firma: dict = defaultdict(set)
    valoare_per_firma: dict = defaultdict(float)
    for f in flags:
        furn = f.get("furnizor", "")
        tip  = f.get("tip", "")
        if furn and tip:
            flags_per_firma[furn].add(tip)
            valoare_per_firma[furn] += f.get("valoare", 0) or 0

    for furnizor, tipuri in flags_per_firma.items():
        if len(tipuri) >= 3:
            cui_f   = next((c.get("castigator_cui","") for c in contracte if c["castigator"] == furnizor), "")
            valoare = valoare_per_firma[furnizor]
            cui_display = (cui_f.lstrip("RO").lstrip("ro")) if cui_f else "necunoscut"
            tipuri_str  = ", ".join(sorted(tipuri))
            flags.append({
                "tip": "RISC_SISTEMIC_FIRMA",
                "severitate": "CRITIC",
                "titlu": f"Furnizor cu indicatori cumulați — {len(tipuri)} categorii",
                "descriere": (
                    f'<strong>{furnizor}</strong> (CUI {cui_display}) apare în '
                    f'<strong>{len(tipuri)} categorii de indicatori</strong>: {tipuri_str}. '
                    f'Suma asociată flagurilor (poate include același contract de mai multe ori): '
                    f'<strong>{_fmt_ron(valoare)}</strong>. Cumulul prioritizează verificarea manuală '
                    f'și nu reprezintă o constatare juridică. '
                    f'<a href="{_termene_url(cui_f)}" target="_blank" rel="noopener noreferrer">Verifică pe termene.ro →</a>'
                ),
                "contract_id": "global",
                "contract_numar": "",
                "valoare": valoare,
                "furnizor": furnizor,
                "cif_furnizor": cui_f,
                "data": datetime.now().strftime("%Y-%m-%d"),
                "tip_procedura": "Multiple",
                "tipuri_detectate": list(tipuri),
            })

    # ── §2.1 Fragmentare temporară (fereastră 90 zile, toate contractele)
    flags.extend(detect_fragmentare_temporara(contracte, config))

    # ── §2.2 Concentrare furnizor (top-3 > 60% din valoare totală)
    flags.extend(detect_concentrare_furnizor(contracte, config))

    # ── §2.7 Publicare întârziată (necesită data_atribuire — graceful no-op dacă lipsește)
    flags.extend(detect_publicare_intarziata(contracte))

    # ── §2.1-audit Valori identice la firme diferite în aceeași zi
    flags.extend(detect_valori_identice_aceeasi_zi(contracte))

    # ── §2.2-audit Burst contracte — volum anormal într-o singură zi
    flags.extend(detect_burst_contracte(contracte))

    # ── §2.7-audit Semnare în zile nelucrătoare (weekend / sărbătoare legală)
    flags.extend(detect_semnare_zile_nelucratoare(contracte))

    # ── §2.5-audit Anomalie geografică (servicii locale de la firme din alt județ)
    # Necesită openapi.ro key în config → firme_openapi conține câmpul 'judet'
    if firme_openapi:
        flags.extend(detect_geographic_anomaly(contracte, firme_openapi))

    # Deduplicare (același furnizor poate apărea în mai mulți algoritmi)
    flags_unice = []
    ids_vazute = set()
    for f in flags:
        cid = f.get('contract_id') or f.get('contract_numar') or ''
        key = f"{f.get('tip','?')}_{cid}_{f.get('furnizor','?')}"
        if key not in ids_vazute:
            flags_unice.append(f)
            ids_vazute.add(key)

    print(f"    ✓ Detectate {len(flags_unice)} red flags "
          f"({sum(1 for f in flags_unice if f['severitate']=='CRITIC')} CRITIC, "
          f"{sum(1 for f in flags_unice if f['severitate']=='MAJOR')} MAJOR, "
          f"{sum(1 for f in flags_unice if f['severitate']=='MEDIU')} MEDIU)")

    return flags_unice


def normalizeaza_nume_firma(nume: str) -> str:
    """Normalizează un nume de firmă pentru comparare/căutare.

    Exportul SEAP livrează nume „murdare": spații duble, diacritice
    inconsistente, „&" vs „and", sufixe juridice prezente sau nu.
    Fără normalizare, „DAV GARDEN&SERVICE SRL" nu se potrivea cu
    „DAV  GARDEN & SERVICE" (două spații, fără sufix) — firma exista în
    date, dar căutarea din raport returna zero rezultate.

    >>> normalizeaza_nume_firma("DAV  GARDEN & SERVICE")
    'dav garden and service'
    >>> normalizeaza_nume_firma("DAV GARDEN&SERVICE")
    'dav garden and service'
    """
    t = unicodedata.normalize("NFD", str(nume or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    # abrevieri punctate: „s.r.l." → „srl", „i.i." → „ii"
    t = re.sub(r"\b(?:[a-z]\.){2,}", lambda m: m.group(0).replace(".", ""), t)
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Sufixe juridice ignorate la potrivirea numelor de firme
SUFIXE_JURIDICE = {
    "srl", "srlu", "srld", "sarl", "sa", "sca", "snc", "scs",
    "pfa", "ii", "sc", "societate", "societatea", "comerciala",
    "asociatia", "asociatie", "ong",
}


def nume_firma_esential(nume: str) -> str:
    """Ca `normalizeaza_nume_firma`, dar fără sufixele juridice.

    >>> nume_firma_esential("SC OLTENIA GARDEN SRL")
    'oltenia garden'
    """
    return " ".join(
        t for t in normalizeaza_nume_firma(nume).split(" ")
        if t and t not in SUFIXE_JURIDICE
    )


def _titlu_fara_revizie(titlu: str) -> str:
    """Elimină sufixul „(Rev.N)" ca să obținem titlul canonic al contractului.

    Varianta veche trata doar Rev.2/Rev.3/Rev.4 prin `.replace()`, deci Rev.5+
    rămâneau grupuri separate și nu mai erau comparate între ele.

    >>> _titlu_fara_revizie("Amenajare spatii verzi (Rev.12)")
    'Amenajare spatii verzi'
    """
    return re.sub(r"\s*\(\s*rev\.?\s*\d+\s*\)", "", str(titlu or ""), flags=re.I).strip()


def construieste_index_cui(contracte: list, cale_geocoded: str = "firme_geocoded.json") -> dict:
    """Index furnizor-normalizat → CUI.

    Exportul SEAP nu pune CUI-ul pe anunțuri (0 din 304 flaguri îl aveau), deci
    căutarea după CUI în raport nu returna nimic. Îl recuperăm din contracte și
    din geocodare, ca să-l putem propaga în raport.json și în profilul de firmă.
    """
    index: dict = {}

    def _adauga(nume_brut: str, cui: str) -> None:
        cui = str(cui or "").strip()
        if not cui:
            return
        # indexăm sub ambele forme: cu sufix juridic și fără, ca „X SRL" și „X"
        # să găsească aceeași firmă (doar 28 din 94 de furnizori au sufixul în nume)
        for cheie in (normalizeaza_nume_firma(nume_brut), nume_firma_esential(nume_brut)):
            if cheie:
                index.setdefault(cheie, cui)

    for contract in contracte or []:
        _adauga(contract.get("castigator") or contract.get("firma") or "",
                contract.get("castigator_cui") or contract.get("cui") or "")
    try:
        if cale_geocoded and os.path.exists(cale_geocoded):
            with open(cale_geocoded, encoding="utf-8") as handle:
                for firma in json.load(handle):
                    _adauga(firma.get("name", ""), firma.get("cif") or "")
    except Exception as err:
        print(f"  [cui-index] {cale_geocoded} indisponibil: {err}")
    return index


def _cui_pentru_furnizor(furnizor: str, fallback: str, index: dict) -> str:
    """CUI-ul propriu al flagului dacă există, altfel din index."""
    direct = (fallback or "").strip()
    if direct:
        return direct
    index = index or {}
    return (index.get(normalizeaza_nume_firma(furnizor))
            or index.get(nume_firma_esential(furnizor))
            or "")


def _seap_url(contract_id: str, tip_procedura: str = '') -> str:
    """Construiește URL-ul direct SEAP dintr-un contract_id.

    Formate acceptate:
      achizitie-directa-2025-489392  → da-direct-acquisition
      contract-2025-79964            → contract-notice (licitatie deschisa)
      contract-2026-3957             → simplified-tender (procedura simplificata)

    Returnează URL-ul la anunțul specific, sau lista generică dacă ID-ul nu e parsabil.
    """
    primul_id = contract_id.split(",")[0].strip()
    parts = primul_id.split("-")
    numeric_id = parts[-1] if parts and parts[-1].isdigit() else ""
    if not numeric_id:
        return "https://e-licitatie.ro/pub/notices/da-direct-acquisition/list/0/0"

    # Detectăm tipul din prefix sau din tip_procedura
    tip_lower = (tip_procedura or '').lower()
    if primul_id.startswith('achizitie-directa'):
        path = 'da-direct-acquisition'
    elif 'simplif' in tip_lower or 'simplificate' in tip_lower:
        path = 'simplified-tender'
    elif 'deschisa' in tip_lower or 'deschis' in tip_lower:
        path = 'contract-notice'
    elif primul_id.startswith('contract-'):
        # fallback: licitatie/contract notice
        path = 'contract-notice'
    else:
        path = 'da-direct-acquisition'

    return f"https://e-licitatie.ro/pub/notices/{path}/view/{numeric_id}"


def _seap_nr(contract_id: str) -> str:
    """Extrage numărul/numerele SEAP din contract_id pentru afișare ca text copiabil.

    Ex: 'achizitie-directa-2025-489392,achizitie-directa-2025-489393'
        → 'Nr. SEAP: 489392, 489393'
    """
    ids = [cid.strip() for cid in contract_id.split(",") if cid.strip()]
    nums = []
    for cid in ids:
        parts = cid.split("-")
        if parts and parts[-1].isdigit():
            nums.append(parts[-1])
    if nums:
        return "Nr. SEAP: " + ", ".join(nums)
    return ""


def _fmt_ron(valoare: float) -> str:
    """Formatează o sumă în RON pentru afișare."""
    if valoare >= 1_000_000:
        return f"{valoare/1_000_000:.2f} mil. RON"
    elif valoare >= 1_000:
        return f"{valoare/1_000:.0f}K RON"
    return f"{valoare:.0f} RON"


def _format_kpi(x: float) -> str:
    """Formatează suma KPI în română: '12,3M RON', '500K RON', '150 RON'."""
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M RON".replace('.', ',')
    elif x >= 1_000:
        return f"{x / 1_000:.0f}K RON"
    return f"{x:.0f} RON"


def _similaritate_titlu(a: str, b: str) -> float:
    """Similaritate simplă între două titluri (Jaccard pe cuvinte)."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0
    return len(wa & wb) / len(wa | wb)


def _get_firme_anaf_batch(cui_list: list, fisier_cache: str = "cache_firme.json") -> dict:
    """
    Interoghează API-ul ANAF (v8) pentru informații despre firme furnizoare.
    Returnează dict keyed by CUI (string) cu:
      dataInregistrare, stare, denumire, nrRegCom, inactiv_tva
    Procesează în batch-uri de 499 CUI-uri (limita ANAF).

    Rezultatele sunt cache-uite TTL_ANAF_V9_DAYS zile în fisier_cache
    (cheia '_anaf_v9_data') — starea de înregistrare TVA se schimbă rar.
    """
    import time as _time

    result = {}
    cui_clean, cui_map = [], {}
    for cui_str in cui_list:
        if not cui_str:
            continue
        c = str(cui_str).strip().upper().lstrip("RO")
        try:
            cui_int = int(c)
            cui_clean.append(cui_int)
            cui_map[cui_int] = str(cui_str).strip()
        except ValueError:
            continue

    if not cui_clean:
        return result

    cache = _incarca_cache_firme(fisier_cache)
    anaf_cache = cache.get("_anaf_v9_data", {})
    now_ts = _time.time()

    # Separă CUI-urile cu cache valid de cele care trebuie interogate
    cui_de_interogat = []
    for cui_int in cui_clean:
        orig = cui_map[cui_int]
        entry = anaf_cache.get(orig)
        if entry and (now_ts - entry.get("_ts", 0)) <= TTL_ANAF_V9_DAYS * 86400:
            result[orig] = {k: v for k, v in entry.items() if k != "_ts"}
        else:
            cui_de_interogat.append(cui_int)

    if not cui_de_interogat:
        return result

    today  = datetime.now().strftime("%Y-%m-%d")
    url    = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
    BATCH  = 499
    total_found = 0

    for i in range(0, len(cui_de_interogat), BATCH):
        batch   = cui_de_interogat[i:i + BATCH]
        payload = [{"cui": ci, "data": today} for ci in batch]
        try:
            resp = requests.post(url, json=payload, timeout=25,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "MonitorCivic/1.0"})
            if resp.status_code != 200:
                print(f"    ⚠️  ANAF API status {resp.status_code} (batch {i//BATCH+1})")
                continue
            data = resp.json()
        except Exception as exc:
            print(f"    ⚠️  ANAF API eroare batch {i//BATCH+1}: {exc}")
            continue

        for item in data.get("found", []):
            dg   = item.get("date_generale", {})
            ci   = dg.get("cui") or item.get("cui")  # v9: CUI in date_generale; v8: la top
            if not ci:
                continue
            orig = cui_map.get(ci, str(ci))
            si   = item.get("stare_inactiv", {})
            stare_raw = (dg.get("stare_inregistrare") or "").upper()
            if si.get("statusInactivi"):
                stare = "INACTIV"
            elif "RADIAT" in stare_raw:
                stare = "RADIAT"
            elif "SUSPENDAT" in stare_raw:
                stare = "SUSPENDAT"
            elif stare_raw:
                stare = "ACTIV"
            else:
                stare = "NECUNOSCUT"
            entry = {
                "dataInregistrare": dg.get("data_infiintare") or None,
                "stare": stare,
                "denumire": dg.get("denumire", ""),
                "nrRegCom": dg.get("nrRegCom", ""),
                "inactiv_tva": bool(si.get("statusInactivi")),
            }
            result[orig] = entry
            anaf_cache[orig] = {**entry, "_ts": now_ts}
            total_found += 1

    cache["_anaf_v9_data"] = anaf_cache
    _salveaza_cache_firme(fisier_cache, cache)
    print(f"    ✓ ANAF firme: {total_found}/{len(cui_de_interogat)} găsite (interogate); {len(result) - total_found} din cache")
    return result


def _termene_url(cui: str) -> str:
    """Link direct termene.ro pentru verificare administrator și angajați."""
    c = str(cui).strip().upper().lstrip("RO")
    if c.isdigit():
        return f"https://termene.ro/firma/{c}"
    return f"https://termene.ro/cauta?q={urllib.parse.quote(cui)}"


def _incarca_cache_firme(fisier: str) -> dict:
    """Încarcă cache-ul local de date firme (evită cereri repetate la API)."""
    if Path(fisier).exists():
        try:
            with open(fisier, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _salveaza_cache_firme(fisier: str, cache: dict):
    """Salvează cache-ul local de date firme."""
    try:
        with open(fisier, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"    ⚠️  Nu am putut salva cache firme: {e}")


def _get_actionariat_openapi(cui_list: list, api_key: str, fisier_cache: str) -> dict:
    """
    Interoghează openapi.ro pentru date suplimentare despre firme.
    API-ul returnează date ANAF îmbogățite: radiata (bool), numar_reg_com, stare, ultima_declaratie.
    NU conține acționari/administrator (pentru acelea generăm link recom.ro din numar_reg_com).

    Returnează dict keyed by CUI (string) cu:
      - radiata: bool — firmă radiată (mai fiabil decât parsing ANAF text)
      - numar_reg_com: str — ex. "J40/1234/2020" pentru link ONRC
      - stare: str — text status complet
      - ultima_declaratie: str — data ultimei declarații fiscale
      - recom_url: str — link direct la recom.ro pentru verificare manuală acționari
    """
    # Also accept key from environment variable (GitHub Actions secret)
    if not api_key:
        api_key = os.environ.get("OPENAPI_RO_KEY", "")
    if not api_key:
        return {}

    cache = _incarca_cache_firme(fisier_cache)
    result = {}
    de_interogat = []

    for cui_str in cui_list:
        if not cui_str:
            continue
        key = str(cui_str).strip().upper().lstrip("RO")
        if key in cache:
            result[str(cui_str).strip()] = cache[key]
        else:
            de_interogat.append((str(cui_str).strip(), key))

    if de_interogat:
        print(f"    [openapi.ro] Interoghez {len(de_interogat)} firme noi (cache: {len(cache)} deja cunoscute)...")

    noi_in_cache = 0
    for orig, cui_clean in de_interogat:
        url = f"https://api.openapi.ro/api/companies/{cui_clean}"
        try:
            req = urllib.request.Request(url)
            req.add_header("x-api-key", api_key)
            req.add_header("User-Agent", "MonitorCivic/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read())
        except Exception as exc:
            if "403" in str(exc):
                print(f"    ❌ openapi.ro: cheie API invalidă — verifică CONFIG['openapi_ro_key']")
                break
            continue

        if data.get("error"):
            continue  # CUI invalid sau negăsit

        nr_reg = data.get("numar_reg_com") or ""
        # Construim link recom.ro: dacă avem nr_reg_com îl folosim, altfel CUI
        if nr_reg:
            recom = f"https://www.recom.ro/companies_ro_company_detail.aspx?id={cui_clean}"
        else:
            recom = f"https://www.recom.ro/companies_ro_company_detail.aspx?id={cui_clean}"

        entry = {
            "radiata": bool(data.get("radiata")),
            "numar_reg_com": nr_reg,
            "stare": data.get("stare", ""),
            "ultima_declaratie": data.get("ultima_declaratie") or "",
            "recom_url": recom,
            "judet": data.get("judet") or data.get("judet_cod") or "",   # pentru §2.5
            "adresa": data.get("adresa") or "",                            # pentru §2.5
            "sursa": "openapi.ro",
            "data_cache": datetime.now().strftime("%Y-%m-%d"),
        }

        result[orig]  = entry
        cache[cui_clean] = entry
        noi_in_cache += 1
        time.sleep(0.1)

    if noi_in_cache:
        _salveaza_cache_firme(fisier_cache, cache)
        print(f"    ✓ openapi.ro: {noi_in_cache} firme adăugate în cache")

    return result


def _fmt_actionariat(info: dict) -> str:
    """
    Formatează datele disponibile din openapi.ro pentru inserare în descrierea unui flag.
    Afișează status radiat, număr ORC și link recom.ro pentru verificare manuală acționari.
    """
    if not info:
        return ""
    parts = []

    if info.get("radiata"):
        parts.append('<span style="color:#C0392B;font-weight:700">⚠️ RADIATĂ în registrul comerțului</span>')

    nr_reg = info.get("numar_reg_com", "")
    if nr_reg:
        parts.append(f"📋 <u>Nr. ORC</u>: <strong>{nr_reg}</strong>")

    ultima = info.get("ultima_declaratie", "")
    if ultima:
        parts.append(f"📅 <u>Ultima declarație fiscală</u>: {ultima}")

    recom = info.get("recom_url", "")
    if recom:
        parts.append(
            f'<a href="{recom}" target="_blank" rel="noopener noreferrer" ' +
            'style="color:#0070C0;font-weight:600">🔍 Verifică acționari și administrator la ONRC →</a>'
        )

    return (" &nbsp;|&nbsp; ".join(parts)) if parts else ""


def _get_reprezentanti_onrc(cui_list: list, fisier_cache: str) -> dict:
    """
    Descarcă OD_FIRME.CSV și OD_REPREZENTANTI_LEGALI.CSV de pe ONRC/data.gov.ro
    și extrage administratori/directori pentru CUI-urile date.
    Rezultatele sunt cache-uite TTL_ONRC_DAYS zile în fisier_cache (cheia '_onrc_data').
    Returnează: {cui: {reprezentanti: [{nume, calitate, localitate}],
                        forma_juridica, data_inmatriculare, cod_inmatriculare}}
    """
    import time
    if not cui_list:
        return {}

    cache = _incarca_cache_firme(fisier_cache)
    onrc_cache = cache.get("_onrc_data", {})
    TTL_ZILE = TTL_ONRC_DAYS
    now_ts = time.time()

    needed = []
    for cui in cui_list:
        entry = onrc_cache.get(str(cui))
        if not entry or (now_ts - entry.get("_ts", 0)) > TTL_ZILE * 86400:
            needed.append(str(cui))

    if not needed:
        return {cui: onrc_cache[cui] for cui in cui_list if cui in onrc_cache}

    print(f"  [ONRC] Caut reprezentanți pentru {len(needed)} CUI-uri din data.gov.ro…")
    result = {cui: {"reprezentanti": [], "forma_juridica": "", "data_inmatriculare": "", "cod_inmatriculare": ""} for cui in needed}

    # --- Descoperă URL-ul setului de date ONRC ---
    try:
        import urllib.request, json as _json
        api_url = ("https://data.gov.ro/api/3/action/package_search"
                   "?q=Firme+inregistrate+Registrul+Comertului&rows=1&sort=metadata_modified+desc")
        with urllib.request.urlopen(api_url, timeout=20) as r:
            meta = _json.loads(r.read())
        resources = meta["result"]["results"][0]["resources"]
        url_firme = url_reprezentanti = ""
        for res in resources:
            name_lower = res.get("name", "").lower()
            url_res    = res.get("url", "")
            if "od_firme" in name_lower and url_firme == "":
                url_firme = url_res
            if "od_reprezentanti_legali" in name_lower and url_reprezentanti == "":
                url_reprezentanti = url_res
        if not url_firme or not url_reprezentanti:
            print("  [ONRC] Nu am găsit URL-urile CSV în data.gov.ro")
            return {}
    except Exception as exc:
        print(f"  [ONRC] Eroare la descoperire URL: {exc}")
        return {}

    # --- Pasul 1: OD_FIRME.CSV — construiește CUI → COD_INMATRICULARE ---
    cui_to_cod = {}
    cod_to_cui = {}
    cui_set = set(needed)
    try:
        with urllib.request.urlopen(url_firme, timeout=30) as resp:
            buf = b""
            header_skipped = False
            col_cui = col_cod = col_forma = col_data = -1
            for chunk in iter(lambda: resp.read(65536), b""):
                buf += chunk
                newline = b"\n"
                lines_raw = buf.split(newline)
                buf = lines_raw[-1]
                for raw in lines_raw[:-1]:
                    line = raw.decode("utf-8-sig", errors="replace").strip()
                    if not line:
                        continue
                    parts = line.split("^")
                    if not header_skipped:
                        header_skipped = True
                        for i, h in enumerate(parts):
                            h = h.strip().upper()
                            if h == "CUI":             col_cui   = i
                            if h == "COD_INMATRICULARE": col_cod = i
                            if h == "FORMA_JURIDICA":  col_forma = i
                            if h == "DATA_INMATRICULARE": col_data = i
                        continue
                    if col_cui < 0 or col_cod < 0:
                        continue
                    cui_val = parts[col_cui].strip().lstrip("0") if col_cui < len(parts) else ""
                    cod_val = parts[col_cod].strip() if col_cod < len(parts) else ""
                    if cui_val in cui_set:
                        cui_to_cod[cui_val] = cod_val
                        cod_to_cui[cod_val] = cui_val
                        if col_forma >= 0 and col_forma < len(parts):
                            result[cui_val]["forma_juridica"] = parts[col_forma].strip()
                        if col_data >= 0 and col_data < len(parts):
                            result[cui_val]["data_inmatriculare"] = parts[col_data].strip()
                        result[cui_val]["cod_inmatriculare"] = cod_val
                if len(cui_to_cod) >= len(needed):
                    break
    except Exception as exc:
        print(f"  [ONRC] Eroare la OD_FIRME.CSV: {exc}")

    if not cui_to_cod:
        print("  [ONRC] Nu am găsit CUI-urile în OD_FIRME.CSV")
        return result

    # --- Pasul 2: OD_REPREZENTANTI_LEGALI.CSV — extrage administratori/directori ---
    calitati_dorite = {
        "administrator", "director", "presedinte", "director general",
        "asociat", "actionar", "cenzor", "lichidator", "manager",
        "director executiv", "vicepresedinte",
    }
    cod_set = set(cui_to_cod.values())
    cod_found = set()
    try:
        with urllib.request.urlopen(url_reprezentanti, timeout=30) as resp:
            buf = b""
            header_skipped = False
            col_cod2 = col_persoana = col_calitate = col_loc = -1
            for chunk in iter(lambda: resp.read(65536), b""):
                buf += chunk
                newline = b"\n"
                lines_raw = buf.split(newline)
                buf = lines_raw[-1]
                for raw in lines_raw[:-1]:
                    line = raw.decode("utf-8-sig", errors="replace").strip()
                    if not line:
                        continue
                    parts = line.split("^")
                    if not header_skipped:
                        header_skipped = True
                        for i, h in enumerate(parts):
                            h = h.strip().upper()
                            if h == "COD_INMATRICULARE":   col_cod2     = i
                            if h == "PERSOANA_IMPUTERNICITA": col_persoana = i
                            if h == "CALITATE":            col_calitate = i
                            if h == "LOCALITATE":          col_loc      = i
                        continue
                    if col_cod2 < 0:
                        continue
                    cod_val = parts[col_cod2].strip() if col_cod2 < len(parts) else ""
                    if cod_val not in cod_set:
                        continue
                    calitate = (parts[col_calitate].strip().lower() if col_calitate >= 0 and col_calitate < len(parts) else "")
                    if not any(c in calitate for c in calitati_dorite):
                        continue
                    persoana = parts[col_persoana].strip() if col_persoana >= 0 and col_persoana < len(parts) else ""
                    localitate = parts[col_loc].strip() if col_loc >= 0 and col_loc < len(parts) else ""
                    cui_val = cod_to_cui.get(cod_val, "")
                    if cui_val and persoana:
                        result[cui_val]["reprezentanti"].append({
                            "nume": persoana,
                            "calitate": calitate.title(),
                            "localitate": localitate,
                        })
                        cod_found.add(cod_val)
                if len(cod_found) >= len(cod_set):
                    break
    except Exception as exc:
        print(f"  [ONRC] Eroare la OD_REPREZENTANTI_LEGALI.CSV: {exc}")

    # Salvează în cache
    for cui in needed:
        entry = result.get(cui, {})
        entry["_ts"] = now_ts
        onrc_cache[cui] = entry
    cache["_onrc_data"] = onrc_cache
    _salveaza_cache_firme(fisier_cache, cache)
    print(f"  [ONRC] Done: {sum(1 for v in result.values() if v['reprezentanti'])} firme cu reprezentanți găsiți")
    return result


def _fmt_reprezentanti(onrc_info: dict) -> str:
    """
    Formatează lista de reprezentanți ONRC ca HTML pentru inserare în flag.
    onrc_info = {'reprezentanti': [{nume, calitate, localitate}], 'cod_inmatriculare': ...}
    """
    if not onrc_info:
        return ""
    reps = onrc_info.get("reprezentanti", [])
    if not reps:
        return ""
    items = []
    for r in reps[:5]:
        loc = f' <span style="color:#888;font-size:11px">({r["localitate"]})</span>' if r.get("localitate") else ""
        items.append(
            f'<span style="font-size:11px"><strong>{r["calitate"]}</strong>: {r["nume"]}{loc}</span>'
        )
    cod = onrc_info.get("cod_inmatriculare", "")
    recom_link = ""
    if cod:
        recom_link = (
            f' <a href="https://www.recom.ro/companies_ro_company_detail.aspx?id={cod}" '
            'target="_blank" rel="noopener noreferrer" style="color:#0070C0;font-size:10px">recom.ro →</a>'
        )
    return (
        '<div style="margin-top:4px;font-size:11px;color:#555">'
        f'🏛 <u>Reprezentanți legali (ONRC)</u>:{recom_link}<br>'
        + " &nbsp;·&nbsp; ".join(items)
        + "</div>"
    )


# ==============================================================================
# 4. TRACKING STARE (detectare flags NOI față de rularea anterioară)
# ==============================================================================

def incarca_stare_anterioara(fisier: str) -> dict:
    """Încarcă starea din rularea anterioară."""
    if Path(fisier).exists():
        with open(fisier, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"flags_anterioare": [], "data_ultima_rulare": None, "contracte_vazute": []}


def salveaza_stare(fisier: str, flags: list, contracte: list, hcl_list: list = None):
    """Salvează starea curentă pentru comparație viitoare."""
    stare = {
        "flags_anterioare": [(f.get("contract_id") or f.get("contract_numar") or "") + "_" + f.get("tip", "") for f in flags],
        "contracte_vazute": [c["id"] for c in contracte],
        "hcl_urls_vazute": [h["url"] for h in (hcl_list or [])],
        "data_ultima_rulare": datetime.now().isoformat(),
        "total_flags": len(flags),
    }
    with open(fisier, "w", encoding="utf-8") as f:
        json.dump(stare, f, ensure_ascii=False, indent=2)
    print(f"  [Stare] Salvat în {fisier}")


def detecteaza_flags_noi(flags_curente: list, stare_anterioara: dict) -> list:
    """Returnează doar flags-urile care nu existau la ultima rulare."""
    ids_anterioare = set(stare_anterioara.get("flags_anterioare", []))
    noi = [f for f in flags_curente
           if ((f.get("contract_id") or f.get("contract_numar") or "") + "_" + f.get("tip", "")) not in ids_anterioare]
    return noi


# ==============================================================================
# 5. GENERARE RAPORT HTML
# ==============================================================================

def calculeaza_analiza_per_tip(flags: list, contracte: list) -> dict:
    """
    Calculează statistici detaliate per tip de flag pentru secțiunea
    'Analiză complexă pe categorie' din raportul HTML.
    Returnează dict cu lista de tipuri și datele aferente.
    """
    from collections import defaultdict

    tip_meta = {
        "OFERTANT_UNIC":          {"label": "Ofertant unic",            "emoji": "👤", "culoare": "#8E44AD"},
        "ACHIZITIE_DIRECTA_PRAG": {"label": "Achiziție directă > prag", "emoji": "⚠️", "culoare": "#C0392B"},
        "APROAPE_DE_PRAG":        {"label": "Aproape de prag",          "emoji": "🎯", "culoare": "#E67E22"},
        "FRAGMENTARE":            {"label": "Fragmentare contracte",     "emoji": "✂️", "culoare": "#D35400"},
        "PROCEDURA_NON_COMPETITIVA": {"label": "Procedură non-competitivă", "emoji": "🚫", "culoare": "#922B21"},
        "FURNIZOR_DOMINANT":      {"label": "Furnizor dominant",        "emoji": "🏭", "culoare": "#1A5276"},
        "CONTRACTE_CONSECUTIVE":  {"label": "Contracte consecutive",    "emoji": "📅", "culoare": "#117A65"},
        "CRESTERE_BRUSCA_VALOARE":{"label": "Creștere bruscă valoare",  "emoji": "📈", "culoare": "#B7950B"},
        "VALOARE_ROTUNDA_SUSPECTA":{"label": "Valoare rotundă suspectă","emoji": "🔢", "culoare": "#6C3483"},
        "FIRMA_INACTIVA":         {"label": "Firmă inactivă/radiată",   "emoji": "💀", "culoare": "#641E16"},
        "FIRMA_NOU_CREATA":          {"label": "Firmă nou înregistrată",    "emoji": "🆕", "culoare": "#1F618D"},
        "CONTRACT_IN_PRIMA_LUNA":    {"label": "Contract în prima lună",    "emoji": "⚡", "culoare": "#922B21"},
        "DECLARATIE_FISCALA_VECHE":  {"label": "Declarație fiscală veche",  "emoji": "📭", "culoare": "#7D3C98"},
        "RISC_SISTEMIC_FIRMA":       {"label": "Risc sistemic firmă",       "emoji": "🔥", "culoare": "#641E16"},
        "GEOGRAFIE_ANORMALA":        {"label": "Anomalie geografică",       "emoji": "🗺️", "culoare": "#117A65"},

    }

    per_tip = defaultdict(lambda: {
        "flags": [], "furnizori": defaultdict(float),
        "luni": defaultdict(int), "valoare_totala": 0
    })

    for f in flags:
        tip = f.get("tip", "ALTELE")
        per_tip[tip]["flags"].append(f)
        per_tip[tip]["valoare_totala"] += f.get("valoare", 0) or 0
        furn = f.get("furnizor", "")
        if furn:
            per_tip[tip]["furnizori"][furn] += f.get("valoare", 0) or 0
        data_str = f.get("data", "")
        if data_str and len(data_str) >= 7:
            luna = data_str[:7]  # "YYYY-MM"
            per_tip[tip]["luni"][luna] += 1

    result = []
    for tip, d in sorted(per_tip.items(), key=lambda x: -len(x[1]["flags"])):
        meta = tip_meta.get(tip, {"label": tip.replace("_", " ").title(), "emoji": "🔍", "culoare": "#555"})
        top_furnizori = sorted(d["furnizori"].items(), key=lambda x: -x[1])[:5]
        luni_sorted   = sorted(d["luni"].items())
        n_critic = sum(1 for f in d["flags"] if f.get("severitate") == "CRITIC")
        n_major  = sum(1 for f in d["flags"] if f.get("severitate") == "MAJOR")
        n_mediu  = sum(1 for f in d["flags"] if f.get("severitate") == "MEDIU")
        result.append({
            "tip": tip,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "culoare": meta["culoare"],
            "total": len(d["flags"]),
            "n_critic": n_critic,
            "n_major": n_major,
            "n_mediu": n_mediu,
            "valoare_totala": d["valoare_totala"],
            "top_furnizori": top_furnizori,
            "luni": luni_sorted,
        })
    return result


# ==============================================================================
# §1.2 — RECONCILIERE BUGET ANAF ↔ SEAP
# ==============================================================================

def _suma_seap_dedupata(contracte: list, an: int) -> tuple:
    """
    Deduplica contractele SEAP pe (titlu canonic, firma) intr-un an.

    SEAP republica valoarea INTREAGA la fiecare modificare (Rev.2 = act aditional).
    Algoritmul:
      1. Scoate sufixul '(Rev.X)' din titlu → titlu canonic
      2. Grupeaza dupa (titlu_canonic, identificator_firma)
      3. Pastreaza valoarea MAX din grup (= revizia curenta, cu valoarea actualizata)

    Accepta ambele scheme de campuri:
      - schema interna Python: 'valoare_ron', 'data_publicare', 'castigator_cui', 'castigator'
      - schema export contracte.json: 'valoare', 'data', 'cui', 'firma'

    Returns:
        (suma_dedup_ron: float, nr_contracte_unice: int)
    """
    import re as _re
    _rev_re = _re.compile(r'\s*\(Rev\.\d+\)\s*$', _re.IGNORECASE)
    seen: dict = {}
    for c in contracte:
        data = c.get('data_publicare') or c.get('data') or ''
        if str(an) not in data:
            continue
        titlu = c.get('titlu') or ''
        titlu_canonic = _rev_re.sub('', titlu).strip().lower()
        # Preferam CUI ca identificator firma (stabil); fallback la nume
        firma = (c.get('castigator_cui') or c.get('cui') or
                 c.get('castigator') or c.get('firma') or '').strip()
        if not titlu_canonic or not firma:
            continue  # skip date murdare
        key = (titlu_canonic, firma)
        valoare = float(c.get('valoare_ron') or c.get('valoare') or 0)
        if key not in seen or valoare > seen[key]:
            seen[key] = valoare
    return sum(seen.values()), len(seen)


def reconciliere_buget_seap(buget_anaf: dict, contracte_seap: list, an: int = 2025) -> dict:
    """
    Reconciliaza cheltuielile ANAF cu contractele SEAP deduplicate pentru un an dat.

    Args:
        buget_anaf: dict cu cel putin una din cheile:
                    - 'cheltuieli_total' (RON direct)
                    - 'cheltuieli_mil_ron' (milioane RON, din fetch_budget_transparenta)
                    Optional: 'cap_salarii', 'cap_transferuri', 'cap_investitii' (RON).
        contracte_seap: lista de contracte — accepta schema interna si schema export.
        an: anul de reconciliere (default 2025).

    Returns:
        Dict cu sumele agregate + procent vizibilitate + nr_contracte_unice +
        date_inconsistente (True daca SEAP > ANAF chiar si dupa dedup).

    Edge cases:
        - total_anaf == 0  → procentele sunt 0, fara ZeroDivisionError
        - gap < 0          → returnat ca 0; date_inconsistente = True
        - estimari_default_folosite → True daca buget_anaf nu are capitole detaliate
    """
    # --- Totalul ANAF: accepta RON direct sau milioane ---
    if buget_anaf.get('cheltuieli_total'):
        total_anaf = float(buget_anaf['cheltuieli_total'])
    elif buget_anaf.get('cheltuieli_mil_ron'):
        total_anaf = float(buget_anaf['cheltuieli_mil_ron']) * 1_000_000
    else:
        total_anaf = 0.0

    # --- Total SEAP dedupat: elimina Rev.X duplicate ---
    total_seap, nr_contracte_unice = _suma_seap_dedupata(contracte_seap, an)

    # --- Capitole non-SEAP ---
    are_capitole_detaliate = bool(buget_anaf.get('cap_salarii'))
    salarii = float(buget_anaf.get('cap_salarii') or total_anaf * 0.45)
    transferuri = float(buget_anaf.get('cap_transferuri') or total_anaf * 0.15)
    investitii = float(buget_anaf.get('cap_investitii') or 0)

    # --- Gap si consistenta ---
    gap_raw = total_anaf - salarii - transferuri - total_seap - investitii
    gap = max(gap_raw, 0.0)
    # Daca chiar si dupa dedup SEAP > ANAF, semnaleaza date inconsistente
    date_inconsistente = (total_seap > total_anaf) if total_anaf else False

    procent_seap = round((total_seap / total_anaf * 100), 1) if total_anaf else 0.0
    procent_gap  = round((gap / total_anaf * 100), 1) if total_anaf else 0.0

    return {
        'an':                        an,
        'total_anaf_ron':            total_anaf,
        'total_seap_ron':            total_seap,
        'nr_contracte_unice':        nr_contracte_unice,
        'salarii_estimate_ron':      salarii,
        'transferuri_ron':           transferuri,
        'investitii_ron':            investitii,
        'gap_neexplicat_ron':        gap,
        'procent_vizibil_in_seap':   procent_seap,
        'procent_gap':               procent_gap,
        'estimari_default_folosite': not are_capitole_detaliate,
        'date_inconsistente':        date_inconsistente,
    }


def genereaza_raport_html(budget: dict, contracte: list, flags: list,
                           flags_noi: list, config: dict) -> str:
    """Generează raportul HTML complet."""

    data_generare = datetime.now().strftime("%d %B %Y, %H:%M")
    total_val = sum(c["valoare_ron"] for c in contracte)
    directe = [c for c in contracte if "direct" in c["tip_procedura"].lower()
               or "negociere" in c["tip_procedura"].lower()]
    unic_ofertant = [c for c in contracte if c.get("nr_ofertanti", 0) == 1]

    # Culori severitate
    culori = {"CRITIC": "#C0392B", "MAJOR": "#E67E22", "MEDIU": "#F39C12"}
    emoji_sev = {"CRITIC": "🔴", "MAJOR": "🟠", "MEDIU": "🟡"}

    # Sortare: CRITIC primul, apoi MAJOR, apoi MEDIU
    ordine_sev = {"CRITIC": 0, "MAJOR": 1, "MEDIU": 2}
    flags_sortate = sorted(flags, key=lambda f: ordine_sev.get(f.get("severitate", "MEDIU"), 2))

    # ── Analiză complexă per tip de flag ─────────────────────────────────────
    analiza_per_tip = calculeaza_analiza_per_tip(flags_sortate, contracte)

    # ── SEO / Open Graph: numere dinamice din flags actuali ──────────────────
    n_total = len(flags)
    n_critic = sum(1 for f in flags if f.get("severitate") == "CRITIC")
    n_major = sum(1 for f in flags if f.get("severitate") == "MAJOR")
    n_contracte_semnale = numara_contracte_cu_semnale(flags, contracte)
    prag_servicii_fmt = f"{config.get('prag_servicii_furnizare', PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON):,.0f}".replace(",", ".")
    prag_lucrari_fmt = f"{config.get('prag_lucrari', PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON):,.0f}".replace(",", ".")
    seo_title = f"Raport Transparență — {n_total} Semnale de Risc"
    seo_description = (
        f"{n_total} semnale automate pe {n_contracte_semnale} contracte unice la "
        f"{config['nume_entitate']}. Indicatorii necesită verificare și nu sunt concluzii "
        f"juridice. Date din SEAP și ANAF, analizate prin 19 detectori."
    )

    # Serializăm contractele ca JSON pentru embed în HTML (folosit de JS pentru "toate contractele firmei")
    contracte_json_embed = json.dumps([{
        "id": c["id"],
        "titlu": c["titlu"][:80],
        "valoare": c["valoare_ron"],
        "data": c["data_publicare"],
        "tip": c["tip_procedura"],
        "firma": c["castigator"],
        "cui": c.get("castigator_cui", ""),
        "ofertanti": c.get("nr_ofertanti", 0),
    } for c in contracte], ensure_ascii=False)
    # ── Index CUI per furnizor ──────────────────────────────────────────────
    # Exportul SEAP nu pune CUI-ul pe flag-uri (0/304 aveau `cif_furnizor`),
    # deci căutarea după CUI în raport nu returna nimic. Îl recuperăm din
    # contracte + firme_geocoded.json și îl propagăm în raport.json.
    _cui_by_supplier = construieste_index_cui(contracte)

    def _cui_pentru(_furnizor: str, _fallback: str = "") -> str:
        return _cui_pentru_furnizor(_furnizor, _fallback, _cui_by_supplier)

    print(f"  [cui-index] CUI mapat pentru {len(_cui_by_supplier)} furnizori")

    # Construim raport_json pentru embed <script id="tp-data"> si raport.json
    _n_contracte = len(contracte)
    _val_totala = sum(c.get("valoare_ron", 0) for c in contracte)
    raport_json_obj = {
        "schema_version": "1.1",
        "generated_at": datetime.now().isoformat(),
        "entity": {"name": config["nume_entitate"], "cif": config["cui"], "judet": config.get("judet", "Ilfov")},
        "totals": {
            "flags": len(flags), "signals": len(flags),
            "contracts_analyzed": _n_contracte,
            "contracts_with_signals": n_contracte_semnale,
            "total_value_ron": _val_totala,
            "by_severity": {
                "CRITIC": sum(1 for f in flags if f.get("severitate") == "CRITIC"),
                "MAJOR":  sum(1 for f in flags if f.get("severitate") == "MAJOR"),
                "MEDIU":  sum(1 for f in flags if f.get("severitate") == "MEDIU"),
            },
        },
        "flags": [
            {"id": i, "severity": fl.get("severitate",""), "title": fl.get("titlu",""),
             "explanation": fl.get("descriere",""), "supplier": fl.get("furnizor",""),
             "supplier_cif": _cui_pentru(fl.get("furnizor",""), fl.get("cif_furnizor","")),
             "sum_ron": fl.get("valoare",0) or 0,
             "date": fl.get("data",""), "contract_id": (fl.get("contract_id") or fl.get("contract_numar") or ""),
             "procedure": fl.get("tip_procedura",""), "type": fl.get("tip",""),
             "anchor": f"nereguli-{i}"}
            for i, fl in enumerate(flags_sortate, 1)
        ],
        "scor_transparenta": config.get("_scor", {}),
        "legal_thresholds": {
            "products_services_ron_excl_vat": config.get(
                "prag_servicii_furnizare",
                PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON,
            ),
            "works_ron_excl_vat": config.get(
                "prag_lucrari",
                PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON,
            ),
            "verified_at": PRAGURI_LEGALE_VERIFICATE_LA,
            "source": PRAGURI_LEGALE_SURSA,
        },
    }
    raport_json_embedded = json.dumps(raport_json_obj, ensure_ascii=False)

    # Index: câte contracte are fiecare firmă
    nr_contracte_firma_map = {}
    for c in contracte:
        nr_contracte_firma_map[c["castigator"]] = nr_contracte_firma_map.get(c["castigator"], 0) + 1

    # ── Index risc per firmă (calculat ÎNAINTE de loop-ul flags_html) ────────
    # IMPORTANT: enumerarea începe de la 1 și respectă ordinea din `flags_sortate`,
    # exact ca la generarea `raport.json` de mai sus. Astfel `anchor` din profilul
    # de firmă indică ACEEAȘI neregulă ca ancora din lista principală
    # (înainte profilul avea o sursă de date paralelă, fără explicații și ancore,
    # ceea ce producea liste de acuzații fără nicio justificare).
    risc_firma: dict = {}
    for _i, _f in enumerate(flags_sortate, 1):
        _furn = _f.get("furnizor", "")
        if not _furn:
            continue
        if _furn not in risc_firma:
            risc_firma[_furn] = {
                "cui": _cui_pentru(_furn, _f.get("cif_furnizor", "")),
                "flags": [],
                "valoare_totala": 0,
                "n_critic": 0, "n_major": 0, "n_mediu": 0,
            }
        risc_firma[_furn]["flags"].append({
            "tip": _f.get("tip", ""),
            "titlu": _f.get("titlu", ""),
            "severitate": _f.get("severitate", ""),
            "valoare": _f.get("valoare", 0) or 0,
            "data": _f.get("data", ""),
            # câmpuri noi — aceleași ca în raport.json, ca profilul să poată
            # afișa explicația și să poată trimite la neregula detaliată
            "descriere": _f.get("descriere", ""),
            "anchor": f"nereguli-{_i}",
            "contract_id": (_f.get("contract_id") or _f.get("contract_numar") or ""),
        })
        risc_firma[_furn]["valoare_totala"] += _f.get("valoare", 0) or 0

    # Contoarele se calculează DIN lista efectivă de flags, nu în paralel cu ea.
    # Altfel badge-ul putea afișa „9 MEDIU" când în listă exista un singur flag MEDIU.
    for _fk, _rd in risc_firma.items():
        _sevs = [(_x.get("severitate") or "MEDIU").upper() for _x in _rd["flags"]]
        _rd["n_critic"] = sum(1 for _s in _sevs if _s == "CRITIC")
        _rd["n_major"]  = sum(1 for _s in _sevs if _s == "MAJOR")
        _rd["n_mediu"]  = len(_sevs) - _rd["n_critic"] - _rd["n_major"]
        _rd["n_total"]  = len(_sevs)
        _rd["scor"] = min(100, _rd["n_critic"]*10 + _rd["n_major"]*5 + _rd["n_mediu"]*2)

    # ── Cross-reference CUI lipsă din firme_geocoded.json ──────────────────
    # Majoritate flag-urilor SEAP nu au cif_furnizor. Îl recuperăm din geocodare.
    try:
        import json as _json_mod
        if os.path.exists("firme_geocoded.json"):
            _geo = _json_mod.load(open("firme_geocoded.json", encoding="utf-8"))
            _geo_by_name = {g["name"].upper().strip(): g["cif"] for g in _geo if g.get("cif")}
            _geo_prefix  = {}
            for _gn, _gc in _geo_by_name.items():
                _geo_prefix.setdefault(_gn[:15], []).append((_gn, _gc))
            for _furn, _rd in risc_firma.items():
                if _rd.get("cui"):
                    continue
                _nu = _furn.upper().strip()
                if _nu in _geo_by_name:
                    _rd["cui"] = _geo_by_name[_nu]
                    continue
                _cands = _geo_prefix.get(_nu[:15], [])
                if len(_cands) == 1:
                    _rd["cui"] = _cands[0][1]
    except Exception:
        pass

    # ── Pre-fetch date financiare firme furnizoare (opțional, cu cache SQLite) ──
    _firma_profile: dict[str, dict] = {}
    if _RISC_FIRMA_OK and not config.get("_offline_mode"):
        _cui_unici = {f.get('cif_furnizor', '') for f in flags_sortate if f.get('cif_furnizor')}
        for _cui in sorted(_cui_unici):   # sorted → ordine deterministă în logs
            try:
                _firma_profile[_cui] = _fetch_firma_anaf(_cui)
            except Exception as _e:
                print(f"  [risc_firma] Eroare la fetch CUI {_cui}: {_e}")
                _firma_profile[_cui] = {}

        # ── Merge indicatori financiari (zero-sal, zero-ca) în risc_firma ──
        # Acești indicatori vin din mfinante.gov.ro și alimentează chip-urile
        # «0 angajați» / «CA = 0 RON» din filtrele enhance.js.
        _cui_to_furn = {}
        for _furn, _rd in risc_firma.items():
            _c = _rd.get("cui", "")
            if _c:
                _cui_to_furn[_c] = _furn

        for _cui, _profil in _firma_profile.items():
            _furn = _cui_to_furn.get(_cui)
            if not _furn or not _profil or 'error' in _profil:
                continue
            _rd = risc_firma[_furn]
            # Folosim cea mai recentă dată de contract și valoarea maximă a firmei
            _dates = [_fg.get("data", "") for _fg in _rd["flags"] if _fg.get("data")]
            _latest_date = max(_dates) if _dates else ""
            _max_val = max((_fg.get("valoare", 0) or 0 for _fg in _rd["flags"]), default=0)
            if not _latest_date:
                continue
            try:
                _shell_flags = _evaluate_shell_risk(_profil, _latest_date, _max_val)
            except Exception:
                _shell_flags = []
            for _sf in _shell_flags:
                # tip cu spațiu pentru a fi detectat de enhance.js
                # (ZERO_ANGAJATI → "ZERO ANGAJATI"; CIFRA_AFACERI_ZERO → "CIFRA AFACERI ZERO")
                _tip_display = _sf["cod"].replace("_", " ")
                _rd["flags"].append({
                    "tip":       _tip_display,
                    "titlu":     _sf.get("descriere", ""),
                    "severitate": _sf["severitate"],
                    "valoare":   0,
                    "data":      "",
                })
                _sev2 = _sf["severitate"]
                if _sev2 == "CRITIC":   _rd["n_critic"] += 1
                elif _sev2 == "MAJOR":  _rd["n_major"]  += 1
                else:                   _rd["n_mediu"]   += 1
            # Recalculăm scorul inclusiv cu noii indicatori
            _rd["scor"] = min(100, _rd["n_critic"]*10 + _rd["n_major"]*5 + _rd["n_mediu"]*2)

    # ── Merge date financiare din firme_financiar.json (generat de import_financiar_datagov.py) ──
    # Alternativă la mfinante.gov.ro (care e 404 din mai 2026).
    # Workflow: rulezi manual import_financiar_datagov.py o dată/an, comiți firme_financiar.json.
    try:
        import json as _json_mod2
        if os.path.exists("firme_financiar.json"):
            _fin = _json_mod2.load(open("firme_financiar.json", encoding="utf-8"))
            import re as _re2
            _cui_to_furn2 = {}
            for _fk, _rd in risc_firma.items():
                _c = _re2.sub(r'^[Rr][Oo]\s*', '', str(_rd.get("cui","")).strip()).replace(' ', '')
                if _c and _c.isdigit():
                    _cui_to_furn2[_c] = _fk
            for _cui_str, _fin_data in _fin.items():
                _furn2 = _cui_to_furn2.get(_cui_str)
                if not _furn2:
                    continue
                _rd2 = risc_firma[_furn2]
                _ex_tips = {_fg.get("tip","") for _fg in _rd2["flags"]}
                _an  = _fin_data.get("an", "2024")
                _an_num = (_re2.sub(r'[^0-9]', '', str(_an)) or str(_an))[:4]
                _ca  = _fin_data.get("cifra_afaceri")
                _sal = _fin_data.get("nr_salariati")
                _dates2  = [_fg.get("data","") for _fg in _rd2["flags"] if _fg.get("data")]
                _maxv2   = max((_fg.get("valoare",0) or 0 for _fg in _rd2["flags"]), default=0)
                _ldate2  = max(_dates2) if _dates2 else f"{_an_num}-12-31"
                _profil2 = {"ani": {_an_num: {"cifra_afaceri": _ca, "salariati": _sal}}}
                if _RISC_FIRMA_OK:
                    try:
                        _sflags2 = _evaluate_shell_risk(_profil2, _ldate2, _maxv2)
                    except Exception:
                        _sflags2 = []
                    # Filtrăm granular flagurile deja existente
                    _new_sflags2 = [_sf2 for _sf2 in _sflags2
                                    if _sf2["cod"].replace("_", " ") not in _ex_tips]
                    for _sf2 in _new_sflags2:
                        _td2 = _sf2["cod"].replace("_", " ")
                        _rd2["flags"].append({"tip": _td2, "titlu": _sf2.get("descriere",""),
                                              "severitate": _sf2["severitate"], "valoare": 0, "data": ""})
                        _s3 = _sf2["severitate"]
                        if _s3 == "CRITIC":   _rd2["n_critic"] += 1
                        elif _s3 == "MAJOR":  _rd2["n_major"]  += 1
                        else:                 _rd2["n_mediu"]   += 1
                    if _new_sflags2:
                        _rd2["scor"] = min(100, _rd2["n_critic"]*10 + _rd2["n_major"]*5 + _rd2["n_mediu"]*2)
    except Exception:
        pass

    flags_html = ""
    for idx, f in enumerate(flags_sortate, 1):
        culoare = culori.get(f["severitate"], "#999")
        emoji = emoji_sev.get(f["severitate"], "⚪")
        nou_badge = ' <span style="background:#E8F5E9;color:#2E7D32;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">NOU</span>' if f in flags_noi else ""

        # Extragem furnizor ÎNAINTE de a-l folosi în risc_badge
        contract_id = (f.get('contract_id') or f.get('contract_numar') or '').strip()
        contract_numar_display = (f.get('contract_numar') or '').strip()
        furnizor = (f.get('furnizor') or '').strip()
        firma_scurta = furnizor[:35] + ('…' if len(furnizor) > 35 else '')
        nr_firma = nr_contracte_firma_map.get(furnizor, 0)

        # Escaping pentru JS (ghilimele simple în numele firmei)
        furnizor_js = furnizor.replace("'", "\\'").replace('"', '&quot;')

        # Risk score badge for this company (furnizor definit deja mai sus)
        rd_firma = risc_firma.get(furnizor, {})
        scor_firma = rd_firma.get("scor", 0)
        if scor_firma >= 50:
            risc_badge = f' <span style="background:#C0392B;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;cursor:pointer" onclick="openFirmaPanel(\'{furnizor_js}\', event)">🔥 RISC {scor_firma}</span>'
        elif scor_firma >= 20:
            risc_badge = f' <span style="background:#E67E22;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;cursor:pointer" onclick="openFirmaPanel(\'{furnizor_js}\', event)">⚠️ RISC {scor_firma}</span>'
        elif scor_firma >= 5:
            risc_badge = f' <span style="background:#F39C12;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;cursor:pointer" onclick="openFirmaPanel(\'{furnizor_js}\', event)">🟡 RISC {scor_firma}</span>'
        else:
            risc_badge = ""

        # Pre-compute atribute data-* pentru markup semantic
        valoare_num = int(f.get('valoare', 0) or 0)
        furnizor_attr = furnizor.replace('"', '&quot;')
        tip_attr = (f.get('tip') or '').replace('"', '&quot;')
        procedura_attr = (f.get('tip_procedura') or '').replace('"', '&quot;')

        # Pre-compute butonul firmei (evităm nested f-string cu același tip de ghilimele)
        if furnizor:
            btn_firma = (
                f'<button onclick="showFirmaContracts(\'{furnizor_js}\', event)"'
                f' style="background:#EBF5FB;color:#0070C0;padding:6px 14px;border-radius:6px;'
                f'font-size:12px;font-weight:600;border:1px solid #AED6F1;cursor:pointer">'
                f'📊 Toate contractele cu {firma_scurta} ({nr_firma} contracte)'
                f'</button> '
            f'<button onclick="openFirmaPanel(\'{furnizor_js}\', event)"'
                f' style="background:#FDEDEC;color:#C0392B;padding:6px 14px;border-radius:6px;'
                f'font-size:12px;font-weight:600;border:1px solid #F1948A;cursor:pointer">'
                f'🔍 Profil complet firmă'
                f'</button>'
            )
        else:
            btn_firma = ''

        # Panel date financiare firmă (risc_firma.py — opțional)
        _cif_f = f.get('cif_furnizor', '')
        if _RISC_FIRMA_OK and _cif_f and _cif_f in _firma_profile:
            _firma_panel_html = _get_risk_panel_html(
                _cif_f, _firma_profile[_cif_f],
                f.get('data', ''), f.get('valoare', 0) or 0,
            )
        else:
            _firma_panel_html = ''

        # Sublistă contracte componente (ex. flag BURST_CONTRACTE — „9 contracte într-o zi")
        _contracte_comp = f.get('contracte') or []
        if _contracte_comp:
            _rows = ""
            for _c in _contracte_comp:
                _cid = _c.get('id') or ''
                _seap_txt = _seap_nr(_cid) or (f"Nr. SEAP: {_c.get('nr_seap')}" if _c.get('nr_seap') else '')
                _seap_cell = (
                    f'<a href="{_seap_url(_cid, _c.get("procedura",""))}" target="_blank" '
                    f'rel="noopener noreferrer" onclick="event.stopPropagation()" style="color:#0070C0;text-decoration:none">'
                    f'🔍 {_seap_txt or "deschide"} ↗</a>'
                ) if (_cid or _c.get('nr_seap')) else '–'
                _rows += (
                    '<tr>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid #eee">{_c.get("firma") or "–"}</td>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap">{_fmt_ron(_c.get("valoare",0) or 0)}</td>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid #eee">{_c.get("procedura") or "–"}</td>'
                    f'<td style="padding:5px 8px;border-bottom:1px solid #eee">{_seap_cell}</td>'
                    '</tr>'
                )
            _contracte_lista_html = (
                '<div style="margin-top:12px">'
                f'<div style="font-size:12px;font-weight:700;color:#555;margin-bottom:6px">'
                f'📑 Cele {len(_contracte_comp)} contracte componente:</div>'
                '<table style="width:100%;border-collapse:collapse;font-size:12px">'
                '<thead><tr style="text-align:left;color:#888">'
                '<th style="padding:5px 8px;border-bottom:2px solid #ddd">Firmă</th>'
                '<th style="padding:5px 8px;border-bottom:2px solid #ddd;text-align:right">Valoare</th>'
                '<th style="padding:5px 8px;border-bottom:2px solid #ddd">Procedură</th>'
                '<th style="padding:5px 8px;border-bottom:2px solid #ddd">SEAP</th>'
                '</tr></thead>'
                f'<tbody>{_rows}</tbody>'
                '</table></div>'
            )
        else:
            _contracte_lista_html = ''

        flags_html += f"""
        <div class="tp-flag"
             onclick="toggleFlag(this)"
             id="nereguli-{idx}"
             data-severity="{f.get('severitate','MEDIU')}"
             data-supplier="{furnizor_attr}"
             data-sum-ron="{valoare_num}"
             data-date="{f.get('data', '')}"
             data-contract-id="{contract_id}"
             data-type="{tip_attr}"
             data-procedure="{procedura_attr}"
             data-supplier-cif="{_cif_f}"
             style="border-left:4px solid {culoare};background:#fff;padding:14px 18px;
                    border-radius:0 8px 8px 0;margin-bottom:10px;
                    box-shadow:0 1px 3px rgba(0,0,0,0.08);cursor:pointer"
             onmouseenter="this.style.boxShadow='0 4px 14px rgba(0,0,0,0.14)'"
             onmouseleave="this.style.boxShadow='0 1px 3px rgba(0,0,0,0.08)'">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="font-size:12px;font-weight:700;color:#bbb;min-width:32px">#{idx}</span>
            <span style="font-size:16px">{emoji}</span>
            <strong style="color:{culoare}">[{f.get('severitate','MEDIU')}]</strong>
                     <span style="font-weight:700;font-size:14px">{furnizor or "—"}</span>
                     <span style="font-size:11px;color:#888;font-weight:400"> — {f.get('titlu','')}</span>
            {nou_badge}{risc_badge}<span class="flag-arrow" style="margin-left:auto;font-size:11px;color:#aaa">▼ detalii</span>
          </div>
          <p style="font-size:13px;color:#444;margin:0 0 8px">{f.get('descriere','')}</p>
          <div style="font-size:12px;color:#777;display:flex;gap:16px;flex-wrap:wrap">
            <span>💰 {_fmt_ron(f.get('valoare',0) or 0)}</span>
            <span>🏢 {furnizor or '–'}</span>
            <span>📅 {f.get('data','')}</span>
            <span>⚙️ {f.get('tip_procedura') or '–'}</span>
            {(f'<span style="background:#EBF5FB;border:1px solid #AED6F1;border-radius:4px;padding:1px 7px;color:#1A5276;font-weight:700;letter-spacing:.3px" title="Număr SEAP — copiază-l pentru căutare manuală">🔍 {_seap_nr(contract_id)}</span>') if _seap_nr(contract_id) else f'<span>📋 {contract_id or "–"}</span>'}
          </div>
          <div class="flag-detail" style="display:none;margin-top:14px;padding-top:12px;border-top:1px solid #eee">
            <div style="font-size:12px;color:#555;margin-bottom:10px">
              <strong>Firmă:</strong> {furnizor or '–'} &nbsp;|&nbsp;
              <strong>Sumă:</strong> {_fmt_ron(f.get('valoare',0) or 0)} &nbsp;|&nbsp;
              <strong>Data:</strong> {f.get('data','')} &nbsp;|&nbsp;
              <strong>Procedură:</strong> {f.get('tip_procedura') or '–'}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <a href="{_seap_url(contract_id, f.get('tip_procedura',''))}"
                 target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"
                 style="background:#0070C0;color:#fff;padding:6px 14px;border-radius:6px;
                        text-decoration:none;font-size:12px;font-weight:600">
                🔍 Deschide în SEAP →
              </a>
              <a href="https://transparenta.eu/entities/{config['cui']}#achizitii"
                 target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"
                 style="background:#1E8449;color:#fff;padding:6px 14px;border-radius:6px;
                        text-decoration:none;font-size:12px;font-weight:600">
                🌐 transparenta.eu →
              </a>
              {btn_firma}</div>
            {_contracte_lista_html}
            {_firma_panel_html}
            <div style="margin-top:10px;padding:8px 12px;background:#F4F6F8;border-radius:6px;
                        font-size:11px;color:#666;line-height:1.6">
              ℹ️ <strong>Cum verifici în SEAP:</strong> apasă „Deschide în SEAP" de mai sus.
              Dacă pagina apare goală, caută manual pe
              <a href="https://e-licitatie.ro/pub/" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()"
                 style="color:#0070C0">e-licitatie.ro</a>
              după <strong>{_seap_nr(contract_id) or contract_id}</strong>
              (data: <strong>{f.get('data','')}</strong>, autoritate: <strong>Pantelimon</strong>).
            </div>
          </div>
        </div>"""

    # ── HTML: Analiză pe categorie ───────────────────────────────────────────
    analiza_per_tip_html = ""
    if analiza_per_tip:
        cards_html = ""
        panels_html = ""
        for d in analiza_per_tip:
            tip_id = d["tip"].lower().replace("_", "-")
            sev_badges = ""
            if d["n_critic"]: sev_badges += f'<span style="background:#C0392B;color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;font-weight:700">{d["n_critic"]} CRITIC</span> '
            if d["n_major"]:  sev_badges += f'<span style="background:#E67E22;color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;font-weight:700">{d["n_major"]} MAJOR</span> '
            if d["n_mediu"]:  sev_badges += f'<span style="background:#F39C12;color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;font-weight:700">{d["n_mediu"]} MEDIU</span>'
            cards_html += f"""
            <div class="atp-card" data-tip="{tip_id}"
                 onclick="showAtp('{tip_id}', this)"
                 style="background:#fff;border-radius:10px;padding:16px;cursor:pointer;
                        border-top:4px solid {d["culoare"]};box-shadow:0 1px 4px rgba(0,0,0,.08);
                        transition:box-shadow .15s"
                 onmouseenter="this.style.boxShadow='0 4px 14px rgba(0,0,0,.15)'"
                 onmouseleave="this.style.boxShadow='0 1px 4px rgba(0,0,0,.08)'">
              <div style="font-size:22px;font-weight:800;color:{d["culoare"]}">{d["total"]}</div>
              <div style="font-size:12px;font-weight:700;color:#333;margin:4px 0">{d["emoji"]} {d["label"]}</div>
              <div style="font-size:11px;color:#777">{_fmt_ron(d["valoare_totala"])}</div>
              <div style="margin-top:6px">{sev_badges}</div>
            </div>"""

            # Build top suppliers rows
            furnizori_rows = ""
            for rank, (furn, val) in enumerate(d["top_furnizori"], 1):
                pct = (val / d["valoare_totala"] * 100) if d["valoare_totala"] else 0
                furnizori_rows += f"""
                <tr style="background:{"#fff" if rank%2==0 else "#f8f9fa"}">
                  <td style="padding:6px 10px;font-size:12px;font-weight:700;color:#555">{rank}</td>
                  <td style="padding:6px 10px;font-size:12px">{furn[:55]}</td>
                  <td style="padding:6px 10px;font-size:12px;font-weight:700">{_fmt_ron(val)}</td>
                  <td style="padding:6px 10px;font-size:12px">
                    <div style="background:#e0e0e0;border-radius:4px;height:8px;width:120px">
                      <div style="background:{d["culoare"]};height:8px;border-radius:4px;width:{min(pct,100):.0f}%"></div>
                    </div>
                    <span style="font-size:10px;color:#777">{pct:.0f}%</span>
                  </td>
                </tr>"""

            # Build monthly timeline
            luna_rows = ""
            max_luna = max((v for _, v in d["luni"]), default=1) or 1
            for luna_key, cnt in d["luni"]:
                bar_w = int(cnt / max_luna * 120)
                luna_rows += f"""
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                  <span style="font-size:11px;color:#555;min-width:56px">{luna_key}</span>
                  <div style="background:#e0e0e0;border-radius:3px;height:14px;width:120px">
                    <div style="background:{d["culoare"]};height:14px;border-radius:3px;width:{bar_w}px"></div>
                  </div>
                  <span style="font-size:11px;font-weight:700;color:#333">{cnt}</span>
                </div>"""

            panels_html += f"""
            <div id="atp-panel-{tip_id}" style="display:none;margin-top:20px;
                 background:#fff;border-radius:10px;border-left:4px solid {d["culoare"]};
                 padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px">
                <h3 style="margin:0;color:{d["culoare"]};font-size:16px">{d["emoji"]} {d["label"]}</h3>
                <span onclick="hideAtp()" style="cursor:pointer;font-size:13px;color:#999;
                       background:#f5f5f5;padding:4px 10px;border-radius:6px">✕ închide</span>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
                <div style="background:#f8f9fa;border-radius:8px;padding:12px">
                  <div style="font-size:22px;font-weight:800;color:{d["culoare"]}">{d["total"]}</div>
                  <div style="font-size:11px;color:#777;text-transform:uppercase">Semnale detectate</div>
                </div>
                <div style="background:#f8f9fa;border-radius:8px;padding:12px">
                  <div style="font-size:22px;font-weight:800;color:{d["culoare"]}">{_fmt_ron(d["valoare_totala"])}</div>
                  <div style="font-size:11px;color:#777;text-transform:uppercase">Sumă asociată flagurilor*</div>
                </div>
              </div>
              {"<h4 style='margin:12px 0 8px;font-size:13px;color:#555'>🏆 Top furnizori implicați</h4><div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:12px'><thead><tr style='background:" + d["culoare"] + ";color:#fff'><th style='padding:6px 10px'>#</th><th style='padding:6px 10px'>Firmă</th><th style='padding:6px 10px'>Valoare</th><th style='padding:6px 10px'>Pondere</th></tr></thead><tbody>" + furnizori_rows + "</tbody></table></div>" if furnizori_rows else ""}
              {"<h4 style='margin:16px 0 8px;font-size:13px;color:#555'>📅 Evoluție lunară</h4>" + luna_rows if luna_rows else ""}
            </div>"""

        analiza_per_tip_html = f"""
    <div style="margin-bottom:12px">
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:8px">
        {cards_html}
      </div>
      <div id="atp-panels">{panels_html}</div>
    </div>
    <script>
    function showAtp(tipId, cardEl) {{
      document.querySelectorAll('.atp-card').forEach(function(c) {{ c.style.opacity='0.6'; c.style.transform=''; }});
      if (cardEl) {{ cardEl.style.opacity='1'; cardEl.style.transform='translateY(-2px)'; }}
      var panelId = 'atp-panel-' + tipId;
      document.querySelectorAll('[id^="atp-panel-"]').forEach(function(p) {{
        p.style.display = p.id === panelId && p.style.display === 'none' ? 'block' : 'none';
      }});
      var panel = document.getElementById(panelId);
      if (panel && panel.style.display === 'block') {{ panel.scrollIntoView({{behavior:'smooth',block:'nearest'}}); }}
      else {{ document.querySelectorAll('.atp-card').forEach(function(c) {{ c.style.opacity='1'; c.style.transform=''; }}); }}
    }}
    function hideAtp() {{
      document.querySelectorAll('[id^="atp-panel-"]').forEach(function(p) {{ p.style.display='none'; }});
      document.querySelectorAll('.atp-card').forEach(function(c) {{ c.style.opacity='1'; c.style.transform=''; }});
    }}
    </script>"""

    # Includem și datele ONRC/openapi.ro per firmă dacă sunt disponibile
    firme_onrc    = config.get("_firme_onrc", {})
    firme_openapi = config.get("_firme_openapi", {})
    risc_firma_json = json.dumps({
        furn: {
            "cui": rd["cui"],
            "scor": rd["scor"],
            "n_critic": rd["n_critic"],
            "n_major": rd["n_major"],
            "n_mediu": rd["n_mediu"],
            "valoare_totala": rd["valoare_totala"],
            # Plafon 50 (max. real: 29 semnale/firmă). `n_total` e expus explicit
            # ca panoul să poată spune când lista e trunchiată — înainte badge-urile
            # numărau tot, iar lista era tăiată la 20, fără niciun indiciu.
            "flags": rd["flags"][:50],
            "n_total": len(rd["flags"]),
            "onrc": {
                "reprezentanti": firme_onrc.get(rd["cui"], {}).get("reprezentanti", [])[:8],
                "cod_inmatriculare": firme_onrc.get(rd["cui"], {}).get("cod_inmatriculare", ""),
                "forma_juridica": firme_onrc.get(rd["cui"], {}).get("forma_juridica", ""),
                "data_inmatriculare": firme_onrc.get(rd["cui"], {}).get("data_inmatriculare", ""),
            },
            "openapi": {
                "numar_reg_com":    firme_openapi.get(rd["cui"], {}).get("numar_reg_com", ""),
                "stare":            firme_openapi.get(rd["cui"], {}).get("stare", ""),
                "ultima_declaratie": firme_openapi.get(rd["cui"], {}).get("ultima_declaratie", ""),
                "recom_url":        firme_openapi.get(rd["cui"], {}).get("recom_url", ""),
                "radiata":          firme_openapi.get(rd["cui"], {}).get("radiata", False),
            },
        } for furn, rd in risc_firma.items()
    }, ensure_ascii=False)

    contracte_html = ""
    for c in contracte[:20]:  # primele 20
        badge_tip = ("🔴" if "direct" in c["tip_procedura"].lower() or "negociere" in c["tip_procedura"].lower()
                     else "🟢" if "deschis" in c["tip_procedura"].lower() else "🟡")
        _nro = c.get("nr_ofertanti", 0)
        _nro_color = "#C0392B" if _nro == 1 else "#27AE60"
        badge_ofertanti = f'<span style="color:{_nro_color};font-weight:700">{_nro}</span>'
        nota_demo = ' <em style="color:#aaa;font-size:10px">(demo)</em>' if c.get("sursa") == "DEMO" else ""
        contracte_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:13px">
            {c['titlu'][:55]}{'…' if len(c['titlu'])>55 else ''}{nota_demo}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:13px;font-weight:700">{_fmt_ron(c['valoare_ron'])}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:12px">{badge_tip} {c['tip_procedura']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:12px;text-align:center">{badge_ofertanti}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:12px">{c['castigator'][:30]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-size:12px">{c['data_publicare']}</td>
        </tr>"""

    budget_html = ""
    if budget.get("venituri_mil_ron"):
        yoy_v = budget.get("yoy_venituri", "N/A")
        yoy_c = budget.get("yoy_cheltuieli", "N/A")
        yoy_v_color = "#C0392B" if "-" in str(yoy_v) else "#27AE60"
        yoy_c_color = "#C0392B" if "+" in str(yoy_c) else "#27AE60"
        budget_html = f"""
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;margin-bottom:24px">
          <div style="background:#fff;border-radius:10px;padding:20px;border-top:4px solid #0070C0;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
            <span style="font-size:24px;font-weight:800;color:#0070C0">{budget['venituri_mil_ron']} mil. RON</span><br>
            <span style="font-size:11px;color:#777;text-transform:uppercase">Venituri {budget['an']}</span><br>
            <span style="font-size:12px;color:{yoy_v_color}">{yoy_v} față de {budget['an']-1}</span>
          </div>
          <div style="background:#fff;border-radius:10px;padding:20px;border-top:4px solid #E67E22;box-shadow:0 1px 4px rgba(0,0,0,0.08)">
            <span style="font-size:24px;font-weight:800;color:#E67E22">{budget['cheltuieli_mil_ron']} mil. RON</span><br>
            <span style="font-size:11px;color:#777;text-transform:uppercase">Cheltuieli {budget['an']}</span><br>
            <span style="font-size:12px;color:{yoy_c_color}">{yoy_c} față de {budget['an']-1}</span>
          </div>
          <div style="background:#fff;border-radius:10px;padding:20px;border-top:4px solid {'#27AE60' if (budget.get('balanta_mil_ron') or 0)>0 else '#C0392B'};box-shadow:0 1px 4px rgba(0,0,0,0.08)">
            <span style="font-size:24px;font-weight:800;color:{'#27AE60' if (budget.get('balanta_mil_ron') or 0)>0 else '#C0392B'}">{budget.get('balanta_mil_ron','N/A')} mil. RON</span><br>
            <span style="font-size:11px;color:#777;text-transform:uppercase">Balanță {budget['an']}</span><br>
            <span style="font-size:12px;color:#777">Sursa: {budget['sursa']}</span>
          </div>
        </div>"""

    nota_demo_msg = ""
    if any(c.get("sursa") == "DEMO" for c in contracte):
        nota_demo_msg = """
        <div style="background:#FFF3CD;border-left:4px solid #F39C12;padding:12px 16px;
                    border-radius:6px;font-size:13px;color:#7D6608;margin-bottom:16px">
          <strong>⚠️ Date demonstrative:</strong> API-ul SEAP nu a putut fi accesat în această rulare.
          Contractele afișate sunt demonstrative. Verificați manual la
          <a href="https://www.e-licitatie.ro/pub" target="_blank" rel="noopener noreferrer">e-licitatie.ro</a>.
        </div>"""

    # ── §4.1 — Widget reconciliere ANAF ↔ SEAP ──────────────────────────────
    _an_reco = budget.get('an', 2025)
    _reco = reconciliere_buget_seap(budget, contracte, an=_an_reco)

    def _ro(n):
        """Format numar in stil romanesc: separator mii = punct."""
        return f'{n:,.0f}'.replace(',', '.')

    _reco_disclaimer = (
        ' <em style="font-size:.85em">Estimarile pentru salarii si transferuri '
        'folosesc procente tipice de UAT (45% si 15%); valorile exacte vor fi '
        'adaugate cand executia bugetara pe capitole va fi disponibila in '
        'date.gov.ro.</em>'
        if _reco['estimari_default_folosite'] else ''
    )

    # Celula GAP + celula SEAP (label) + nota principala — toate conditionate pe date_inconsistente
    if _reco['date_inconsistente']:
        _seap_label = '<small>Vizibil in SEAP (procent indisponibil)</small>'
        _gap_cell = (
            '<div class="tp-reco-cell tp-reco-gap">'
            '<span style="font-size:.95rem">n/a</span>'
            '<small>Suma SEAP dep&#259;&#351;e&#351;te ANAF &mdash; '
            'date posibil incomplete sau in actualizare</small>'
            '</div>'
        )
        _nota_inconsistenta = (
            '<strong>Not&#259;:</strong> Suma contractelor SEAP dep&#259;&#351;e&#351;te '
            'totalul cheltuielilor ANAF &mdash; semn c&#259; datele bugetare sunt par&#355;iale '
            'sau c&#259; SEAP include contracte multi-anuale publicate in acest an. '
            'Reconcilierea va fi disponibil&#259; dup&#259; ce prim&#259;ria public&#259; '
            'execu&#355;ia bugetar&#259; pe {an} in date.gov.ro.'.format(an=_an_reco)
        )
        _nota_principala = ''
    else:
        _seap_label = f'<small>Vizibil in SEAP ({_reco["procent_vizibil_in_seap"]}%)</small>'
        _gap_cell = (
            f'<div class="tp-reco-cell tp-reco-gap">'
            f'<span>~{_ro(_reco["gap_neexplicat_ron"])} RON</span>'
            f'<small>GAP neexplicat ({_reco["procent_gap"]}%)</small>'
            f'</div>'
        )
        _nota_inconsistenta = ''
        _nota_principala = (
            f'Doar <strong>{_reco["procent_vizibil_in_seap"]}%</strong> din cheltuielile '
            f'primariei sunt vizibile public in SEAP pentru anul {_an_reco}. '
            f'Procentul ramas nu se regaseste nici in salariile estimate, nici in transferuri, '
            f'nici in contracte SEAP &mdash; este o diferenta calculata din surse publice oficiale.'
        )

    reco_html = f"""
  <section class="tp-reconciliation" aria-labelledby="reco-h">
    <h3 id="reco-h">&#x1F4CA; Reconciliere ANAF &#x2194; SEAP &mdash; {_an_reco}</h3>
    <div class="tp-reco-grid">
      <div class="tp-reco-cell tp-reco-total">
        <span>{_ro(_reco['total_anaf_ron'])} RON</span>
        <small>Cheltuieli totale ANAF {_an_reco}</small>
      </div>
      <div class="tp-reco-cell tp-reco-known">
        <span>~{_ro(_reco['salarii_estimate_ron'])} RON</span>
        <small>Salarii estimate (~45%)</small>
      </div>
      <div class="tp-reco-cell tp-reco-known">
        <span>~{_ro(_reco['transferuri_ron'])} RON</span>
        <small>Transferuri / subventii (~15%)</small>
      </div>
      <div class="tp-reco-cell tp-reco-visible">
        <span>{_ro(_reco['total_seap_ron'])} RON</span>
        {_seap_label}
      </div>
      {_gap_cell}
    </div>
    <p class="tp-reco-note">
      {_nota_principala}{_nota_inconsistenta}{_reco_disclaimer}
    </p>
    <p class="tp-reco-note" style="margin-top:.5rem;font-size:.82rem;background:#f1f5f9;border-left-color:#64748b">
      <strong>De ce difer&#259; de tabel:</strong> SEAP republic&#259; valoarea integral&#259; a
      unui contract la fiecare modificare (Rev.2 = act adi&#355;ional). Aceast&#259; sum&#259;
      elimin&#259; duplicatele canonic &mdash; grupare pe (titlu, firm&#259;), p&#259;strând
      revizia cu valoarea cea mai mare.
      Sunt <strong>{_reco['nr_contracte_unice']}</strong> contracte unice {_an_reco} dup&#259; deduplicare.
    </p>
  </section>"""

    html = f"""<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{seo_title} — {config['nume_entitate']} — {data_generare}</title>

<!-- SEO -->
<meta name="description" content="{seo_description}">
<meta name="keywords" content="transparență, Pantelimon, primărie, achiziții publice, SEAP, ANAF, monitorizare cetățenească, Ilfov, semnale de risc, raport">
<meta name="author" content="Inițiativă cetățenească independentă">
<link rel="canonical" href="https://transparenta-pantelimon.eu/raport_transparenta.html">

<!-- Open Graph (Facebook, LinkedIn) -->
<meta property="og:type" content="article">
<meta property="og:url" content="https://transparenta-pantelimon.eu/raport_transparenta.html">
<meta property="og:title" content="{seo_title}">
<meta property="og:description" content="{seo_description}">
<meta property="og:image" content="https://transparenta-pantelimon.eu/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ro_RO">
<meta property="og:site_name" content="Transparența Pantelimon">

<!-- Twitter -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{seo_title}">
<meta name="twitter:description" content="{seo_description}">
<meta name="twitter:image" content="https://transparenta-pantelimon.eu/og-image.png">
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#F4F6F9;color:#1A1A2E;margin:0;padding:0}}
  .wrap{{max-width:960px;margin:0 auto;padding:24px 16px 60px}}
  h1,h2,h3{{margin:0 0 8px}}
  table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;
         overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
  thead{{background:#00427A;color:#fff}}
  th{{padding:10px 12px;font-size:12px;text-align:left;text-transform:uppercase;letter-spacing:.5px}}
  @media (max-width:640px) {{
    html,body {{ max-width:100%; overflow-x:hidden; }}
    .wrap {{ padding:16px 10px 48px; }}
    table {{ display:block; max-width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .tp-reco-grid {{ grid-template-columns:1fr; }}
    .tp-flag {{ overflow:hidden; padding:12px !important; }}
    .tp-flag > div:first-child {{ flex-wrap:wrap; min-width:0; }}
    .tp-flag > div:first-child > span {{ overflow-wrap:anywhere; max-width:100%; }}
    .tp-flag .flag-arrow {{ margin-left:0 !important; }}
  }}

  /* ---- PRINT / PDF ---- */
  @media print {{
    body {{ background:#fff !important; font-size:11pt; }}
    .wrap {{ max-width:100%; padding:0; }}
    .no-print {{ display:none !important; }}
    .flag-detail {{ display:block !important; }}
    .flag-arrow {{ display:none !important; }}
    .firma-contracts-panel {{ display:none !important; }}
    [onmouseenter] {{ box-shadow:none !important; cursor:default !important; }}
    h2 {{ color:#00427A !important; page-break-after:avoid; }}
    h2, h3 {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
    table {{ page-break-inside:avoid; }}
    div[style*="border-left"] {{ page-break-inside:avoid;
      -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
    thead {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
    @page {{ margin:1.5cm; size:A4; }}
  }}

  /* ---- §4.1 RECONCILIERE WIDGET ---- */
  .tp-reconciliation {{
    margin: 1.5rem 0;
    padding: 1rem;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
  }}
  .tp-reconciliation h3 {{ margin: 0 0 .75rem; font-size: 1.05rem; color: #00427A; }}
  .tp-reco-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: .75rem;
    margin: 1rem 0;
  }}
  .tp-reco-cell {{
    padding: 1rem;
    border-radius: 8px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    text-align: center;
  }}
  .tp-reco-cell span {{
    display: block;
    font-size: 1.2rem;
    font-weight: 700;
    color: #111;
    line-height: 1.2;
    word-break: break-word;
  }}
  .tp-reco-cell small {{
    color: #6b7280;
    font-size: .78rem;
    display: block;
    margin-top: .25rem;
  }}
  .tp-reco-total  {{ border-color: #94a3b8; }}
  .tp-reco-known  {{ background: #f0fdf4; border-color: #bbf7d0; }}
  .tp-reco-visible{{ background: #dbeafe; border-color: #93c5fd; }}
  .tp-reco-gap    {{ background: #fee2e2; border-color: #fca5a5; }}
  .tp-reco-gap span {{ color: #b91c1c; }}
  .tp-reco-note {{
    font-size: .9rem;
    padding: .75rem 1rem;
    background: #fef9c3;
    border-left: 3px solid #ca8a04;
    border-radius: 4px;
    margin: 0;
    line-height: 1.5;
  }}
  /* Dark mode */
  [data-tp-theme="dark"] .tp-reconciliation {{
    background: #1e293b; border-color: #334155;
  }}
  [data-tp-theme="dark"] .tp-reco-cell {{
    background: #1e293b; border-color: #334155;
  }}
  [data-tp-theme="dark"] .tp-reco-cell span {{ color: #f1f5f9; }}
  [data-tp-theme="dark"] .tp-reco-cell small {{ color: #94a3b8; }}
  [data-tp-theme="dark"] .tp-reco-known  {{ background: #14532d; border-color: #166534; }}
  [data-tp-theme="dark"] .tp-reco-visible{{ background: #1e3a8a; border-color: #1d4ed8; }}
  [data-tp-theme="dark"] .tp-reco-gap    {{ background: #7f1d1d; border-color: #991b1b; }}
  [data-tp-theme="dark"] .tp-reco-gap span {{ color: #fca5a5; }}
  [data-tp-theme="dark"] .tp-reco-note   {{ background: #422006; border-left-color: #ca8a04; color: #fef3c7; }}
</style>
<link rel="alternate" type="application/atom+xml" title="Semnale noi — Transparența Pantelimon" href="https://transparenta-pantelimon.eu/feed.xml">
<script src="enhance.js" defer></script>
</head>
<body>
<div style="background:linear-gradient(135deg,#00427A,#0070C0);color:#fff;padding:24px 32px">
  <div style="max-width:960px;margin:0 auto">
    <div style="font-size:11px;opacity:.7;margin-bottom:8px">
      Monitorizare cetățenească · {config['judet']}
    </div>
    <h1 style="font-size:26px;font-weight:800;margin:0 0 6px">
      Raport Transparență Bugetară<br>
      <span style="color:#FF6B35">{config['nume_entitate']}</span>
    </h1>
    <p style="opacity:.85;margin:0">Generat automat la {data_generare} · CUI: {config['cui']}</p>
    <div style="margin-top:14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap" class="no-print">
      <a href="index.html"
         style="background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.4);
                padding:9px 18px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;
                display:inline-flex;align-items:center;gap:6px">
        ← Pagina Principală
      </a>
      <button onclick="printRaport()"
              style="background:#FF6B35;color:#00427A;border:none;padding:9px 20px;
                     border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;
                     display:inline-flex;align-items:center;gap:8px">
        🖨️ Salvează ca PDF / Tipărește
      </button>
      <span style="font-size:11px;opacity:.65">
        → în dialogul de tipărire alege „Salvare ca PDF"
      </span>
    </div>
    <div style="display:flex;gap:24px;margin-top:16px;flex-wrap:wrap">
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;text-align:center">
        <div style="font-size:22px;font-weight:800;color:#{"C0392B" if flags else "27AE60"}">{len(flags)}</div>
        <div style="font-size:11px;opacity:.8">Semnale automate</div>
      </div>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;text-align:center">
        <div style="font-size:22px;font-weight:800;color:{"#FF6B35" if flags_noi else "#27AE60"}">{len(flags_noi)}</div>
        <div style="font-size:11px;opacity:.8">Semnale noi (față de ultima rulare)</div>
      </div>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;text-align:center">
        <div style="font-size:22px;font-weight:800">{n_contracte_semnale}</div>
        <div style="font-size:11px;opacity:.8">Contracte unice cu semnale</div>
      </div>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;text-align:center">
        <div style="font-size:22px;font-weight:800">{len(contracte)}</div>
        <div style="font-size:11px;opacity:.8">Contracte analizate</div>
      </div>
      <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:10px 16px;text-align:center">
        <div style="font-size:22px;font-weight:800">{_fmt_ron(total_val)}</div>
        <div style="font-size:11px;opacity:.8">Valoare totală contracte</div>
      </div>
    </div>
  </div>
</div>

<div class="wrap">

  <div role="note" style="margin:24px 0 18px;background:#EBF5FB;border-left:4px solid #0070C0;
       border-radius:0 8px 8px 0;padding:14px 18px;color:#1F3B53;font-size:13px;line-height:1.6">
    <strong>Indicatori, nu verdicte.</strong> Semnalele sunt euristice și trebuie verificate în
    documentele-sursă. Același contract poate genera mai multe semnale, deci sumele asociate
    se pot suprapune și nu reprezintă prejudicii. Pragurile pentru achiziția directă sunt
    <strong>{prag_servicii_fmt} RON</strong>
    fără TVA pentru produse/servicii și
    <strong>{prag_lucrari_fmt} RON</strong>
    fără TVA pentru lucrări.
    <a href="despre.html#metodologie" style="color:#005A9C;font-weight:700">Metodologie</a> ·
    <a href="{PRAGURI_LEGALE_SURSA}" target="_blank" rel="noopener noreferrer"
       style="color:#005A9C;font-weight:700">Legea 98/2016</a>
  </div>

  <!-- BUGET -->
  <h2 style="color:#00427A;margin:28px 0 16px">📊 Date Bugetare (ANAF/MF)</h2>
  {budget_html if budget_html else '<p style="color:#777;font-size:13px">Date buget indisponibile.</p>'}

  <!-- RED FLAGS -->
  <h2 style="color:#00427A;margin:28px 0 8px">🚩 Semnale de risc automate ({len(flags)})</h2>
  <p style="font-size:13px;color:#777;margin:0 0 16px">
    {sum(1 for f in flags if f['severitate']=='CRITIC')} CRITIC · {sum(1 for f in flags if f['severitate']=='MAJOR')} MAJOR · {sum(1 for f in flags if f['severitate']=='MEDIU')} MEDIU</p>
  {nota_demo_msg}

  <!-- ANALIZĂ PE CATEGORIE -->
  <details style="margin-bottom:20px;background:#F4F6F8;border-radius:10px;padding:14px 18px;border:1px solid #DDE1E7">
    <summary style="cursor:pointer;font-size:14px;font-weight:700;color:#00427A;list-style:none;display:flex;align-items:center;gap:8px">
      <span style="font-size:18px">📊</span>
      Analiză pe categorii de semnale
      <span style="margin-left:auto;font-size:12px;color:#999;font-weight:400">▼ extinde</span>
    </summary>
    <p style="font-size:12px;color:#777;margin:10px 0 14px">
      Apasă pe o categorie pentru statistici descriptive. Sumele asociate flagurilor pot
      include același contract de mai multe ori și nu reprezintă prejudicii sau cheltuieli nelegale.
    </p>
    {analiza_per_tip_html}
  </details>

  {flags_html if flags_html else '<div style="background:#E8F5E9;border-left:4px solid #27AE60;padding:14px 18px;border-radius:0 8px 8px 0"><span style="color:#27AE60;font-weight:700">✅ Niciun semnal automat detectat în această perioadă.</span></div>'}

  <!-- HCL STATISTICI -->
  <h2 style="color:#00427A;margin:28px 0 8px">📋 Hotărâri Consiliu Local</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px">
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #0070C0;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#0070C0">{config.get('_hcl_total',0)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">HCL Total analizate</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #27AE60;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#27AE60">{config.get('_hcl_ordinare',0)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Ședințe ordinare</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid {'#C0392B' if config.get('_hcl_pct',0)>25 else '#E67E22'};box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:{'#C0392B' if config.get('_hcl_pct',0)>25 else '#E67E22'}">{config.get('_hcl_extraordinare',0)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Extraordinare cu convocare de îndată ({config.get('_hcl_pct',0)}%)</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #8E44AD;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:12px;font-weight:700;color:#8E44AD">{'✅ OCR activ' if config.get('_hcl_ocr') else '⚠️ Doar metadata'}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase;margin-top:4px">Mod analiză HCL</div>
    </div>
  </div>

  <!-- STATISTICI ACHIZITII -->
  <h2 style="color:#00427A;margin:28px 0 8px">📊 Statistici Achiziții</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px">
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #0070C0;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#0070C0">{len(contracte)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Contracte totale</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #C0392B;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#C0392B">{len(directe)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Cumpărare directă / negociere</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #E67E22;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#E67E22">{len(unic_ofertant)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Un singur ofertant</div>
    </div>
    <div style="background:#fff;border-radius:10px;padding:16px;border-top:4px solid #27AE60;box-shadow:0 1px 4px rgba(0,0,0,.08)">
      <div style="font-size:28px;font-weight:800;color:#27AE60">{_fmt_ron(total_val)}</div>
      <div style="font-size:11px;color:#777;text-transform:uppercase">Valoare totală</div>
    </div>
  </div>

  <!-- §4.1 RECONCILIERE WIDGET -->
  {reco_html}

  <!-- LISTA CONTRACTE -->
  <h2 style="color:#00427A;margin:28px 0 8px">📄 Lista contracte analizate (primele 20)</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Titlu contract</th><th>Valoare</th><th>Tip procedură</th>
      <th>Ofertanți</th><th>Câștigător</th><th>Data</th>
    </tr></thead>
    <tbody>{contracte_html if contracte_html else '<tr><td colspan="6" style="text-align:center;padding:20px;color:#777">Nu există contracte de afișat</td></tr>'}</tbody>
  </table>
  </div>

</div>

<script id="contracte-data" type="application/json">{contracte_json_embed}</script>
<script id="risc-firma-data" type="application/json">{risc_firma_json}</script>

<style>
/* ── Profil firmă panou lateral ──────────────────────────────────── */
#tp-firma-overlay {{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9000;
  backdrop-filter:blur(2px);
}}
#tp-firma-panel {{
  position:fixed;top:0;right:0;width:min(520px,100vw);height:100vh;
  background:#fff;box-shadow:-4px 0 24px rgba(0,0,0,.18);z-index:9001;
  overflow-y:auto;transform:translateX(100%);
  transition:transform .25s cubic-bezier(.4,0,.2,1);
}}
#tp-firma-panel.open {{ transform:translateX(0); }}
.tp-risc-badge {{
  display:inline-block;padding:2px 8px;border-radius:10px;
  font-size:11px;font-weight:700;color:#fff;
}}
</style>

<!-- PANOU PROFIL FIRMĂ -->
<div id="tp-firma-overlay" onclick="closeFirmaPanel()"></div>
<div id="tp-firma-panel">
  <div style="background:#00427A;color:#fff;padding:16px 20px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:1">
    <span style="font-size:20px">🏢</span>
    <div style="flex:1">
      <div id="tp-fp-name" style="font-size:15px;font-weight:700">—</div>
      <div id="tp-fp-cui"  style="font-size:11px;opacity:.7">CUI: —</div>
    </div>
    <button onclick="closeFirmaPanel()"
            style="background:rgba(255,255,255,.15);border:none;color:#fff;
                   padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px">✕</button>
  </div>
  <div id="tp-fp-body" style="padding:16px 20px;font-size:13px"></div>
</div>
<script>
// ── Date contracte ──────────────────────────────────────────────
var _contracteData = null;
function _getContracte() {{
  if (!_contracteData) {{
    try {{
      _contracteData = JSON.parse(document.getElementById('contracte-data').textContent);
    }} catch(e) {{ _contracteData = []; }}
  }}
  return _contracteData;
}}

// ── Export PDF / Print ──────────────────────────────────────────
function printRaport() {{
  // Deschidem toate flag-urile înainte de print
  document.querySelectorAll('.flag-detail').forEach(function(el) {{
    el.style.display = 'block';
  }});
  document.querySelectorAll('.flag-arrow').forEach(function(el) {{
    el.style.display = 'none';
  }});
  // Închidem toate panourile de contracte (prea verbose pentru PDF)
  document.querySelectorAll('.firma-contracts-panel').forEach(function(el) {{
    el.style.display = 'none';
  }});
  window.print();
}}

// ── Toggle detalii flag ─────────────────────────────────────────
function toggleFlag(el) {{
  var detail = el.querySelector('.flag-detail');
  var arrow = el.querySelector('.flag-arrow');
  if (detail.style.display === 'none') {{
    detail.style.display = 'block';
    if (arrow) arrow.textContent = '▲ ascunde';
  }} else {{
    detail.style.display = 'none';
    if (arrow) arrow.textContent = '▼ detalii';
  }}
}}

// ── Toate contractele unei firme ────────────────────────────────
function showFirmaContracts(firma, evt) {{
  evt.stopPropagation();
  var flagDiv = evt.target.closest('[onclick="toggleFlag(this)"]');
  var existing = flagDiv.querySelector('.firma-contracts-panel');
  if (existing) {{
    existing.style.display = existing.style.display === 'none' ? 'block' : 'none';
    return;
  }}

  var contracte = _getContracte();
  var _nfc = _nzFirma(firma);
  // Exporturile trimestriale data.gov.ro republica acelasi contract cu id-uri
  // diferite. Fara dedup, DAV GARDEN aparea cu „3 contracte · 10.39 mil. RON",
  // desi doua randuri erau acelasi contract de 4.62 mil. (real: 2 / 5.77 mil.).
  var _vazuteC = {{}};
  var matches = contracte.filter(function(c) {{
    var cl = _nzFirma(c.firma || '');
    if (!cl || !_nfc) return false;
    if (!(cl === _nfc || cl.indexOf(_nfc) !== -1 || _nfc.indexOf(cl) !== -1)) return false;
    var k = cl + '|' + (c.data || '') + '|' + Math.round(c.valoare || 0) + '|' + String(c.titlu || '').slice(0, 60);
    if (_vazuteC[k]) return false;
    _vazuteC[k] = 1;
    return true;
  }});
  matches.sort(function(a, b) {{ return b.data.localeCompare(a.data); }});

  var totalVal = matches.reduce(function(s, c) {{ return s + (c.valoare || 0); }}, 0);
  var totalFmt = totalVal >= 1000000
    ? (totalVal / 1000000).toFixed(2) + ' mil. RON'
    : Math.round(totalVal / 1000) + ' K RON';

  function fmtVal(v) {{
    if (!v) return '–';
    return v >= 1000000
      ? (v/1000000).toFixed(2) + ' mil.'
      : Math.round(v/1000) + ' K RON';
  }}

  // Extrage numărul SEAP din câmpul id (ex: "contract-2025-79964" → "79964")
  function seapNr(id) {{
    if (!id) return '';
    var parts = id.split('-');
    return parts[parts.length - 1];
  }}

  // Construiește URL SEAP din id
  function seapUrl(id) {{
    if (!id) return '#';
    var nr = seapNr(id);
    if (!nr) return '#';
    if (id.indexOf('achizitie-directa') !== -1)
      return 'https://e-licitatie.ro/pub/direct-acquisition/' + nr;
    return 'https://e-licitatie.ro/pub/contract-notice/' + nr;
  }}

  var rows = matches.map(function(c, i) {{
    var bg = i % 2 === 0 ? '#fff' : '#f8f9fa';
    var ofColor = c.ofertanti === 1 ? '#C0392B' : '#27AE60';
    var nr = seapNr(c.id);
    var url = seapUrl(c.id);
    var seapCell = nr
      ? '<a href="' + url + '" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" '
        + 'style="color:#0070C0;font-weight:700;text-decoration:none;white-space:nowrap" '
        + 'title="Deschide în SEAP">' + nr + ' ↗</a>'
      : '–';
    var ofCell = '<span style="color:' + ofColor + ';font-weight:700">' + (c.ofertanti || '?') + '</span>';
    if (c.ofertanti === 2) {{
      ofCell += ' <a href="' + url + '" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" '
        + 'style="font-size:10px;color:#0070C0;text-decoration:none" '
        + 'title="Cel de-al doilea ofertant — vizualizează în SEAP">→ SEAP</a>';
    }}
    return '<tr style="background:' + bg + '">'
      + '<td style="padding:6px 10px;font-size:12px;white-space:nowrap">' + (c.data || '–') + '</td>'
      + '<td style="padding:6px 10px;font-size:12px;max-width:260px">' + (c.titlu || '').substring(0, 70) + '</td>'
      + '<td style="padding:6px 10px;font-size:12px;font-weight:700;white-space:nowrap">' + fmtVal(c.valoare) + '</td>'
      + '<td style="padding:6px 10px;font-size:12px">' + (c.tip || '–') + '</td>'
      + '<td style="padding:6px 10px;font-size:12px;text-align:center">' + ofCell + '</td>'
      + '<td style="padding:6px 10px;font-size:12px;text-align:center">' + seapCell + '</td>'
      + '</tr>';
  }}).join('');

  var panel = document.createElement('div');
  panel.className = 'firma-contracts-panel';
  panel.style.cssText = 'margin-top:16px;';
  panel.innerHTML =
    '<div style="background:#EBF5FB;border-radius:8px;padding:14px 16px;border:1px solid #AED6F1">'
    + '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">'
    + '<strong style="color:#0070C0;font-size:14px">📊 Contracte cu Primăria Pantelimon – ' + firma + '</strong>'
    + '<span style="font-size:12px;color:#555;background:#fff;padding:4px 10px;border-radius:12px;border:1px solid #AED6F1">'
    + matches.length + ' contracte · Total: ' + totalFmt
    + '</span></div>'
    + (matches.length === 0
      ? '<p style="text-align:center;color:#888;font-size:13px">Niciun contract găsit în datele descărcate.</p>'
      : '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
        + '<thead><tr style="background:#0070C0;color:#fff">'
        + '<th style="padding:6px 10px;font-size:11px;text-align:left">Data</th>'
        + '<th style="padding:6px 10px;font-size:11px;text-align:left">Obiect contract</th>'
        + '<th style="padding:6px 10px;font-size:11px;text-align:left">Valoare</th>'
        + '<th style="padding:6px 10px;font-size:11px;text-align:left">Tip procedură</th>'
        + '<th style="padding:6px 10px;font-size:11px;text-align:center">Ofertanți</th>'
        + '<th style="padding:6px 10px;font-size:11px;text-align:center">Nr. SEAP</th>'
        + '</tr></thead><tbody>' + rows + '</tbody></table></div>')
    + '<div style="margin-top:10px;font-size:11px;color:#777">Date: data.gov.ro · Perioadă analizată: ultimele 12 luni'
    + ' · <em>Al doilea ofertant — apasă „→ SEAP" pentru detalii complete</em></div>'
    + '</div>';

  flagDiv.appendChild(panel);
}}

// ── Profil complet firmă ─────────────────────────────────────────────────────
function _esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
  }});
}}
// Normalizare pentru potrivirea numelor de firme (SEAP livrează nume „murdare":
// spații duble, diacritice, „&" vs „and", sufixe SRL/S.A. inconsistente).
function _nzFirma(s) {{
  var t = String(s == null ? '' : s).toLowerCase();
  if (t.normalize) t = t.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
  return t.replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').replace(/\\s+/g, ' ').trim();
}}
var _riscData = null;
function _getRisc() {{
  if (!_riscData) {{
    try {{ _riscData = JSON.parse(document.getElementById('risc-firma-data').textContent); }}
    catch(e) {{ _riscData = {{}}; }}
  }}
  return _riscData;
}}

// Trimite utilizatorul in lista principala, filtrata pe firma respectiva.
function _filtreazaFurnizor(firma) {{
  var sel = document.getElementById('tp-supplier');
  if (sel) {{
    var optiune = Array.from(sel.options).find(function(o) {{ return o.value === firma; }});
    if (optiune) {{
      sel.value = firma;
      sel.dispatchEvent(new Event('change', {{bubbles: true}}));
      var toolbar = document.querySelector('.tp-toolbar');
      if (toolbar) toolbar.scrollIntoView({{behavior: 'smooth', block: 'start'}});
      return;
    }}
  }}
  // fallback fara enhance.js: cautare prin hash
  location.hash = 'supplier=' + encodeURIComponent(firma);
  location.reload();
}}

function openFirmaPanel(firma, evt) {{
  if (evt) evt.stopPropagation();
  var rd   = _getRisc()[firma] || {{}};
  var _nf  = _nzFirma(firma);
  // Exporturile trimestriale data.gov.ro repetă același contract în mai multe
  // trimestre cu id-uri diferite. Fără deduplicare, valoarea firmei se dubla.
  var _vazute = {{}};
  var contracte = _getContracte().filter(function(c) {{
    var cn = _nzFirma(c.firma||'');
    if (!cn || !_nf) return false;
    if (!(cn === _nf || cn.indexOf(_nf) !== -1 || _nf.indexOf(cn) !== -1)) return false;
    var k = cn + '|' + (c.data||'') + '|' + Math.round(c.valoare||0) + '|' + String(c.titlu||'').slice(0,60);
    if (_vazute[k]) return false;
    _vazute[k] = 1;
    return true;
  }});
  var cui  = rd.cui || '';
  var scor = rd.scor || 0;
  var scorColor = scor >= 50 ? '#C0392B' : scor >= 20 ? '#E67E22' : '#F39C12';
  var scorLabel = scor >= 50 ? 'CRITIC' : scor >= 20 ? 'MAJOR' : 'MEDIU';

  document.getElementById('tp-fp-name').textContent = firma;
  document.getElementById('tp-fp-cui').textContent  = 'CUI: ' + (cui || '—');

  var totalVal = contracte.reduce(function(s,c){{return s+(c.valoare||0);}},0);
  function fmtV(v) {{ return v>=1000000?(v/1000000).toFixed(2)+' mil. RON':Math.round(v/1000)+'K RON'; }}

  // Lista din panou e plafonata server-side; badge-urile numara toate semnalele.
  // Expunem diferenta explicit, altfel „29 CRITIC/MAJOR/MEDIU" langa o lista de 20
  // arata ca o contradictie (vezi AUDIT 01.07.2026).
  var _nTotal   = rd.n_total || (rd.flags||[]).length;
  var _nAscunse = Math.max(0, _nTotal - (rd.flags||[]).length);

  var flagsHtml = '';
  (rd.flags||[]).forEach(function(f) {{
    var fColor = f.severitate==='CRITIC'?'#C0392B':f.severitate==='MAJOR'?'#E67E22':'#F39C12';
    var anchor = f.anchor || '';
    // Rândurile sunt acum <a> reale spre neregula detaliată din lista principală.
    // Înainte erau <div>-uri fără handler: arătau ca butoane, dar nu făceau nimic.
    var openTag = anchor
      ? '<a href="#'+anchor+'" onclick="closeFirmaPanel()" '
        + 'style="display:block;text-decoration:none;color:inherit;cursor:pointer;'
      : '<div style="';
    var closeTag = anchor ? '</a>' : '</div>';
    flagsHtml += openTag
      + 'border-left:3px solid '+fColor+';padding:8px 10px;margin-bottom:6px;background:#fafafa;border-radius:0 6px 6px 0">'
      + '<span style="font-size:10px;font-weight:700;color:'+fColor+'">'+f.severitate+'</span>'
      + ' <span style="font-size:12px;font-weight:600">'+_esc(f.titlu)+'</span>'
      + (f.descriere
          ? '<div style="font-size:11.5px;color:#444;margin-top:4px;line-height:1.45">'+_esc(f.descriere)+'</div>'
          : '')
      + '<div style="font-size:11px;color:#777;margin-top:4px">'
        + fmtV(f.valoare||0) + ' · ' + (f.data||'—')
        + (f.contract_id ? ' · <span style="font-family:monospace">'+_esc(f.contract_id)+'</span>' : '')
        + (anchor ? ' · <span style="color:#0070C0;font-weight:600">vezi neregula →</span>' : '')
      + '</div>'
      + closeTag;
  }});

  var contracteHtml = '';
  contracte.slice(0,10).forEach(function(c,i) {{
    var bg = i%2===0?'#fff':'#f8f9fa';
    contracteHtml += '<tr style="background:'+bg+'">'
      + '<td style="padding:5px 8px;font-size:11px;white-space:nowrap">'+c.data+'</td>'
      + '<td style="padding:5px 8px;font-size:11px;max-width:200px">'+c.titlu.substring(0,50)+'</td>'
      + '<td style="padding:5px 8px;font-size:11px;font-weight:700;white-space:nowrap">'+fmtV(c.valoare)+'</td>'
      + '</tr>';
  }});

  var termeneUrl = cui ? 'https://termene.ro/firma/'+cui.replace(/^RO/i,'') : '#';
  var onrcUrl    = cui ? 'https://www.recom.ro/companies_ro_company_detail.aspx?id='+cui.replace(/^RO/i,'') : '#';
  // SEAP: linkul generic /list/0/0 deschidea o pagină goală — pentru utilizator
  // arăta ca un buton stricat. Mergem direct la anunțul contractului dacă avem
  // un contract_id numeric; altfel la căutarea SEAP după numele firmei.
  var seapId = '';
  (rd.flags||[]).some(function(f) {{
    var m = String(f.contract_id||'').match(/(\\d{{4,}})\\s*$/);
    if (m) {{ seapId = m[1]; return true; }}
    return false;
  }});
  var seapUrl = seapId
    ? 'https://e-licitatie.ro/pub/notices/da-direct-acquisition/view/' + seapId
    : 'https://e-licitatie.ro/pub/notices/contract-notices/list/0/0?text=' + encodeURIComponent(firma);
  var seapLabel = seapId ? '📋 Anunț SEAP →' : '📋 Caută în SEAP →';

  document.getElementById('tp-fp-body').innerHTML =
    '<div style="background:#FFF3E0;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:12px">'
    + '<div style="text-align:center">'
    + '<div style="font-size:32px;font-weight:800;color:'+scorColor+'">'+scor+'</div>'
    + '<div style="font-size:10px;font-weight:700;color:'+scorColor+'">SCOR RISC</div>'
    + '</div>'
    + '<div style="flex:1">'
    + '<span class="tp-risc-badge" style="background:#C0392B">'+( rd.n_critic||0)+' CRITIC</span> '
    + '<span class="tp-risc-badge" style="background:#E67E22">'+( rd.n_major||0)+' MAJOR</span> '
    + '<span class="tp-risc-badge" style="background:#F39C12">'+( rd.n_mediu||0)+' MEDIU</span>'
    // Valoarea afișată este suma contractelor DISTINCTE ale firmei cu Primăria.
    // Înainte se afișa rd.valoare_totala = suma valorilor tuturor flag-urilor,
    // în care același contract era numărat de 3-4 ori (o dată per semnal) —
    // rezulta o cifră de câteva ori mai mare decât realitatea.
    + '<div style="font-size:11px;color:#555;margin-top:6px">Valoare contracte cu Primăria: <strong>'
      + (contracte.length ? fmtV(totalVal) : '—')
      + '</strong>' + (contracte.length ? ' <span style="color:#888">('+contracte.length+' contracte)</span>' : '')
    + '</div>'
    + '<div style="font-size:10.5px;color:#888;margin-top:2px" '
      + 'title="Suma valorilor tuturor semnalelor. Un contract poate genera mai multe semnale, deci aceeași sumă poate fi numărată de mai multe ori.">'
      + 'Sumă cumulată a semnalelor: '+fmtV(rd.valoare_totala||0)+' <span style="cursor:help">ⓘ</span></div>'
    + '</div></div>'

    + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">'
    + '<a href="'+termeneUrl+'" target="_blank" rel="noopener noreferrer" style="background:#0070C0;color:#fff;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:600">🔍 termene.ro →</a>'
    + '<a href="'+onrcUrl+'" target="_blank" rel="noopener noreferrer" style="background:#1E8449;color:#fff;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:600">🏛 ONRC →</a>'
    + '<a href="'+seapUrl+'" target="_blank" rel="noopener noreferrer" style="background:#8E44AD;color:#fff;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:600">'+seapLabel+'</a>'
    + '</div>'

    + (rd.onrc && rd.onrc.reprezentanti && rd.onrc.reprezentanti.length > 0
      ? (function() {{
          var rows = rd.onrc.reprezentanti.map(function(r) {{
            return '<tr><td style="padding:5px 8px;font-size:12px;font-weight:600">' + r.calitate + '</td>'
              + '<td style="padding:5px 8px;font-size:12px"><strong>' + r.nume + '</strong>'
              + (r.localitate ? ' <span style="color:#888;font-size:11px">(' + r.localitate + ')</span>' : '')
              + '</td></tr>';
          }}).join('');
          var cod = rd.onrc.cod_inmatriculare || '';
          var onrcLink = cod
            ? '<a href="https://www.recom.ro/companies_ro_company_detail.aspx?id='+encodeURIComponent(cod)+'" target="_blank" rel="noopener noreferrer" style="color:#0070C0;font-size:11px">recom.ro →</a>'
            : '';
          return '<h4 style="margin:16px 0 8px;font-size:13px;color:#1E8449">🏛 Reprezentanți legali (ONRC)</h4>'
            + '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
            + '<thead><tr style="background:#1E8449;color:#fff"><th style="padding:5px 8px;font-size:11px">Calitate</th><th style="padding:5px 8px;font-size:11px">Nume</th></tr></thead>'
            + '<tbody>' + rows + '</tbody></table></div>'
            + '<div style="font-size:11px;color:#777;margin-top:4px">Sursă: ONRC data.gov.ro (date oficiale) · ' + onrcLink + '</div>';
        }})()
      : (function() {{
          var op = rd.openapi || {{}};
          var hasOp = op.numar_reg_com || op.stare;
          if (hasOp) {{
            var cuiClean = cui.replace(/^RO/i, '');
            return '<h4 style="margin:16px 0 8px;font-size:13px;color:#1E8449">🏛 Date firmă (ANAF/ONRC)</h4>'
              + '<div style="background:#F4F6F8;border-radius:8px;padding:12px 14px;font-size:12px">'
              + (op.stare ? '<div style="margin-bottom:4px">Stare: <strong' + (op.radiata ? ' style="color:#C0392B"' : '') + '>' + op.stare + (op.radiata ? ' ⚠️' : '') + '</strong></div>' : '')
              + (op.numar_reg_com ? '<div style="margin-bottom:4px">Nr. reg. com.: <strong>' + op.numar_reg_com + '</strong></div>' : '')
              + (op.ultima_declaratie ? '<div style="margin-bottom:8px;color:#777">Ultima declarație fiscală: ' + op.ultima_declaratie + '</div>' : '')
              + '<div style="margin-top:6px">'
              + '<a href="https://termene.ro/firma/' + cuiClean + '" target="_blank" rel="noopener noreferrer" style="color:#0070C0;font-weight:600;font-size:12px">📋 Administratori pe termene.ro →</a>'
              + ' &nbsp;·&nbsp; '
              + '<a href="https://www.recom.ro/companies_ro_company_detail.aspx?id=' + cuiClean + '" target="_blank" rel="noopener noreferrer" style="color:#1E8449;font-size:12px">🏛 recom.ro →</a>'
              + '</div>'
              + '<div style="font-size:10px;color:#aaa;margin-top:6px">Date ONRC complete: disponibile după procesare locală</div>'
              + '</div>';
          }} else {{
            return '<div style="margin:12px 0;padding:8px 12px;background:#F4F6F8;border-radius:6px;font-size:11px;color:#777">'
              + '🏛 Reprezentanți legali: <a href="' + onrcUrl + '" target="_blank" rel="noopener noreferrer" style="color:#0070C0">verifică pe recom.ro →</a>'
              + ' sau <a href="https://termene.ro/firma/' + cui.replace(/^RO/i,'') + '" target="_blank" rel="noopener noreferrer" style="color:#0070C0">termene.ro →</a>'
              + '</div>';
          }}
        }})())

    + (flagsHtml
      ? '<h4 style="margin:16px 0 8px;font-size:13px;color:#C0392B">🚩 Semnale de risc ('+_nTotal+')</h4>'
        + '<div style="font-size:11px;color:#777;margin:-4px 0 8px">Apasă pe un semnal pentru a vedea analiza completă în raport.</div>'
        + flagsHtml
        + (_nAscunse > 0
            ? '<div style="font-size:11.5px;color:#555;padding:8px 10px;background:#F4F6F8;border-radius:6px">'
              + 'Încă <strong>'+_nAscunse+'</strong> semnale pentru această firmă nu încap în panou. '
              + '<a href="#" onclick="closeFirmaPanel();_filtreazaFurnizor('+JSON.stringify(firma).replace(/"/g,'&quot;')+');return false;" style="color:#0070C0;font-weight:600">Vezi toate în raport →</a>'
              + '</div>'
            : '')
      : '')

    + (contracteHtml
      ? '<h4 style="margin:16px 0 8px;font-size:13px;color:#00427A">📄 Contracte cu Primăria</h4>'
        + '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
        + '<thead><tr style="background:#00427A;color:#fff"><th style="padding:5px 8px;font-size:11px">Data</th><th style="padding:5px 8px;font-size:11px">Obiect</th><th style="padding:5px 8px;font-size:11px">Valoare</th></tr></thead>'
        + '<tbody>' + contracteHtml + '</tbody></table></div>'
      : '')

    + '<div style="margin-top:16px;padding:10px;background:#F4F6F8;border-radius:6px;font-size:11px;color:#777">'
    + 'Date: ANAF · SEAP (data.gov.ro) · openapi.ro · ONRC data.gov.ro · Surse publice oficiale.<br>'
    + 'Asociați/acționari: verifică manual la ONRC (recom.ro) — date actualizate lunar.'
    + '</div>';

  document.getElementById('tp-firma-overlay').style.display = 'block';
  document.getElementById('tp-firma-panel').classList.add('open');
}}

function closeFirmaPanel() {{
  document.getElementById('tp-firma-overlay').style.display = 'none';
  document.getElementById('tp-firma-panel').classList.remove('open');
}}

// Keyboard ESC closes panel
document.addEventListener('keydown', function(e) {{ if (e.key==='Escape') closeFirmaPanel(); }});
</script>
<footer style="background:#00427A;color:rgba(255,255,255,.7);text-align:center;padding:16px;font-size:12px;margin-top:40px">
  <p>Surse date: <a href="https://transparenta.eu/entities/{config['cui']}#achizitii" target="_blank" rel="noopener noreferrer" style="color:#FF6B35">transparenta.eu</a> (ANAF/MF) &nbsp;·&nbsp;
     <a href="https://www.e-licitatie.ro/pub" target="_blank" rel="noopener noreferrer" style="color:#FF6B35">e-licitatie.ro (SEAP)</a> &nbsp;·&nbsp;
     <a href="https://www.primariapantelimon.ro" target="_blank" rel="noopener noreferrer" style="color:#FF6B35">primariapantelimon.ro</a></p>
  <p style="margin-top:6px;font-size:11px;opacity:.7">
    Raport generat automat de <strong>monitor_pantelimon.py</strong> &nbsp;·&nbsp;
    Inițiativă cetățenească independentă &nbsp;·&nbsp;
    Datele sunt extrase exclusiv din surse publice oficiale.
  </p>
<script type="application/json" id="tp-data">{raport_json_embedded}</script>
</footer>
<script data-goatcounter="https://transparenta-pantelimon.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
</body>
</html>"""
    return html


# ==============================================================================
# 6. FEED ATOM
# ==============================================================================

def genereaza_contracte_csv(contracte_export: list) -> str:
    """Genereaza continutul CSV pentru contractele exportate (aceleasi campuri ca contracte.json).

    Args:
        contracte_export: lista de dictionare cu chei id, titlu, valoare, data, tip, firma, cui, ofertanti

    Returns:
        String UTF-8 cu headerul si randurile CSV (separator virgula, quoting automat).
    """
    import csv
    import io

    FIELDNAMES = ["id", "titlu", "valoare", "data", "tip", "firma", "cui", "ofertanti"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for row in contracte_export:
        writer.writerow({k: (row.get(k, "") if row.get(k) is not None else "") for k in FIELDNAMES})
    return buf.getvalue()


def genereaza_feed_atom(nereguli: list, data_generare: datetime) -> str:
    """Generează feed Atom cu cele mai noi N=20 semnale automate."""
    import html as html_mod
    from datetime import timezone

    BASE = "https://transparenta-pantelimon.eu"
    if data_generare.tzinfo is None:
        updated = data_generare.replace(tzinfo=timezone.utc).isoformat()
    else:
        updated = data_generare.astimezone(timezone.utc).isoformat()

    sev_order = {"CRITIC": 0, "MAJOR": 1, "MEDIU": 2}
    sorted_nereguli = sorted(
        nereguli,
        key=lambda n: (sev_order.get(n.get("severitate", "MEDIU"), 99),
                       -float(n.get("valoare", 0) or 0))
    )[:20]

    entries = []
    for i, n in enumerate(sorted_nereguli, 1):
        titlu = html_mod.escape(str(n.get("titlu", "Semnal")))
        sev = html_mod.escape(str(n.get("severitate", "MEDIU")))
        furnizor = html_mod.escape(str(n.get("furnizor", "") or ""))
        try:
            valoare = float(n.get("valoare", 0) or 0)
        except (TypeError, ValueError):
            valoare = 0.0
        # Trunchiem ÎNAINTE de escape — altfel tăiem o entitate (&quot;) în jumătate → XML invalid
        descriere = html_mod.escape(str(n.get("descriere", "") or "")[:500])
        data_neregula = html_mod.escape(str(n.get("data", "") or ""))
        url = f"{BASE}/raport_transparenta.html#nereguli-{i}"
        entry_id = f"{BASE}/raport_transparenta.html#nereguli-{i}-{updated}"

        summary_html = (
            f"&lt;p&gt;&lt;strong&gt;Furnizor:&lt;/strong&gt; {furnizor}"
            f"&lt;br/&gt;&lt;strong&gt;Sumă:&lt;/strong&gt; {valoare:,.0f} RON"
            f"&lt;br/&gt;&lt;strong&gt;Dată:&lt;/strong&gt; {data_neregula}"
            f"&lt;/p&gt;&lt;p&gt;{descriere}&lt;/p&gt;"
        )

        entries.append(
            "  <entry>\n"
            f"    <title>[{sev}] {titlu}</title>\n"
            f'    <link href="{url}"/>\n'
            f"    <id>{entry_id}</id>\n"
            f"    <updated>{updated}</updated>\n"
            f'    <summary type="html">{summary_html}</summary>\n'
            "  </entry>"
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        '  <title>Transparența Pantelimon — Semnale de risc automate</title>\n'
        '  <subtitle>Monitorizare cetățenească automată a achizițiilor publice</subtitle>\n'
        f'  <link href="{BASE}/feed.xml" rel="self"/>\n'
        f'  <link href="{BASE}/raport_transparenta.html"/>\n'
        f"  <updated>{updated}</updated>\n"
        f"  <id>{BASE}/feed.xml</id>\n"
        "  <author><name>Inițiativă cetățenească independentă</name></author>\n"
        + "\n".join(entries) + "\n"
        "</feed>\n"
    )
    return feed


# ==============================================================================
# 7. TRIMITERE EMAIL ALERTĂ
# ==============================================================================

def trimite_email_alerta(flags_noi: list, raport_html: str, config: dict):
    """Trimite email de alertă dacă există red flags noi."""
    if not config.get("email_from") or not config.get("email_to"):
        print("  [Email] Emailul nu e configurat — se sare.")
        return

    subiect = f"🚩 {len(flags_noi)} semnale noi — Transparență Pantelimon {datetime.now().strftime('%d.%m.%Y')}"

    flags_text = "\n".join([
        f"[{f['severitate']}] {f['titlu']}\n  → {f['descriere'][:200]}"
        for f in flags_noi[:5]
    ])

    body_text = f"""
Monitor Transparență Bugetară — Pantelimon
==========================================

{len(flags_noi)} semnale automate noi față de ultima rulare:

{flags_text}

Raport complet: https://transparenta-pantelimon.eu/raport_transparenta.html

---
Inițiativă cetățenească independentă · Date din surse publice oficiale.
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subiect
    msg["From"] = config["email_from"]
    msg["To"] = config["email_to"]
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(raport_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(config["email_smtp"], config["email_port"]) as server:
            server.starttls()
            server.login(config["email_from"], config["email_parola"])
            server.sendmail(config["email_from"], config["email_to"], msg.as_string())
        print(f"  [Email] ✓ Trimis la {config['email_to']}")
    except Exception as e:
        print(f"  [Email] ✗ Eroare: {e}")


# ==============================================================================
# PAGINI FURNIZORI
# ==============================================================================

import re as _re


def _slugify(s: str) -> str:
    """Transformă un nume de firmă în slug URL-safe (max 60 chars)."""
    s = s.strip().lower()
    s = _re.sub(r'[șş]', 's', s); s = _re.sub(r'[țţ]', 't', s)
    s = _re.sub(r'[ăâ]', 'a', s); s = _re.sub(r'[î]', 'i', s)
    s = _re.sub(r'[^a-z0-9\s-]', '', s)
    s = _re.sub(r'\s+', '-', s)
    s = _re.sub(r'-+', '-', s).strip('-')
    return s[:60] or 'furnizor'


# ==============================================================================
# §1.1 — TABEL CONTRACTE STATIC (fallback pentru fetch JS eșuat)
# ==============================================================================

def _detect_flag_simple(c: dict, firma_sums: dict) -> str:
    """
    Replică logica _detectFlag() din transparenta_pantelimon.html.
    Folosit pentru generarea statică a rândurilor tabelului (§1.1).
    """
    v = float(c.get('valoare', 0) or 0)
    prag, categorie = _prag_pentru_contract(c)
    if v > prag:
        return 'CRITIC'
    if v > prag * 0.97:
        return 'MAJOR'
    firma = c.get('firma', '')
    if firma_sums.get((firma, categorie), 0) > prag and v > prag * 0.5:
        return 'MAJOR'
    if (c.get('ofertanti', 0) or 0) == 1 and v > 50_000:
        return 'MEDIU'
    return 'OK'


def render_contracte_tbody_rows(contracts: list, top_n: int = 20) -> str:
    """
    Generează rânduri <tr> statice pentru tabelul de contracte din
    transparenta_pantelimon.html. Returnează HTML-ul rândurilor gata de injectat
    în <tbody id="contracte-tbody">.

    Rândurile sunt fallback vizibil chiar dacă fetch('contracte.json') din JS
    eșuează (file://, CORS, blocare rețea). JS-ul suprascrie tbody-ul
    dacă se încarcă cu succes (progresive enhancement).
    """
    import html as _html_mod

    # Construiește suma per firmă (pentru detectarea fragmentării)
    firma_sums: dict = {}
    for c in contracts:
        firma = c.get('firma', '')
        _, categorie = _prag_pentru_contract(c)
        key = (firma, categorie)
        firma_sums[key] = firma_sums.get(key, 0) + float(c.get('valoare', 0) or 0)

    # Top N după valoare descrescătoare
    top = sorted(contracts, key=lambda c: float(c.get('valoare', 0) or 0), reverse=True)[:top_n]

    SEV_CLS = {'CRITIC': 'sev-critic', 'MAJOR': 'sev-major', 'MEDIU': 'sev-mediu', 'OK': 'sev-ok'}

    rows = []
    for c in top:
        v = float(c.get('valoare', 0) or 0)
        titlu = _html_mod.escape(str(c.get('titlu', '-'))[:80])
        tip_procedura = _html_mod.escape(str(c.get('tip') or 'Procedură nespecificată'))
        ofertanti = c.get('ofertanti') or '—'
        flag = _detect_flag_simple(c, firma_sums)

        prefix = '🚩 ' if flag != 'OK' else ''
        data_flag = 'nereguli' if flag != 'OK' else 'ok'
        ofertanti_attr = ' style="color:var(--rosu);font-weight:700"' if ofertanti == 1 else ''
        v_fmt = f'{v:,.0f}'.replace(',', '.')  # format românesc: 1.234.567

        rows.append(
            f'<tr class="contract-row" data-flag="{data_flag}">'
            f'<td>{prefix}{titlu}</td>'
            f'<td><strong>{v_fmt}</strong></td>'
            f'<td><span class="badge red">{tip_procedura}</span></td>'
            f'<td{ofertanti_attr}>{ofertanti}</td>'
            f'<td><span class="sev {SEV_CLS[flag]}">{flag}</span></td>'
            f'<td><span class="badge green">Atribuit</span></td>'
            f'</tr>'
        )

    if not rows:
        return (
            '<tr id="contracte-loading-row">'
            '<td colspan="6" style="text-align:center;padding:30px;color:#888">'
            'Nicio dată disponibilă.</td></tr>'
        )
    return '\n          '.join(rows)


def actualizeaza_tabel_contracte(contracte_export: list) -> None:
    """
    Injectează rânduri statice în <tbody id="contracte-tbody"> din
    transparenta_pantelimon.html. Apelat din main() după salvarea contracte.json.
    """
    import re as _re2
    tp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'transparenta_pantelimon.html')
    if not os.path.exists(tp_path):
        print('  ⚠ transparenta_pantelimon.html lipsă — skip actualizare tabel')
        return

    with open(tp_path, encoding='utf-8') as _f:
        content = _f.read()

    rows_html = render_contracte_tbody_rows(contracte_export, top_n=20)

    new_content = _re2.sub(
        r'(<tbody id="contracte-tbody">)(.*?)(</tbody>)',
        lambda m: m.group(1) + '\n          ' + rows_html + '\n        ' + m.group(3),
        content,
        flags=_re2.DOTALL,
        count=1,
    )

    if new_content == content:
        print('  [INFO] tabel contracte: deja actualizat, nicio modificare')
        return

    with open(tp_path, 'w', encoding='utf-8') as _f:
        _f.write(new_content)
    print(f'  [OK] transparenta_pantelimon.html: tabel contracte actualizat static '
          f'(top {min(20, len(contracte_export))} dupa valoare)')


def _categorizeaza_contracte_breakdown(contracte: list, an: int) -> dict:
    """Calculează breakdownul deduplicat al contractelor pentru un an.

    Categorii:
      - 'lucr': contracte cu titluri ce conțin cuvinte-cheie de lucrări (construcții, reparații etc.)
      - 'srv':  toate celelalte (servicii + furnizări)

    Deduplicare identică cu _suma_seap_dedupata: păstrează valoarea MAX per (titlu_canonic, firma).

    Returns: dict cu chei 'lucr_total', 'lucr_n', 'srv_total', 'srv_n', 'total', 'n', 'medie'
    """
    import re as _bre
    rev_re = _bre.compile(r'\s*\(Rev\.\d+\)\s*$', _bre.IGNORECASE)
    lucr: dict = {}
    srv: dict = {}
    for c in contracte:
        data = c.get('data_publicare') or c.get('data') or ''
        if str(an) not in data:
            continue
        titlu_raw = c.get('titlu') or ''
        titlu_can = rev_re.sub('', titlu_raw).strip().lower()
        firma = (c.get('castigator_cui') or c.get('cui') or
                 c.get('castigator') or c.get('firma') or '').strip()
        if not titlu_can or not firma:
            continue
        key = (titlu_can, firma)
        val = float(c.get('valoare_ron') or c.get('valoare') or 0)
        if _este_contract_lucrari(c):
            if key not in lucr or val > lucr[key]:
                lucr[key] = val
        else:
            if key not in srv or val > srv[key]:
                srv[key] = val
    lucr_total = sum(lucr.values())
    lucr_n = len(lucr)
    srv_total = sum(srv.values())
    srv_n = len(srv)
    total = lucr_total + srv_total
    n = lucr_n + srv_n
    return {
        'lucr_total': lucr_total, 'lucr_n': lucr_n,
        'srv_total': srv_total, 'srv_n': srv_n,
        'total': total, 'n': n,
        'medie': total / n if n else 0,
    }


def actualizeaza_kpi_seap(contracte_export: list) -> None:
    """
    Actualizeaza KPI-ul 'Valoare contracte' din transparenta_pantelimon.html
    cu suma deduplicata canonic pentru anul curent (fix BUG-1 + BUG-2 + BUG-3 + BUG-8 + BUG-9).
    Injecteaza atributul data-total-ron folosit de JS ca sursa unica de adevar.
    """
    import re as _re3
    an_curent = datetime.now().year
    total_dedupat, nr_unice = _suma_seap_dedupata(contracte_export, an_curent)
    kpi_text = _format_kpi(total_dedupat)
    total_ron_int = int(round(total_dedupat))
    bkd = _categorizeaza_contracte_breakdown(contracte_export, an_curent)

    def _ro_int(n: float) -> str:
        return f'{int(round(n)):,}'.replace(',', '.')

    tp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'transparenta_pantelimon.html')
    if not os.path.exists(tp_path):
        print('  [WARN] transparenta_pantelimon.html lipsa -- skip actualizare KPI')
        return

    with open(tp_path, encoding='utf-8') as _f:
        content = _f.read()
    original = content

    # BUG-1a: <span class="val" id="kpi-val-total">...</span>
    # Adauga data-an, data-total-ron ca sursa de adevar pentru JS; actualizeaza textul static
    content = _re3.sub(
        r'<span class="val" id="kpi-val-total"[^>]*>[^<]*</span>',
        (f'<span class="val" id="kpi-val-total"'
         f' data-an="{an_curent}" data-total-ron="{total_ron_int}">{kpi_text}</span>'),
        content,
        count=1,
    )

    # BUG-1b: heading in KPI detail panel
    content = _re3.sub(
        r'💰 Valoare totală contracte \d{4} — [\d\.]+ RON',
        f'💰 Valoare totală contracte {an_curent} — {_ro_int(total_dedupat)} RON',
        content,
        count=1,
    )

    # BUG-1c: row in reconciliere table
    content = _re3.sub(
        r'<tr><td>Valoare totală contracte \d{4}</td><td>[\d\.]+ RON</td>',
        f'<tr><td>Valoare totală contracte {an_curent}</td><td>{_ro_int(total_dedupat)} RON</td>',
        content,
        count=1,
    )

    # BUG-8: label "Valoare contracte atribuite YYYY" — an hardcodat
    content = _re3.sub(
        r'Valoare contracte atribuite \d{4}',
        f'Valoare contracte atribuite {an_curent}',
        content,
    )

    # BUG-9: detail-grid breakdown — celule stale din 2025
    content = _re3.sub(
        r'<div class="d-lbl">Contracte lucrări</div><div class="d-val">[^<]*</div>',
        f'<div class="d-lbl">Contracte lucrări</div>'
        f'<div class="d-val">{_ro_int(bkd["lucr_total"])} RON</div>',
        content,
        count=1,
    )
    content = _re3.sub(
        r'<div class="d-lbl">Servicii & furniz[^<]+</div><div class="d-val">[^<]*</div>',
        f'<div class="d-lbl">Servicii & furnizări</div>'
        f'<div class="d-val">{_ro_int(bkd["srv_total"])} RON</div>',
        content,
        count=1,
    )
    content = _re3.sub(
        r'<div class="d-lbl">Nr\. contracte publicate</div><div class="d-val">[^<]*</div>',
        f'<div class="d-lbl">Nr. contracte publicate</div>'
        f'<div class="d-val">{bkd["n"]} contracte</div>',
        content,
        count=1,
    )
    content = _re3.sub(
        r'<div class="d-lbl">Valoare medie/contract</div><div class="d-val">[^<]*</div>',
        f'<div class="d-lbl">Valoare medie/contract</div>'
        f'<div class="d-val">{_ro_int(bkd["medie"])} RON</div>',
        content,
        count=1,
    )

    if content == original:
        print('  [INFO] KPI seap: deja actualizat, nicio modificare')
        return

    with open(tp_path, 'w', encoding='utf-8') as _f:
        _f.write(content)
    print(f'  [OK] transparenta_pantelimon.html: KPI actualizat -- '
          f'{kpi_text} ({nr_unice} contracte unice {an_curent})'
          f' | Lucr: {_ro_int(bkd["lucr_total"])} RON,'
          f' Srv: {_ro_int(bkd["srv_total"])} RON)')


def actualizeaza_kpi_buget_index(budget: dict) -> None:
    """Sincronizează KPI-ul de cheltuieli din index.html cu sursa ANAF/MF."""
    import re as _re_index
    valoare = budget.get("cheltuieli_mil_ron")
    an = budget.get("an")
    if valoare in (None, "") or not an:
        return
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if not os.path.exists(index_path):
        return
    with open(index_path, encoding="utf-8") as handle:
        content = handle.read()
    valoare_text = f"{float(valoare):.2f}".replace(".", ",").rstrip("0").rstrip(",")
    content_nou = _re_index.sub(
        r'(<span class="v" id="idx-cheltuieli">)[^<]*(</span>)',
        rf'\g<1>{valoare_text}M RON\2', content, count=1,
    )
    content_nou = _re_index.sub(
        r'(<span class="l" id="idx-cheltuieli-label">)Cheltuieli \d{4}(</span>)',
        rf'\g<1>Cheltuieli {an}\2', content_nou, count=1,
    )
    if content_nou != content:
        with open(index_path, "w", encoding="utf-8") as handle:
            handle.write(content_nou)
        print(f"  [OK] index.html: cheltuieli {an} sincronizate ({valoare_text}M RON)")


def actualizeaza_semnale_index(n_semnale: int, n_critic: int, index_path: str = None) -> bool:
    """Sincronizează valorile de rezervă (fără JS) din index.html cu raport.json.

    JS-ul paginii le suprascrie oricum din raport.json, dar crawlerele, previzualizările
    și vizitatorii fără JS vedeau cifre vechi (ex. 251/40 după o rulare cu 231/20).
    Returnează True dacă fișierul a fost modificat.
    """
    import re as _re_idx
    if index_path is None:
        index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if not os.path.exists(index_path):
        return False
    with open(index_path, encoding="utf-8") as handle:
        content = handle.read()
    nou = content
    for _id, _val in (("idx-nereguli", n_semnale), ("idx-banner-nereguli", n_semnale),
                      ("idx-banner-critic", n_critic)):
        nou = _re_idx.sub(rf'(<span[^>]*id="{_id}"[^>]*>)[^<]*(</span>)',
                          rf'\g<1>{int(_val)}\2', nou, count=1)
    if nou == content:
        return False
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(nou)
    print(f"  [OK] index.html: {n_semnale} semnale / {n_critic} critice sincronizate")
    return True


def actualizeaza_contoare_analiza(contracte_export: list) -> None:
    """
    BUG-10: Actualizează contoarele „N contracte · YYYY" din secțiunile de analiză
    ale transparenta_pantelimon.html. Aceste referințe devin stale la fiecare an nou
    sau după import de contracte noi.

    Actualizează elementele cu ID: tp-nr-contracte, tp-nr-analiza, tp-an-analiza,
    tp-nr-top10, tp-an-top10, tp-nr-directe, tp-nr-stat-card, tp-an-stat-card.
    """
    import re as _re_ca
    an_curent = datetime.now().year
    n_total = len(contracte_export)

    tp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'transparenta_pantelimon.html')
    if not os.path.exists(tp_path):
        return

    with open(tp_path, encoding='utf-8') as _f:
        content = _f.read()
    original = content

    # Contoare contracte (tp-nr-*)
    for elem_id in ('tp-nr-contracte', 'tp-nr-analiza', 'tp-nr-top10',
                    'tp-nr-directe', 'tp-nr-stat-card'):
        content = _re_ca.sub(
            rf'(<span[^>]*id="{elem_id}"[^>]*>)\d+(</span>)',
            rf'\g<1>{n_total}\2',
            content,
        )

    # An curent (tp-an-*)
    for elem_id in ('tp-an-analiza', 'tp-an-top10', 'tp-an-stat-card'):
        content = _re_ca.sub(
            rf'(<span[^>]*id="{elem_id}"[^>]*>)\d{{4}}(</span>)',
            rf'\g<1>{an_curent}\2',
            content,
        )

    if content == original:
        print('  [INFO] contoare analiza: deja actualizate')
        return

    with open(tp_path, 'w', encoding='utf-8') as _f:
        _f.write(content)
    print(f'  [OK] transparenta_pantelimon.html: contoare analiza → {n_total} contracte, {an_curent}')


def genereaza_og_image(n_flags: int, n_critic: int, valoare_mil: float,
                       scor: int = None, output: str = "og-image.png") -> bool:
    """
    §5.7 AUDIT.md — Generează og-image.png (1200×630px) cu statisticile curente.
    Returnează True dacă imaginea a fost creată, False dacă Pillow nu e disponibil.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  [WARN] Pillow nu e instalat — og-image.png nu a fost generat.")
        return False

    img = Image.new('RGB', (1200, 630), '#0a1628')
    d = ImageDraw.Draw(img)

    # Bandă de accent
    d.rectangle([(0, 0), (8, 630)], fill='#dc2626')

    # Încercăm fonturi sistem; fallback la default
    def _font(size):
        for path in [
            r'C:\Windows\Fonts\calibrib.ttf',
            r'C:\Windows\Fonts\arialbd.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        ]:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    def _font_reg(size):
        for path in [
            r'C:\Windows\Fonts\calibri.ttf',
            r'C:\Windows\Fonts\arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        ]:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    # Header
    d.text((40, 40), 'Transparența Pantelimon', fill='#94a3b8', font=_font_reg(30))
    d.text((40, 90), 'transparenta-pantelimon.eu', fill='#64748b', font=_font_reg(22))

    # Numărul de semnale automate
    d.text((40, 150), f'{n_flags}', fill='#dc2626', font=_font(130))
    d.text((40, 290), 'semnale automate', fill='#ffffff', font=_font(44))

    # Statistici secundare
    d.text((40, 370), f'{n_critic} CRITICE', fill='#f59e0b', font=_font(36))
    d.text((40, 420), f'{valoare_mil:.0f} mil. RON contracte analizate', fill='#cbd5e1', font=_font_reg(28))

    # Scor (dacă disponibil)
    if scor is not None:
        d.rectangle([(40, 480), (500, 540)], fill='#1e3a5f')
        d.text((55, 490), f'Scor transparență: {scor}/100', fill='#ffffff', font=_font_reg(30))

    # Siglă
    d.text((750, 560), 'Inițiativă civică independentă', fill='#475569', font=_font_reg(22))

    try:
        img.save(output, 'PNG', optimize=True)
        print(f"  [OK] og-image.png generat ({n_flags} semnale, {n_critic} critice)")
        return True
    except Exception as e:
        print(f"  [WARN] og-image.png: eroare la salvare: {e}")
        return False


# ==============================================================================
# §5.1  PRESS KIT AUTO-GENERAT — pentru jurnaliști și ONG-uri
# ==============================================================================

def genereaza_press_kit(
    nereguli: list,
    contracte: list,
    scor: dict,
    config: dict,
) -> dict:
    """§5.1 Generează press kit JSON + Markdown pentru jurnaliști.

    Conține: top 10 nereguli, top 10 firme, statistici, linkuri utile.
    Scrie:
      - press_kit.json   (citit de presa.html pentru date dinamice)
      - press_kit.md     (Markdown descărcabil)

    Args:
        nereguli:  toate_flags (lista neregulilor detectate)
        contracte: lista contracte SEAP
        scor:      dict scor transparență {scor, detalii, ...}
        config:    CONFIG dict cu metadate UAT

    Returns:
        dict cu datele press kit-ului
    """
    import json as json_mod
    from datetime import datetime

    BASE_URL = "https://transparenta-pantelimon.eu"
    azi = datetime.now().strftime("%d.%m.%Y")
    azi_iso = datetime.now().strftime("%Y-%m-%d")

    # ── Statistici generale ───────────────────────────────────────
    n_total = len(nereguli)
    n_critic = sum(1 for f in nereguli if f.get("severitate") == "CRITIC")
    n_major  = sum(1 for f in nereguli if f.get("severitate") == "MAJOR")
    n_mediu  = sum(1 for f in nereguli if f.get("severitate") == "MEDIU")
    val_total = sum(c.get("valoare_ron", 0) for c in contracte)
    val_mil = round(val_total / 1_000_000, 2)
    n_contracte = len(contracte)
    n_contracte_semnale = numara_contracte_cu_semnale(nereguli, contracte)
    scor_val = scor.get("scor") if scor else None

    # ── Top 10 nereguli (sortate: CRITIC > MAJOR > MEDIU, apoi valoare) ──
    sev_ord = {"CRITIC": 0, "MAJOR": 1, "MEDIU": 2}
    top_nereguli = sorted(
        nereguli,
        key=lambda f: (sev_ord.get(f.get("severitate", ""), 3), -(f.get("valoare") or 0))
    )[:10]

    top_nereguli_export = [{
        "titlu":        f.get("titlu", "")[:120],
        "severitate":   f.get("severitate", ""),
        "descriere":    f.get("descriere", "")[:300],
        "furnizor":     f.get("furnizor", ""),
        "valoare_ron":  f.get("valoare", 0) or 0,
        "data":         f.get("data", ""),
        "contract_id":  f.get("contract_id") or f.get("contract_numar") or "",
        "tip":          f.get("tip", ""),
        "anchor":       f"#nereguli-{nereguli.index(f) + 1}" if f in nereguli else "",
    } for f in top_nereguli]

    # ── Top 10 firme după valoare contracte ──────────────────────
    firme_val: dict = {}
    firme_nr: dict = {}
    for c in contracte:
        firma = c.get("castigator", "")
        if not firma:
            continue
        firme_val[firma] = firme_val.get(firma, 0) + c.get("valoare_ron", 0)
        firme_nr[firma]  = firme_nr.get(firma, 0) + 1

    top_firme = sorted(firme_val.items(), key=lambda x: -x[1])[:10]
    top_firme_export = [{
        "nume":         f,
        "valoare_ron":  v,
        "nr_contracte": firme_nr.get(f, 0),
    } for f, v in top_firme]

    # ── Structura JSON ────────────────────────────────────────────
    press_kit = {
        "schema_version":  "1.1",
        "generated_at":    azi_iso,
        "uat": {
            "name":   config.get("nume_entitate", ""),
            "cif":    config.get("cui", ""),
            "judet":  config.get("judet", ""),
        },
        "statistici": {
            "total_nereguli":  n_total,
            "total_semnale":    n_total,
            "contracte_cu_semnale": n_contracte_semnale,
            "critice":         n_critic,
            "majore":          n_major,
            "medii":           n_mediu,
            "total_contracte": n_contracte,
            "valoare_totala_ron": val_total,
            "valoare_totala_mil": val_mil,
            "scor_transparenta": scor_val,
        },
        "top_nereguli":  top_nereguli_export,
        "top_semnale":   top_nereguli_export,
        "top_firme":     top_firme_export,
        "date_deschise": {
            "api_json":    f"{BASE_URL}/raport.json",
            "contracte_json": f"{BASE_URL}/contracte.json",
            "rss_feed":    f"{BASE_URL}/feed.xml",
            "harta":       f"{BASE_URL}/harta.html",
        },
        "contact":       config.get("contact_url", ""),
        "site":          BASE_URL,
        "disclaimer":    (
            "Toate datele sunt fapte publice (SEAP, ANAF, ONRC). "
            "Semnalele sunt indicatori euristici, pot avea suprapuneri și nu reprezintă "
            "constatări juridice, prejudicii sau afirmații despre intenții ori vinovăție."
        ),
    }

    # ── Scriere press_kit.json ────────────────────────────────────
    with open("press_kit.json", "w", encoding="utf-8") as fout:
        json_mod.dump(press_kit, fout, ensure_ascii=False, indent=2)

    # ── Generare press_kit.md ─────────────────────────────────────
    top5_md = "\n".join(
        f"{i+1}. [{f['severitate']}] **{f['titlu']}** — {f['furnizor']} — "
        f"{f['valoare_ron']:,.0f} RON"
        for i, f in enumerate(top_nereguli_export[:5])
    )
    top5_firme_md = "\n".join(
        f"{i+1}. **{f['nume']}** — {f['valoare_ron']/1_000_000:.2f} M RON "
        f"({f['nr_contracte']} contracte)"
        for i, f in enumerate(top_firme_export[:5])
    )

    md = f"""# Press kit — Transparența Pantelimon ({azi})

Monitorizare cetățenească automată a achizițiilor publice — {config.get('nume_entitate', 'Primăria Pantelimon')}.

## Statistici la zi

| Indicator | Valoare |
|---|---|
| Semnale automate totale | {n_total} |
| Contracte unice cu semnale | {n_contracte_semnale} |
| Critice / Majore / Medii | {n_critic} / {n_major} / {n_mediu} |
| Contracte analizate | {n_contracte} |
| Valoare totală contracte | {val_mil} M RON |
| Scor transparență | {scor_val if scor_val is not None else 'N/A'}/100 |

## Top 5 semnale (severitate + valoare)

{top5_md}

## Top 5 firme după valoare contracte

{top5_firme_md}

## Date deschise

- API JSON: {BASE_URL}/raport.json
- Contracte JSON: {BASE_URL}/contracte.json
- RSS: {BASE_URL}/feed.xml
- Hartă furnizori: {BASE_URL}/harta.html

## Contact

{config.get('contact_url', '[contact]')}

## Metodologie completă

{BASE_URL}/despre.html

## Disclaimer

Semnalele sunt indicatori euristici și nu reprezintă constatări juridice sau prejudicii.

---
*Generat automat de monitor_pantelimon.py la {azi_iso}*
"""

    with open("press_kit.md", "w", encoding="utf-8") as fout:
        fout.write(md)

    print(f"  ✓ Press kit generat: press_kit.json + press_kit.md "
          f"(top {len(top_nereguli_export)} semnale, top {len(top_firme_export)} firme)")
    return press_kit


def genereaza_sitemap(index_furnizori: list) -> str:
    """Regenerează sitemap.xml cu paginile statice + toate paginile furnizori."""
    BASE = "https://transparenta-pantelimon.eu"
    azi = datetime.now().strftime("%Y-%m-%d")
    statice = [
        ("",                              "1.0", "weekly"),
        ("/raport_transparenta.html",     "0.9", "daily"),
        ("/transparenta_pantelimon.html", "0.8", "monthly"),
        ("/despre.html",                  "0.7", "monthly"),
        ("/presa.html",                   "0.7", "monthly"),
        ("/gdpr.html",                    "0.5", "yearly"),
        ("/petitie.html",                 "0.6", "monthly"),
        ("/harta.html",                   "0.6", "weekly"),
        ("/furnizori/index.html",         "0.6", "weekly"),
    ]
    urls = ""
    for path, prio, freq in statice:
        urls += (
            f"  <url>\n"
            f"    <loc>{BASE}{path}</loc>\n"
            f"    <lastmod>{azi}</lastmod>\n"
            f"    <changefreq>{freq}</changefreq>\n"
            f"    <priority>{prio}</priority>\n"
            f"  </url>\n"
        )
    for f in sorted(index_furnizori, key=lambda x: x["slug"]):
        urls += (
            f"  <url>\n"
            f"    <loc>{BASE}/furnizori/{f['slug']}.html</loc>\n"
            f"    <lastmod>{azi}</lastmod>\n"
            f"    <changefreq>monthly</changefreq>\n"
            f"    <priority>0.5</priority>\n"
            f"  </url>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls
        + '</urlset>\n'
    )


def geocodeaza_firme(
    firme_openapi: dict,
    cui_valori: dict,
    cui_contracte: dict,
    index_furnizori: list,
    cache_db: str = "geocoding_cache.db",
    ttl_zile: int = TTL_NOMINATIM_DAYS,
) -> list:
    """§3.6 Geocodare adrese firme furnizoare via Nominatim (OpenStreetMap).

    Returnează lista de dict-uri cu coordonate pentru harta Leaflet.
    Foloseşte SQLite cache cu TTL TTL_NOMINATIM_DAYS pentru a nu supraîncărca API-ul.

    Args:
        firme_openapi: dict CUI -> {adresa, judet, ...} de la openapi.ro
        cui_valori:    dict CUI -> valoare totală RON contractate
        cui_contracte: dict CUI -> număr contracte
        index_furnizori: list [{nume, slug, ...}] pentru link-uri
        cache_db:      cale fișier SQLite cache
        ttl_zile:      TTL cache în zile (implicit TTL_NOMINATIM_DAYS)

    Returns:
        list [{name, cif, adresa, lat, lng, valoare, nr_contracte, slug}]
        Scrie firme_geocoded.json cu rezultatele.
    """
    import sqlite3
    import time
    import urllib.request
    import urllib.parse
    import json as json_mod
    from datetime import datetime, timedelta

    USER_AGENT = "transparenta-pantelimon-bot (contact: contact@transparenta-pantelimon.eu)"
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    RATE_LIMIT = 1.2  # secunde între requests

    # Inițializare cache SQLite
    def _init_geocache(db_path: str):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS geocoding (
                adresa     TEXT PRIMARY KEY,
                lat        REAL,
                lng        REAL,
                geocodat_la TEXT
            )
        """)
        conn.commit()
        return conn

    def _cache_get_geo(conn, adresa: str, ttl_zile: int):
        row = conn.execute(
            "SELECT lat, lng, geocodat_la FROM geocoding WHERE adresa=?",
            (adresa,)
        ).fetchone()
        if not row:
            return None
        lat, lng, geocodat_la = row
        if geocodat_la:
            try:
                data_cache = datetime.fromisoformat(geocodat_la)
                if datetime.now() - data_cache < timedelta(days=ttl_zile):
                    return {"lat": lat, "lng": lng}
            except ValueError:
                pass
        return None

    def _cache_set_geo(conn, adresa: str, lat, lng):
        conn.execute(
            "INSERT OR REPLACE INTO geocoding (adresa, lat, lng, geocodat_la) VALUES (?,?,?,?)",
            (adresa, lat, lng, datetime.now().isoformat())
        )
        conn.commit()

    def _simplify_adresa(adresa: str) -> str:
        """Extrage localitate + judet din adresa ANAF verbosa pentru Nominatim."""
        import re as _re
        parts = [p.strip() for p in adresa.split(",")]
        judet, localitate, sector = "", "", ""
        for p in parts:
            pu = p.upper()
            if pu.startswith("JUD."):
                judet = _re.sub(r"^JUD\.\s*", "", p, flags=_re.IGNORECASE).strip()
            elif "BUCURE" in pu:
                localitate = "Bucuresti"
            elif _re.match(r"^SECTOR\s+\d+", pu, _re.IGNORECASE):
                sector = _re.sub(r"^SECTOR\s*", "Sector ", p, flags=_re.IGNORECASE).strip()
            elif _re.match(r"^(MUN\.|MUNICIPIUL|ORAS|SAT|ORŞ\.|ORS\.)\s*", pu):
                loc = _re.sub(r"^(MUN\.|MUNICIPIUL|ORAS|SAT|ORŞ\.\s*|ORS\.)\s*", "", p, flags=_re.IGNORECASE).strip()
                loc = loc.split()[0] if loc else loc
                if loc:
                    localitate = loc
            elif _re.match(r"^(STR|SOS|BD|BDUL|CAL\.|CALEA|NR|BL|SC|AP|ET|ALEEA|INTRAREA)", pu):
                break
        parts_q = []
        if localitate == "Bucuresti" and sector:
            parts_q.append(sector)
        if localitate:
            parts_q.append(localitate)
        if judet and judet.upper() not in (localitate.upper() if localitate else ""):
            parts_q.append(judet)
        if not parts_q:
            for p in adresa.split(",")[:2]:
                p2 = _re.sub(r"^(JUD\.|MUNICIPIUL|ORAS|MUN\.|SAT|ORŞ\.|ORS\.)\s*", "", p, flags=_re.IGNORECASE).strip()
                if p2:
                    parts_q.append(p2)
        return ", ".join(parts_q) if parts_q else adresa[:50]

    def _nominatim_query(adresa: str) -> tuple:
        """Returnează (lat, lng) sau (None, None) dacă nu găsit."""
        adresa_query = _simplify_adresa(adresa)
        query = urllib.parse.urlencode({"q": adresa_query + ", Romania", "format": "json", "limit": "1"})
        url = f"{NOMINATIM_URL}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json_mod.loads(resp.read().decode("utf-8"))
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception:
            pass
        return None, None

    # Construiește slug map din index_furnizori
    slug_map = {f["nume"]: f["slug"] for f in index_furnizori}

    conn = _init_geocache(cache_db)
    rezultate = []
    ultima_req = 0.0

    for cui, info in firme_openapi.items():
        adresa = (info.get("adresa") or "").strip()
        if not adresa:
            continue
        # Simplificăm adresa ANAF verbosă pentru query Nominatim precis
        adresa_query = adresa  # cheia de cache rămâne adresa completă

        cached = _cache_get_geo(conn, adresa_query, ttl_zile)
        if cached:
            lat, lng = cached["lat"], cached["lng"]
        else:
            # Rate limiting Nominatim (1 req/sec policy)
            elapsed = time.time() - ultima_req
            if elapsed < RATE_LIMIT:
                time.sleep(RATE_LIMIT - elapsed)
            lat, lng = _nominatim_query(adresa_query)
            ultima_req = time.time()
            if lat is not None:  # Nu salvam in cache geocodare esuate
                _cache_set_geo(conn, adresa_query, lat, lng)

        if lat is None or lng is None:
            continue

        # Găsim numele firmei din firme_openapi sau din contracte
        # CUI din openapi poate fi cu sau fără prefix "RO"
        cui_clean = cui.lstrip("RO").lstrip("0") if cui.startswith("RO") else cui
        valoare = cui_valori.get(cui, 0) or cui_valori.get("RO" + cui, 0)
        nr_contracte = cui_contracte.get(cui, 0) or cui_contracte.get("RO" + cui, 0)

        # Găsim slug din index_furnizori prin cui sau la potrivire inexactă
        firma_slug = ""
        firma_name = info.get("_nume", "")
        if firma_name in slug_map:
            firma_slug = slug_map[firma_name]

        if valoare == 0 and nr_contracte == 0:
            continue  # firmă necunoscută în contracte, skip

        rezultate.append({
            "name": firma_name or cui,
            "cif": cui,
            "adresa": adresa,
            "lat": lat,
            "lng": lng,
            "valoare": valoare,
            "nr_contracte": nr_contracte,
            "slug": firma_slug,
        })

    conn.close()

    # Scriere firme_geocoded.json
    with open("firme_geocoded.json", "w", encoding="utf-8") as fout:
        json_mod.dump(rezultate, fout, ensure_ascii=False, indent=2)
    print(f"  ✓ geocodare completă: {len(rezultate)} firme cu coordonate → firme_geocoded.json")
    return rezultate


def genereaza_pagina_furnizor(
        nume: str, slug: str,
        flags_firma: list, contracte_firma: list,
        config: dict, mentiuni: list = None,
        mentiuni_auto: list = None,
        firme_legate: list = None) -> str:
    """Generează pagina HTML dedicată unui furnizor."""
    import html as html_mod
    import re

    valoare_totala = sum(c.get("valoare_ron", 0) for c in contracte_firma)
    n_critic = sum(1 for f in flags_firma if f.get("severitate") == "CRITIC")
    n_major  = sum(1 for f in flags_firma if f.get("severitate") == "MAJOR")
    n_mediu  = sum(1 for f in flags_firma if f.get("severitate") == "MEDIU")
    cui_f    = (contracte_firma[0].get("castigator_cui", "") or "") if contracte_firma else ""
    base_url = "https://transparenta-pantelimon.eu"
    safe_name = html_mod.escape(nume)

    culori = {"CRITIC": "#C0392B", "MAJOR": "#E67E22", "MEDIU": "#F39C12"}
    emoji_sev = {"CRITIC": "🔴", "MAJOR": "🟠", "MEDIU": "🟡"}

    flags_html = ""
    for idx, f in enumerate(flags_firma, 1):
        culoare = culori.get(f.get("severitate", ""), "#999")
        emoji = emoji_sev.get(f.get("severitate", ""), "⚪")
        descriere_text = re.sub(r"<[^>]+>", "", str(f.get("descriere", "")))
        descriere_safe = html_mod.escape(descriere_text[:400])
        flags_html += f"""
      <div style="border-left:4px solid {culoare};background:#fff;padding:12px 16px;
                  border-radius:0 6px 6px 0;margin-bottom:8px;
                  box-shadow:0 1px 3px rgba(0,0,0,0.08)">
        <div style="font-weight:700;color:{culoare}">{emoji} [{html_mod.escape(str(f.get("severitate","")))}] {html_mod.escape(str(f.get("titlu",""))[:120])}</div>
        <div style="font-size:13px;color:#555;margin-top:4px">{descriere_safe}</div>
        <div style="font-size:12px;color:#888;margin-top:4px">
          📋 {html_mod.escape(str(f.get("contract_id","") or "–"))} &nbsp;|&nbsp;
          💰 {_fmt_ron(float(f.get("valoare",0) or 0))} &nbsp;|&nbsp;
          📅 {html_mod.escape(str(f.get("data","")))}
        </div>
      </div>"""

    contracte_rows = ""
    for c in sorted(contracte_firma, key=lambda x: x.get("data_publicare",""), reverse=True):
        contracte_rows += f"""
        <tr>
          <td style="padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:13px">{html_mod.escape(c.get("titlu","")[:55])}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:13px;font-weight:700">{_fmt_ron(c.get("valoare_ron",0))}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:12px">{html_mod.escape(c.get("tip_procedura",""))}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #f0f2f5;font-size:12px">{html_mod.escape(c.get("data_publicare",""))}</td>
        </tr>"""

    onrc_link = f'https://termene.ro/firma/{cui_f}' if cui_f else '#'

    # Secțiune mențiuni media (din mentiuni_media.json, curatorial)
    mentiuni_html = ""
    if mentiuni:
        rands_m = ""
        for m in mentiuni:
            rezumat_row = (
                f'<div style="font-size:13px;color:#555;margin-top:4px">'
                f'{html_mod.escape(str(m.get("rezumat",""))[:300])}</div>'
            ) if m.get("rezumat") else ""
            rands_m += f"""
      <div style="border-left:3px solid #2874A6;padding:8px 14px;margin-bottom:8px;
                  background:#fff;border-radius:0 6px 6px 0;
                  box-shadow:0 1px 3px rgba(0,0,0,.06)">
        <div style="font-weight:600;font-size:14px">
          <a href="{html_mod.escape(str(m.get('url','#')))}" target="_blank" rel="noopener"
             style="color:#2874A6;text-decoration:none">
            {html_mod.escape(str(m.get('titlu',''))[:120])}
          </a>
        </div>
        <div style="font-size:12px;color:#888;margin-top:3px">
          🗞️ {html_mod.escape(str(m.get('outlet','')))} &nbsp;·&nbsp;
          📅 {html_mod.escape(str(m.get('data','')))}
        </div>
        {rezumat_row}
      </div>"""
        mentiuni_html = f"""
  <h2>📰 Mențiuni în presă ({len(mentiuni)})</h2>
  {rands_m}"""

    # Secțiune mențiuni automate de presă (din mentiuni_presa_auto.json)
    mentiuni_auto_html = ""
    if mentiuni_auto:
        rands_auto = ""
        for m in mentiuni_auto[:10]:
            kw = m.get('matched_keyword', '')
            rands_auto += f"""
      <div style="border-left:3px solid #7C3AED;padding:8px 14px;margin-bottom:8px;
                  background:#fff;border-radius:0 6px 6px 0;
                  box-shadow:0 1px 3px rgba(0,0,0,.06)">
        <div style="font-weight:600;font-size:14px">
          <a href="{html_mod.escape(str(m.get('link','#')))}" target="_blank" rel="noopener noreferrer"
             style="color:#7C3AED;text-decoration:none">
            {html_mod.escape(str(m.get('title',''))[:120])}
          </a>
        </div>
        <div style="font-size:12px;color:#888;margin-top:3px">
          🗞️ {html_mod.escape(str(m.get('source','')))} &nbsp;·&nbsp;
          📅 {html_mod.escape(str(m.get('pub_date',''))[:16])}
          {(' &nbsp;·&nbsp; 🔑 <strong>' + html_mod.escape(kw) + '</strong>') if kw else ''}
        </div>
      </div>"""
        mentiuni_auto_html = f"""
  <h2>🔍 Mențiuni detectate automat în presă ({len(mentiuni_auto)})</h2>
  <div style="background:#FDF4FF;border:1px solid #E9D5FF;border-radius:8px;
              padding:10px 14px;font-size:12px;color:#6B21A8;margin-bottom:12px">
    ⚠️ <strong>Detecție automată</strong> — articolele de mai jos conțin cuvinte-cheie
    asociate cu numele firmei. Pot exista rezultate nerelevante. Verificare manuală recomandată.
  </div>
  {rands_auto}"""

    # Secțiune firme legate (din retele_firme.json)
    firme_legate_html = ""
    if firme_legate:
        tip_friendly = {
            'ADRESA_COMUNA': 'aceeași adresă fiscală',
            'ACTIONAR_COMUN': 'acționar comun',
        }
        rows_legate = ""
        for leg in firme_legate:
            tip_f = tip_friendly.get(leg.get('tip', ''), leg.get('tip', ''))
            slug_l = re.sub(r'[^\w-]', '-', leg.get('nume_legat', '').lower()).strip('-')
            slug_l = re.sub(r'-+', '-', slug_l)
            link_l = f'<a href="{slug_l}.html" style="color:#5b21b6">{html_mod.escape(leg.get("nume_legat",""))}</a>'
            rows_legate += f"""
      <li style="margin:.3rem 0">{link_l} — <em style="color:#6b7280">{html_mod.escape(tip_f)}</em></li>"""
        firme_legate_html = f"""
  <h2 style="margin-top:2rem">🔗 Firme legate (detectare automată)</h2>
  <div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;
              padding:.6rem 1rem;font-size:.82rem;color:#6b21a8;margin:.5rem 0 .75rem">
    Relații detectate pe baza adresei fiscale ANAF. Pot fi coincidențe geografice
    (sedii de comoditate, clădiri de birouri). Verificare manuală recomandată.
    <a href="../retele.html" style="color:#5b21b6;font-weight:600">→ Grafic rețele</a>
  </div>
  <ul style="margin:.2rem 0 .5rem 1.3rem;color:#374151;font-size:.9rem">{rows_legate}
  </ul>"""

    return f"""<!DOCTYPE html>
<html lang="ro">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_name} — Transparența Pantelimon</title>
<meta name="description" content="Dosarul de transparență al {safe_name}: {len(contracte_firma)} contracte cu Primăria Pantelimon, valoare {_fmt_ron(valoare_totala)}, {len(flags_firma)} semnale automate.">
  <meta property="og:title" content="{safe_name} — Transparența Pantelimon">
<meta property="og:description" content="{len(contracte_firma)} contracte, {_fmt_ron(valoare_totala)}, {len(flags_firma)} semnale detectate automat.">
  <meta property="og:url" content="{base_url}/furnizori/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:image" content="{base_url}/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{base_url}/og-image.png">
  <link rel="canonical" href="{base_url}/furnizori/{slug}.html">
  <script src="../enhance.js" defer></script>
  <style>
    body{{font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;margin:0;background:#f5f7fa;color:#1a1a1a}}
    .container{{max-width:900px;margin:0 auto;padding:24px 16px}}
    .back-link{{color:#0070C0;text-decoration:none;font-size:14px}}
    .back-link:hover{{text-decoration:underline}}
    h1{{font-size:1.6rem;margin:16px 0 4px}}
    .meta{{color:#666;font-size:14px;margin-bottom:20px}}
    .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:20px 0}}
    .stat{{background:#fff;border-radius:8px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center}}
    .stat-val{{font-size:1.5rem;font-weight:700;color:#00244A}}
    .stat-lbl{{font-size:11px;color:#888;margin-top:4px}}
    table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
    th{{padding:10px 12px;text-align:left;background:#00244A;color:#fff;font-size:12px}}
    h2{{font-size:1.1rem;margin:28px 0 12px;color:#00244A}}
    .ext-btn{{display:inline-block;padding:8px 16px;background:#0070C0;color:#fff;
              border-radius:6px;text-decoration:none;font-size:13px;margin-right:8px;margin-bottom:8px}}
    .ext-btn:hover{{opacity:.85}}
    footer{{text-align:center;color:#aaa;font-size:12px;padding:32px 0 16px}}
  </style>
</head>
<body>
<div class="container">
  <a href="../raport_transparenta.html" class="back-link">← înapoi la raport</a>
  <h1>{safe_name}</h1>
  <div class="meta">
    CUI: {html_mod.escape(cui_f) if cui_f else "—"} &nbsp;·&nbsp;
    Furnizor în relație contractuală cu Primăria Pantelimon
  </div>

  <div class="stats">
    <div class="stat"><div class="stat-val">{len(contracte_firma)}</div><div class="stat-lbl">Contracte</div></div>
    <div class="stat"><div class="stat-val">{_fmt_ron(valoare_totala)}</div><div class="stat-lbl">Valoare totală</div></div>
    <div class="stat"><div class="stat-val" style="color:#C0392B">{n_critic}</div><div class="stat-lbl">Semnale CRITIC</div></div>
    <div class="stat"><div class="stat-val" style="color:#E67E22">{n_major}</div><div class="stat-lbl">Semnale MAJOR</div></div>
    <div class="stat"><div class="stat-val" style="color:#F39C12">{n_mediu}</div><div class="stat-lbl">Semnale MEDIU</div></div>
  </div>

  <div style="margin-bottom:16px">
    <a href="{onrc_link}" target="_blank" rel="noopener" class="ext-btn">🔍 Dosar ONRC (termene.ro)</a>
    <a href="https://listafirme.ro/search/?q={html_mod.escape(cui_f or nume)}" target="_blank" rel="noopener" class="ext-btn">📋 Listafirme.ro</a>
    <a href="../raport_transparenta.html" class="ext-btn" style="background:#1E8449">📊 Raport complet</a>
  </div>

  <h2>⚠️ Semnale automate ({len(flags_firma)})</h2>
  {flags_html if flags_firma else '<p style="color:#888;font-size:14px">Niciun semnal automat pentru acest furnizor.</p>'}

  <h2>📄 Contracte ({len(contracte_firma)})</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr><th>Titlu</th><th>Valoare</th><th>Procedură</th><th>Dată</th></tr></thead>
    <tbody>{contracte_rows}</tbody>
  </table>
  </div>

  {mentiuni_html}
  {mentiuni_auto_html}
  {firme_legate_html}
  <footer>
    Date extrase din surse publice oficiale (SEAP / data.gov.ro) · Inițiativă cetățenească independentă
  </footer>
</div>
<script data-goatcounter="https://transparenta-pantelimon.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
</body>
</html>"""


def genereaza_index_furnizori(index: list) -> str:
    """Generează furnizori/index.html cu lista A-Z a furnizorilor."""
    import html as html_mod
    rânduri = ""
    for f in sorted(index, key=lambda x: x["nume"]):
        safe_nume = html_mod.escape(str(f["nume"]))
        safe_slug = html_mod.escape(str(f["slug"]), quote=True)
        rânduri += f"""
      <tr>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5">
          <a href="{safe_slug}.html" style="color:#0070C0;font-weight:600">{safe_nume}</a>
        </td>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;font-weight:700">{_fmt_ron(f['valoare'])}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5">{f['count']}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5;color:{'#C0392B' if f['flags_critic']>0 else '#E67E22' if f['flags_major']>0 else '#888'}">{f['flags_critic']}C / {f['flags_major']}M / {f['flags_mediu']}m</td>
      </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ro">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Furnizori Primăria Pantelimon — Transparența</title>
<meta name="description" content="Index A-Z al furnizorilor Primăriei Pantelimon cu semnale de risc detectate automat.">
  <link rel="canonical" href="https://transparenta-pantelimon.eu/furnizori/">
  <script src="../enhance.js" defer></script>
  <style>
    body{{font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;margin:0;background:#f5f7fa;color:#1a1a1a}}
    .container{{max-width:900px;margin:0 auto;padding:24px 16px}}
    h1{{font-size:1.5rem;margin-bottom:4px}}
    .sub{{color:#666;font-size:14px;margin-bottom:20px}}
    table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
    th{{padding:10px 12px;text-align:left;background:#00244A;color:#fff;font-size:12px}}
    .back-link{{color:#0070C0;text-decoration:none;font-size:14px}}
    footer{{text-align:center;color:#aaa;font-size:12px;padding:32px 0 16px}}
  </style>
</head>
<body>
<div class="container">
  <a href="../raport_transparenta.html" class="back-link">← înapoi la raport</a>
  <h1>🏢 Furnizori monitorizați</h1>
  <div class="sub">Furnizori cu ≥3 contracte cu Primăria Pantelimon (sortare A-Z)</div>
  <div style="overflow-x:auto">
  <table>
    <thead><tr><th>Firmă</th><th>Valoare totală</th><th>Contracte</th><th>Semnale (C/M/m)</th></tr></thead>
    <tbody>{rânduri}</tbody>
  </table>
  </div>
  <footer>Date extrase din surse publice oficiale · Inițiativă cetățenească independentă</footer>
</div>
<script data-goatcounter="https://transparenta-pantelimon.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
</body>
</html>"""


# ==============================================================================
# MAIN
# ==============================================================================

def genereaza_pagini_furnizori_locale(contracte: list, flags: list) -> list:
    """Regenerează fișele furnizorilor fără acces la servicii externe."""
    from collections import defaultdict

    contracte_per_firma = defaultdict(list)
    for contract in contracte:
        if contract.get("castigator"):
            contracte_per_firma[contract["castigator"]].append(contract)

    flags_per_firma = defaultdict(list)
    for flag in flags:
        furnizor = flag.get("furnizor")
        if furnizor and furnizor != "Multiple":
            flags_per_firma[furnizor].append(flag)

    mentiuni_media = {}
    try:
        with open("mentiuni_media.json", encoding="utf-8") as handle:
            raw = json.load(handle)
        mentiuni_media = {key: value for key, value in raw.items() if not key.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    mentiuni_auto = {}
    try:
        with open("mentiuni_presa_auto.json", encoding="utf-8") as handle:
            mentiuni_auto = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    os.makedirs("furnizori", exist_ok=True)
    index_furnizori = []
    for firma, contracte_firma in contracte_per_firma.items():
        if len(contracte_firma) < 3:
            continue
        slug = _slugify(firma)
        if not slug:
            continue
        flags_firma = flags_per_firma.get(firma, [])
        cui_firma = str(contracte_firma[0].get("castigator_cui", "") or "")
        auto_firma = mentiuni_auto.get(cui_firma, {}).get("mentiuni", [])
        pagina_html = genereaza_pagina_furnizor(
            firma,
            slug,
            flags_firma,
            contracte_firma,
            CONFIG,
            mentiuni=mentiuni_media.get(firma, []),
            mentiuni_auto=auto_firma or None,
        )
        with open(f"furnizori/{slug}.html", "w", encoding="utf-8") as handle:
            handle.write(pagina_html)
        index_furnizori.append({
            "nume": firma,
            "slug": slug,
            "count": len(contracte_firma),
            "valoare": sum(c.get("valoare_ron", 0) for c in contracte_firma),
            "flags_critic": sum(1 for f in flags_firma if f.get("severitate") == "CRITIC"),
            "flags_major": sum(1 for f in flags_firma if f.get("severitate") == "MAJOR"),
            "flags_mediu": sum(1 for f in flags_firma if f.get("severitate") == "MEDIU"),
        })

    with open("furnizori/index.html", "w", encoding="utf-8") as handle:
        handle.write(genereaza_index_furnizori(index_furnizori))
    with open("sitemap.xml", "w", encoding="utf-8") as handle:
        handle.write(genereaza_sitemap(index_furnizori))
    print(f"  [OK] {len(index_furnizori)} fișe de furnizor și sitemap regenerate local")
    return index_furnizori


def regenereaza_din_exporturile_existente() -> None:
    """Regenerează determinist raportul fără apeluri externe.

    Folosește `contracte.json` deja versionat și păstrează explicit în metadate faptul
    că sursele ANAF/ONRC nu au fost reîmprospătate. Este util când un serviciu extern
    este lent sau indisponibil și evită publicarea unui raport parțial.
    """
    with open("contracte.json", encoding="utf-8") as handle:
        contracte_export = json.load(handle)
    # Fără asta, raport.json regenerat ieșea cu supplier_cif gol pe toate flagurile
    _index_cui = construieste_index_cui(contracte_export)
    contracte = [{
        "id": c.get("id", ""),
        "numar": c.get("numar", "–"),
        "titlu": c.get("titlu", ""),
        "valoare_ron": float(c.get("valoare_ron", c.get("valoare", 0)) or 0),
        "data_publicare": c.get("data_publicare", c.get("data", "")),
        "tip_procedura": c.get("tip_procedura", c.get("tip", "")),
        "castigator": c.get("castigator", c.get("firma", "")),
        "castigator_cui": c.get("castigator_cui", c.get("cui", "")),
        "nr_ofertanti": int(c.get("nr_ofertanti", c.get("ofertanti", 0)) or 0),
        "data_start": c.get("data_start", ""),
        "data_sfarsit": c.get("data_sfarsit", ""),
        "autoritate": c.get("autoritate", ""),
        "cpv": c.get("cpv", ""),
    } for c in contracte_export]

    raport_vechi = {}
    try:
        with open("raport.json", encoding="utf-8") as handle:
            raport_vechi = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    source_contracte_generated_at = (
        raport_vechi.get("data_freshness", {}).get("contracts_source_generated_at")
        or raport_vechi.get("generated_at")
    )

    statistici_hcl = {"total_hcl": 0, "ordinare": 0, "extraordinare": 0, "pct_extraordinare": 0}
    for flag in raport_vechi.get("flags", []):
        if flag.get("type") != "SEDINTE_EXTRAORDINARE_EXCESIVE":
            continue
        import re as _re_offline
        match = _re_offline.search(
            r"Din\s+(\d+)\s+ședințe.*?,\s*(\d+)\s*\(([\d.,]+)%\)",
            flag.get("explanation", ""), _re_offline.DOTALL,
        )
        if match:
            total, extraordinare = int(match.group(1)), int(match.group(2))
            statistici_hcl = {
                "total_hcl": total,
                "ordinare": max(0, total - extraordinare),
                "extraordinare": extraordinare,
                "pct_extraordinare": float(match.group(3).replace(",", ".")),
            }
        break

    CONFIG["_offline_mode"] = True
    CONFIG["_firme_openapi"] = {}
    CONFIG["_firme_onrc"] = {}
    CONFIG["_hcl_total"] = statistici_hcl["total_hcl"]
    CONFIG["_hcl_ordinare"] = statistici_hcl["ordinare"]
    CONFIG["_hcl_extraordinare"] = statistici_hcl["extraordinare"]
    CONFIG["_hcl_pct"] = statistici_hcl["pct_extraordinare"]
    CONFIG["_hcl_ocr"] = "Date păstrate din ultima analiză completă"

    flags_contracte = analizeaza_red_flags(contracte, CONFIG)
    toate_flags = flags_contracte + detect_sedinte_extraordinare(statistici_hcl)
    scor = calculeaza_scor_transparenta(toate_flags, contracte, statistici_hcl)
    CONFIG["_scor"] = scor

    # Ultima execuție bugetară validată în paginile proiectului. Rularea offline
    # nu pretinde că a reîmprospătat această sursă.
    budget = {
        "an": 2025,
        "venituri_mil_ron": 147.97,
        "cheltuieli_mil_ron": 146.43,
        "yoy_venituri": "N/A",
        "yoy_cheltuieli": "N/A",
        "sursa": "ultima execuție bugetară validată (rulare offline)",
    }
    flags_noi = []
    raport_html = genereaza_raport_html(budget, contracte, toate_flags, flags_noi, CONFIG)
    with open(CONFIG["fisier_raport"], "w", encoding="utf-8") as handle:
        handle.write(raport_html)

    total_valoare = sum(c["valoare_ron"] for c in contracte)
    raport_json = {
        "schema_version": "1.1",
        "generated_at": datetime.now().isoformat(),
        "entity": {"name": CONFIG["nume_entitate"], "cif": CONFIG["cui"], "judet": CONFIG["judet"]},
        "totals": {
            "flags": len(toate_flags),
            "signals": len(toate_flags),
            "contracts_analyzed": len(contracte),
            "contracts_with_signals": numara_contracte_cu_semnale(toate_flags, contracte),
            "total_value_ron": total_valoare,
            "by_severity": {
                sev: sum(1 for flag in toate_flags if flag.get("severitate") == sev)
                for sev in ("CRITIC", "MAJOR", "MEDIU")
            },
        },
        "flags": [{
            "id": index,
            "severity": flag.get("severitate", ""),
            "title": flag.get("titlu", ""),
            "explanation": flag.get("descriere", ""),
            "supplier": flag.get("furnizor", ""),
            "supplier_cif": _cui_pentru_furnizor(flag.get("furnizor", ""), flag.get("cif_furnizor", ""), _index_cui),
            "sum_ron": flag.get("valoare", 0) or 0,
            "date": flag.get("data", ""),
            "contract_id": flag.get("contract_id") or flag.get("contract_numar") or "",
            "procedure": flag.get("tip_procedura", ""),
            "type": flag.get("tip", ""),
            "anchor": f"nereguli-{index}",
        } for index, flag in enumerate(toate_flags, 1)],
        "scor_transparenta": scor,
        "legal_thresholds": {
            "products_services_ron_excl_vat": CONFIG["prag_servicii_furnizare"],
            "works_ron_excl_vat": CONFIG["prag_lucrari"],
            "verified_at": PRAGURI_LEGALE_VERIFICATE_LA,
            "source": PRAGURI_LEGALE_SURSA,
        },
        "data_freshness": {
            "mode": "regenerated_from_versioned_contract_export",
            "contracts_source_generated_at": source_contracte_generated_at,
            "external_enrichment_refreshed": False,
        },
    }
    with open("raport.json", "w", encoding="utf-8") as handle:
        json.dump(raport_json, handle, ensure_ascii=False, indent=2)

    with open("feed.xml", "w", encoding="utf-8") as handle:
        handle.write(genereaza_feed_atom(toate_flags, datetime.now()))
    genereaza_press_kit(toate_flags, contracte, scor, CONFIG)
    genereaza_pagini_furnizori_locale(contracte, toate_flags)
    try:
        with open("istoric_scor.json", encoding="utf-8") as handle:
            istoric = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        istoric = {"puncte": []}
    luna_scor = scor["data"][:7]
    puncte = [p for p in istoric.get("puncte", []) if not p.get("data", "").startswith(luna_scor)]
    puncte.append({"data": scor["data"], "scor": scor["scor"]})
    istoric["puncte"] = sorted(puncte, key=lambda p: p["data"])[-24:]
    with open("istoric_scor.json", "w", encoding="utf-8") as handle:
        json.dump(istoric, handle, ensure_ascii=False, indent=2)
    genereaza_og_image(
        len(toate_flags),
        sum(1 for flag in toate_flags if flag.get("severitate") == "CRITIC"),
        round(total_valoare / 1_000_000, 1),
        scor.get("scor"),
    )
    actualizeaza_tabel_contracte(contracte_export)
    actualizeaza_kpi_seap(contracte_export)
    actualizeaza_kpi_buget_index(budget)
    actualizeaza_semnale_index(len(toate_flags), sum(1 for _f in toate_flags if _f.get("severitate") == "CRITIC"))
    actualizeaza_contoare_analiza(contracte_export)
    with open("delta.json", "w", encoding="utf-8") as handle:
        json.dump({
            "data_curenta": datetime.now().isoformat(),
            "data_anterioara": raport_vechi.get("generated_at"),
            "nereguli_noi": 0,
            "nereguli_rezolvate": max(0, (raport_vechi.get("totals", {}).get("flags", 0) - len(toate_flags))),
            "scor_transparenta": scor.get("scor"),
            "top_noi": [],
        }, handle, ensure_ascii=False, indent=2)
    salveaza_stare(CONFIG["fisier_stare"], toate_flags, contracte, [])
    print(
        f"  [OK] Regenerare offline completă: {len(toate_flags)} semnale, "
        f"{numara_contracte_cu_semnale(toate_flags, contracte)} contracte unice cu semnale."
    )


def main():
    # --- CLI: parametrizare UAT ---
    import argparse as _ap
    _parser = _ap.ArgumentParser(add_help=False)
    _parser.add_argument("--cif", default=None)
    _parser.add_argument("--nume", default=None)
    _parser.add_argument("--judet", default=None)
    _parser.add_argument("--output-dir", default=None)
    _parser.add_argument("--offline-existing", action="store_true")
    _args, _ = _parser.parse_known_args()
    if _args.cif: CONFIG["cui"] = _args.cif
    if _args.nume: CONFIG["nume_entitate"] = _args.nume
    if _args.judet: CONFIG["judet"] = _args.judet
    if _args.output_dir:
        os.makedirs(_args.output_dir, exist_ok=True)
        os.chdir(_args.output_dir)
    if _args.offline_existing:
        regenereaza_din_exporturile_existente()
        return
    # --- end CLI ---

    # Încarcă mențiuni automate de presă (opțional — fișier mentiuni_presa_auto.json)
    _mentiuni_presa_auto_by_cui: dict = {}
    try:
        from monitorizare_presa import incarca_mentiuni_presa_auto as _imp_auto
        _mentiuni_presa_auto_raw = _imp_auto()
        # Indexăm după CUI pentru lookup rapid în bucla furnizori
        _mentiuni_presa_auto_by_cui = _mentiuni_presa_auto_raw
        if _mentiuni_presa_auto_by_cui:
            n_cu_hits = sum(1 for v in _mentiuni_presa_auto_by_cui.values() if v.get('total', 0) > 0)
            print(f"  ✓ mentiuni_presa_auto.json: {n_cu_hits} firme cu mențiuni de presă")
    except (ImportError, Exception) as _e_auto:
        pass  # opțional, nu blocăm dacă lipsește

    # Încarcă mențiuni media curatoriale (opțional — fișier mentiuni_media.json)
    _mentiuni_media: dict = {}
    try:
        with open("mentiuni_media.json", encoding="utf-8") as _fmm:
            _raw_mm = json.load(_fmm)
        # Excludem cheile de metadate (prefixate cu _)
        _mentiuni_media = {k: v for k, v in _raw_mm.items() if not k.startswith("_")}
        _total_mm = sum(len(v) for v in _mentiuni_media.values())
        if _total_mm:
            print(f"  ✓ mentiuni_media.json: {_total_mm} mențiuni pentru {len(_mentiuni_media)} firme")
    except FileNotFoundError:
        pass
    except Exception as _e_mm:
        print(f"  [WARN] mentiuni_media.json: {_e_mm}")

    # Încarcă rețelele de firme (opțional — retele_firme.json)
    _retea_firme: dict = {}
    try:
        from analizeaza_retele import incarca_retea as _incarca_retea
        _retea_firme = _incarca_retea()
        if _retea_firme.get('edges'):
            print(f"  ✓ retele_firme.json: {len(_retea_firme['edges'])} relații")
    except (ImportError, Exception):
        pass  # opțional

    trimite_email = "--email" in sys.argv
    print("\n" + "="*60)
    print(f"  MONITOR TRANSPARENȚĂ BUGETARĂ — {CONFIG['nume_entitate']}")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("="*60)

    # 1. Buget
    print("\n[1/6] Fetchuiesc date bugetare...")
    budget = fetch_budget_transparenta(CONFIG["cui"])

    # 2. Contracte din data.gov.ro
    print("\n[2/6] Fetchuiesc contracte din data.gov.ro...")
    contracte, seap_debug = fetch_contracts_seap(CONFIG["cui"], CONFIG["luni_analiza"])

    # Fallback: dacă data.gov.ro nu e accesibil (ex. GitHub Actions blochează IP-urile Azure),
    # încărcăm contracte.json deja existent în repo (actualizat la ultima rulare locală).
    if not contracte:
        fallback_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracte.json")
        if os.path.exists(fallback_path):
            try:
                with open(fallback_path, encoding="utf-8") as _f:
                    contracte = json.load(_f)
                # contracte.json foloseşte chei scurtate (valoare, firma, tip, etc.)
                # → normalizăm la formatul intern aşteptat de analizeaza_red_flags şi genereaza_raport_html
                contracte = [
                    {
                        "id":             c.get("id", ""),
                        "titlu":          c.get("titlu", ""),
                        "valoare_ron":    float(c.get("valoare_ron", c.get("valoare", 0)) or 0),
                        "data_publicare": c.get("data_publicare", c.get("data", "")),
                        "tip_procedura":  c.get("tip_procedura", c.get("tip", "")),
                        "castigator":     c.get("castigator", c.get("firma", "")),
                        "castigator_cui": c.get("castigator_cui", c.get("cui", "")),
                        "nr_ofertanti":   int(c.get("nr_ofertanti", c.get("ofertanti", 0)) or 0),
                        "numar":          c.get("numar", "–"),
                        "data_start":     c.get("data_start", ""),
                        "data_sfarsit":   c.get("data_sfarsit", ""),
                        "autoritate":     c.get("autoritate", ""),
                        "cpv":            c.get("cpv", ""),
                    }
                    for c in contracte
                ]
                seap_debug.append(f"FALLBACK: loaded {len(contracte)} contracte din contracte.json")
                print(f"  ↩ Fallback: {len(contracte)} contracte din contracte.json (data.gov.ro inaccesibil)")
            except Exception as _fe:
                seap_debug.append(f"FALLBACK FAIL: {_fe}")

    # 3. Hotărâri Consiliu Local
    print("\n[3/6] Analizez hotărârile Consiliului Local...")
    stare_ant = incarca_stare_anterioara(CONFIG["fisier_stare"])
    rezultat_hcl = analizeaza_hcl(stare_ant)
    flags_hcl = rezultat_hcl["flags"]
    statistici_hcl = rezultat_hcl["statistici"]

    # §3.1 Curtea de Conturi — rapoarte audit UAT (cache TTL_CURTEA_CONTURI_DAYS)
    rapoarte_cc = fetch_curtea_de_conturi(
        uat_nume=CONFIG.get("uat_search", "Pantelimon"),
    )
    CONFIG["_rapoarte_cc"] = rapoarte_cc

    # §3.2 ANI — declarații avere aleși locali (cache TTL_ANI_DAYS)
    declaratii_ani = fetch_declaratii_avere(
        uat=CONFIG.get("uat_search", "Pantelimon"),
    )
    CONFIG["_declaratii_ani"] = declaratii_ani

    # §3.4 TED Europa — cross-referențiere contracte mari (cache TTL_TED_DAYS)
    ted_notices = search_ted_for_buyer(
        cif_buyer=CONFIG["cui"],
    )
    CONFIG["_ted_notices"] = ted_notices

    # §3.5 MOL primărie — rectificări bugetare și HCL (cache TTL_MOL_DAYS)
    mol_intrari = fetch_mol_primarie()
    CONFIG["_mol_intrari"] = mol_intrari

    # §3.3 Proiecte PNRR
    pnrr_projects = fetch_pnrr_projects(
        cif_beneficiar=CONFIG.get("cui", "4420759"),
    )
    CONFIG["_pnrr_projects"] = pnrr_projects

    # Pasăm statisticile HCL în CONFIG pentru template
    CONFIG["_hcl_total"] = statistici_hcl.get("total_hcl", 0)
    CONFIG["_hcl_ordinare"] = statistici_hcl.get("ordinare", 0)
    CONFIG["_hcl_extraordinare"] = statistici_hcl.get("extraordinare", 0)
    CONFIG["_hcl_pct"] = statistici_hcl.get("pct_extraordinare", 0)
    CONFIG["_hcl_ocr"] = statistici_hcl.get("ocr_rezumat", "")

    # 4. Red flags
    print("\n[4/6] Analizez red flags...")
    flags_contracte = analizeaza_red_flags(contracte, CONFIG)
    toate_flags = flags_contracte + flags_hcl
    # firme_openapi e construit în analizeaza_red_flags și pus în CONFIG["_firme_openapi"]
    firme_openapi = CONFIG.get("_firme_openapi", {})
    # Calculam scorul de transparenta
    rezultat_scor = calculeaza_scor_transparenta(toate_flags, contracte, statistici_hcl)
    CONFIG["_scor"] = rezultat_scor
    print(f"  ✓ Scor transparenta calculat: {rezultat_scor['scor']}/100")


    # 4b. Detectăm flags NOI față de rularea precedentă
    flags_noi = detecteaza_flags_noi(toate_flags, stare_ant)
    ids_curente = set((f.get("contract_id") or f.get("contract_numar") or "") + "_" + f.get("tip", "") for f in toate_flags)
    ids_anterioare = set(stare_ant.get("flags_anterioare", []))
    flags_rezolvate_n = len(ids_anterioare - ids_curente)
    data_anterioara_str = stare_ant.get("data_ultima_rulare", None)

    # Export delta.json — folosit de enhance.js pentru banner "ce e nou"
    data_curenta = datetime.now()
    delta = {
        "data_curenta": data_curenta.isoformat(),
        "data_anterioara": data_anterioara_str,
        "nereguli_noi": len(flags_noi),
        "nereguli_rezolvate": flags_rezolvate_n,
        "scor_transparenta": CONFIG.get("_scor", {}).get("scor"),
        "top_noi": [
            {"titlu": n["titlu"], "severitate": n["severitate"], "index": i}
            for i, n in enumerate(flags_noi[:3], 1)
        ],
    }
    with open("delta.json", "w", encoding="utf-8") as f:
        json.dump(delta, f, ensure_ascii=False, indent=2)
    print(f"  ✓ delta.json: {len(flags_noi)} nereguli noi, {flags_rezolvate_n} rezolvate")
    # Salvare/actualizare istoric_scor.json
    _scor_r = CONFIG.get("_scor", {})
    if _scor_r:
        try:
            with open("istoric_scor.json", "r", encoding="utf-8") as _fis:
                _istoric = json.load(_fis)
        except (FileNotFoundError, json.JSONDecodeError):
            _istoric = {"puncte": []}
        _luna = _scor_r["data"][:7]
        _istoric["puncte"] = [p for p in _istoric.get("puncte", []) if not p["data"].startswith(_luna)]
        _istoric["puncte"].append({"data": _scor_r["data"], "scor": _scor_r["scor"]})
        _istoric["puncte"] = sorted(_istoric["puncte"], key=lambda x: x["data"])[-24:]
        with open("istoric_scor.json", "w", encoding="utf-8") as _fis:
            json.dump(_istoric, _fis, ensure_ascii=False, indent=2)
        print(f"  ✓ Scor transparenta salvat: {_scor_r['scor']}/100 → istoric_scor.json")


    # 5. Raport HTML + export contracte.json
    print("\n[5/6] Generez raport HTML...")
    raport_html = genereaza_raport_html(budget, contracte, toate_flags, flags_noi, CONFIG)
    with open(CONFIG["fisier_raport"], "w", encoding="utf-8") as f:
        f.write(raport_html)
    print(f"  ✓ Raport salvat: {CONFIG['fisier_raport']}")

    # Pagini per furnizor (≥3 contracte)
    print("  [Furnizori] Generez pagini per furnizor...")
    from collections import defaultdict as _defaultdict
    import os as _os

    # risc_firma e construit în genereaza_raport_html; reconstruim minimal pentru pagini furnizori
    risc_firma = {}

    contracte_per_firma = _defaultdict(list)
    for c in contracte:
        if c.get("castigator"):
            contracte_per_firma[c["castigator"]].append(c)

    flags_per_firma = _defaultdict(list)
    for f in toate_flags:
        if f.get("furnizor") and f["furnizor"] != "Multiple":
            flags_per_firma[f["furnizor"]].append(f)

    # Adăugăm flaguri financiare din risc_firma (PUTINI_ANGAJATI, CIFRA_AFACERI etc.)
    # Acestea nu sunt în toate_flags (vin din firme_financiar.json, nu din SEAP).
    # Prin includerea lor în flags_per_firma, apar în paginile furnizori și
    # sunt trackuite de stare_anterioara.json → badge-ul NOU va funcționa automat.
    _FIN_TIPS_SET = {"ZERO ANGAJATI", "CIFRA AFACERI ZERO", "CIFRA AFACERI MULT SUB CONTRACT",
                     "CIFRA AFACERI SUB CONTRACT", "FOARTE PUTINI ANGAJATI"}
    for _furn_fin, _rd_fin in risc_firma.items():
        _existing_keys = {(f.get("tip",""), f.get("data",""))
                          for f in flags_per_firma.get(_furn_fin, [])}
        for _ff in _rd_fin.get("flags", []):
            if _ff.get("tip","") in _FIN_TIPS_SET:
                _k = (_ff.get("tip",""), _ff.get("data",""))
                if _k not in _existing_keys:
                    flags_per_firma[_furn_fin].append({
                        **_ff,
                        "furnizor": _furn_fin,
                        "titlu": _ff.get("titlu") or _ff.get("tip",""),
                        "descriere": _ff.get("titlu",""),
                    })
                    _existing_keys.add(_k)

    # B — Adăugăm flaguri MENTIUNI_PRESA_RISCANTE din mentiuni_presa_auto.json
    try:
        from monitorizare_presa import incarca_mentiuni_presa_auto, evalueaza_flag_presa
        import re as _re_presa
        _mentiuni_auto = incarca_mentiuni_presa_auto()
        if _mentiuni_auto:
            # Construim lookup CUI → furnizor (același mecanism ca pentru date financiare)
            _cui_to_furn_p = {}
            for _fp, _rdp in risc_firma.items():
                _cp = _re_presa.sub(r'^[Rr][Oo]\s*', '', str(_rdp.get("cui","")).strip()).replace(' ', '')
                if _cp and _cp.isdigit():
                    _cui_to_furn_p[_cp] = _fp
            _presa_added = 0
            for _cui_p, _mp in _mentiuni_auto.items():
                if not _mp.get('total'):
                    continue
                _furn_p = _cui_to_furn_p.get(str(_cui_p))
                if not _furn_p:
                    continue
                _flag_p = evalueaza_flag_presa(_mp)
                if not _flag_p:
                    continue
                _ex_tips_p = {f.get("tip","") for f in flags_per_firma.get(_furn_p, [])}
                if 'MENTIUNI PRESA RISCANTE' not in _ex_tips_p:
                    flags_per_firma[_furn_p].append({**_flag_p, "furnizor": _furn_p})
                    # Adăugăm și în risc_firma pentru a apărea în raport + chip filter
                    if _furn_p in risc_firma:
                        _ex_rf_tips = {f.get("tip","") for f in risc_firma[_furn_p].get("flags",[])}
                        if 'MENTIUNI PRESA RISCANTE' not in _ex_rf_tips:
                            risc_firma[_furn_p].setdefault("flags", []).append(_flag_p)
                    _presa_added += 1
            if _presa_added:
                print(f'  [OK] Presă: {_presa_added} firme cu flaguri MENTIUNI_PRESA_RISCANTE')
    except ImportError:
        pass  # monitorizare_presa.py opțional

    _os.makedirs("furnizori", exist_ok=True)
    index_furnizori = []
    for firma, contracte_firma in contracte_per_firma.items():
        if len(contracte_firma) < 3:
            continue
        slug = _slugify(firma)
        if not slug:
            continue
        flags_firma = flags_per_firma.get(firma, [])
        # Lookup mențiuni automate de presă pentru această firmă (prin CUI)
        _cui_firma = (contracte_firma[0].get("castigator_cui", "") or "") if contracte_firma else ""
        _mentiuni_auto_firma = []
        if _cui_firma and _mentiuni_presa_auto_by_cui:
            _mp_entry = _mentiuni_presa_auto_by_cui.get(str(_cui_firma), {})
            _mentiuni_auto_firma = _mp_entry.get('mentiuni', [])
        # Firme legate (rețele) — lookup prin CUI
        _firme_legate_r = []
        if _retea_firme and _cui_firma:
            try:
                from analizeaza_retele import gaseste_firme_legate as _gfl
                _firme_legate_r = _gfl(_cui_firma, _retea_firme)
            except ImportError:
                pass
        pagina_html = genereaza_pagina_furnizor(
            firma, slug, flags_firma, contracte_firma, CONFIG,
            mentiuni=_mentiuni_media.get(firma, []),
            mentiuni_auto=_mentiuni_auto_firma if _mentiuni_auto_firma else None,
            firme_legate=_firme_legate_r if _firme_legate_r else None,
        )
        with open(f"furnizori/{slug}.html", "w", encoding="utf-8") as fh:
            fh.write(pagina_html)
        index_furnizori.append({
            "nume": firma, "slug": slug,
            "count": len(contracte_firma),
            "valoare": sum(c.get("valoare_ron", 0) for c in contracte_firma),
            "flags_critic": sum(1 for f in flags_firma if f.get("severitate") == "CRITIC"),
            "flags_major":  sum(1 for f in flags_firma if f.get("severitate") == "MAJOR"),
            "flags_mediu":  sum(1 for f in flags_firma if f.get("severitate") == "MEDIU"),
        })

    if index_furnizori:
        index_html = genereaza_index_furnizori(index_furnizori)
        with open("furnizori/index.html", "w", encoding="utf-8") as fh:
            fh.write(index_html)
        print(f"  ✓ {len(index_furnizori)} pagini furnizori generate în furnizori/")
    else:
        print("  ℹ️  Niciun furnizor cu ≥3 contracte găsit.")

    # §3.6 Geocodare firme furnizoare → firme_geocoded.json (folosit de harta.html)
    if firme_openapi:
        # Construiește cui_valori și cui_contracte din index_furnizori și contracte
        cui_valori_map: dict = {}
        cui_contracte_map: dict = {}
        for c in contracte:
            cui_c = c.get("castigator_cui", "")
            if cui_c:
                cui_valori_map[cui_c] = cui_valori_map.get(cui_c, 0) + c.get("valoare_ron", 0)
                cui_contracte_map[cui_c] = cui_contracte_map.get(cui_c, 0) + 1
        geocodeaza_firme(
            firme_openapi=firme_openapi,
            cui_valori=cui_valori_map,
            cui_contracte=cui_contracte_map,
            index_furnizori=index_furnizori,
        )
    else:
        # Fără openapi.ro key → scriem placeholder gol pentru a nu rupe harta.html
        import json as _json_geo
        if not os.path.exists("firme_geocoded.json"):
            with open("firme_geocoded.json", "w", encoding="utf-8") as _fg:
                _json_geo.dump([], _fg)
            print("  ℹ️  firme_geocoded.json placeholder gol (lipsă openapi.ro key)")

    # Regenerare sitemap.xml cu toate paginile (statice + furnizori)
    sitemap_xml = genereaza_sitemap(index_furnizori)
    with open("sitemap.xml", "w", encoding="utf-8") as fh:
        fh.write(sitemap_xml)
    print(f"  ✓ sitemap.xml actualizat ({len(index_furnizori)} pagini furnizori + 9 statice)")

    # §5.7 Generare og-image.png cu statisticile curente (pentru share social media)
    _scor_val = CONFIG.get("_scor", {}).get("scor")
    _val_mil = round(sum(c.get("valoare_ron", 0) for c in contracte) / 1_000_000, 1)
    genereaza_og_image(
        n_flags=len(toate_flags),
        n_critic=sum(1 for f in toate_flags if f.get("severitate") == "CRITIC"),
        valoare_mil=_val_mil,
        scor=_scor_val,
    )

    # Export feed.xml (Atom) pentru cititori RSS / jurnaliști
    feed_xml = genereaza_feed_atom(toate_flags, datetime.now())
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(feed_xml)
    print(f"  ✓ Feed Atom salvat: feed.xml (top {min(20, len(toate_flags))} nereguli)")

    # §5.1 Press kit auto-generat pentru jurnaliști / ONG-uri
    genereaza_press_kit(
        nereguli=toate_flags,
        contracte=contracte,
        scor=CONFIG.get("_scor", {}),
        config=CONFIG,
    )

    # Export raport.json (endpoint public pentru jurnalisti / integari externe)
    _n_main = len(contracte)
    _val_main = sum(c.get("valoare_ron", 0) for c in contracte)
    _index_cui_main = construieste_index_cui(contracte)
    raport_json_main = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "entity": {"name": CONFIG["nume_entitate"], "cif": CONFIG["cui"], "judet": CONFIG.get("judet", "Ilfov")},
        "totals": {"flags": len(toate_flags), "signals": len(toate_flags),
                   "contracts_analyzed": _n_main,
                   "contracts_with_signals": numara_contracte_cu_semnale(toate_flags, contracte),
                   "total_value_ron": _val_main,
                   "by_severity": {"CRITIC": sum(1 for f in toate_flags if f.get("severitate") == "CRITIC"),
                                   "MAJOR": sum(1 for f in toate_flags if f.get("severitate") == "MAJOR"),
                                   "MEDIU": sum(1 for f in toate_flags if f.get("severitate") == "MEDIU")}},
        "flags": [{"id": i, "severity": fl.get("severitate",""), "title": fl.get("titlu",""),
                   "explanation": fl.get("descriere",""), "supplier": fl.get("furnizor",""),
                   # a treia cale care scrie raport.json — lipsea CUI-ul aici,
                   # deci fișierul public ieșea cu supplier_cif gol pe toate flagurile
                   "supplier_cif": _cui_pentru_furnizor(fl.get("furnizor",""),
                                                        fl.get("cif_furnizor",""),
                                                        _index_cui_main),
                   "sum_ron": fl.get("valoare",0) or 0, "date": fl.get("data",""),
                   "contract_id": (fl.get("contract_id") or fl.get("contract_numar") or ""),
                   "procedure": fl.get("tip_procedura",""), "type": fl.get("tip",""),
                   "anchor": f"nereguli-{i}"}
                  for i, fl in enumerate(toate_flags, 1)],
        "scor_transparenta": CONFIG.get("_scor", {}),
        "legal_thresholds": {
            "products_services_ron_excl_vat": CONFIG["prag_servicii_furnizare"],
            "works_ron_excl_vat": CONFIG["prag_lucrari"],
            "verified_at": PRAGURI_LEGALE_VERIFICATE_LA,
            "source": PRAGURI_LEGALE_SURSA,
        },
        "seap_debug": seap_debug if 'seap_debug' in dir() else [],
    }
    with open("raport.json", "w", encoding="utf-8") as fout:
        json.dump(raport_json_main, fout, ensure_ascii=False, indent=2)
    print(f"  ✓ Raport JSON salvat: raport.json ({len(toate_flags)} nereguli)")
    # Export contracte.json pentru acces extern
    contracte_export = [{
        "id": c["id"],
        "titlu": c["titlu"][:80],
        "valoare": c["valoare_ron"],
        "data": c["data_publicare"],
        "tip": c["tip_procedura"],
        "firma": c["castigator"],
        "cui": c.get("castigator_cui", ""),
        "ofertanti": c.get("nr_ofertanti", 0),
    } for c in contracte]
    with open("contracte.json", "w", encoding="utf-8") as f:
        json.dump(contracte_export, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Contracte exportate: contracte.json ({len(contracte_export)} intrări)")

    # Export contracte.csv pentru jurnalisti / prelucrare spreadsheet
    csv_content = genereaza_contracte_csv(contracte_export)
    with open("contracte.csv", "w", encoding="utf-8", newline="") as f:
        f.write(csv_content)
    print(f"  ✓ Contracte exportate: contracte.csv ({len(contracte_export)} randuri)")

    # §1.1: Actualizează tabelul static din transparenta_pantelimon.html
    actualizeaza_tabel_contracte(contracte_export)
    # §2.5: Actualizează KPI valoare contracte (fix BUG-1/2/3/8/9)
    actualizeaza_kpi_seap(contracte_export)
    actualizeaza_kpi_buget_index(budget)
    actualizeaza_semnale_index(len(toate_flags), sum(1 for _f in toate_flags if _f.get("severitate") == "CRITIC"))
    # BUG-10: Actualizează contoare „N contracte · YYYY" din secțiunile de analiză
    actualizeaza_contoare_analiza(contracte_export)

    # 6. Salvare stare
    print("\n[6/6] Salvez starea...")
    hcl_urls_noi = rezultat_hcl.get("hcl_urls", [])
    salveaza_stare(CONFIG["fisier_stare"], toate_flags, contracte, hcl_urls_noi)
    print(f"  ✓ Stare salvata: {CONFIG['fisier_stare']}")

    if trimite_email and toate_flags:
        flags_noi = [f for f in toate_flags
                     if f.get("titlu") not in
                     [x.get("titlu") for x in stare_ant.get("flags_anterioare", [])]]
        if flags_noi:
            trimite_email_alerta(flags_noi, raport_html, CONFIG)

    print(f"\n{'='*60}")
    print(f"  FINALIZAT -- {len(toate_flags)} flags, {len(contracte)} contracte analizate")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

