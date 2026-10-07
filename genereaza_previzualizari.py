"""
genereaza_previzualizari.py — previzualizări de partajare (1200×630) și permalinkuri de semnal.

Rulează DUPĂ ce raportul și paginile de furnizor au fost generate (e apelat la
finalul `monitor_pantelimon.main()` și al regenerării offline; se poate rula și
singur: `python genereaza_previzualizari.py`).

Ce produce:
  og/semnale/<slug>.png      — imagine 1200×630 pentru fiecare semnal din raport
  og/furnizori/<slug>.png    — imagine 1200×630 pentru fiecare pagină de furnizor
  semnale/<slug>.html        — pagină ușoară (permalink) per semnal, cu meta og:*
                               proprii; linkul distribuit pe WhatsApp/Facebook
  semnale/harta.json         — ancora din raport (nereguli-N) → slug; citit de enhance.js
  furnizori/<slug>.html      — og:image / twitter:image înlocuite cu imaginea proprie
  delta.json                 — câmpul `date_seap_pana_la` (data celui mai recent contract)

De ce pagini separate per semnal: rețelele sociale ignoră fragmentul `#nereguli-N`,
deci toate linkurile spre raport ar arăta aceeași imagine. Slug-ul e derivat din
tip + id-urile contractelor, nu din numărul de ordine, ca linkurile deja distribuite
să rămână valabile după o regenerare în care ordinea semnalelor se schimbă.

Regulă de conținut: imaginile folosesc DOAR titlul semnalului așa cum apare în raport,
plus fapte verificabile (firmă, valoare, dată, id SEAP) și mențiunea că e un indicator
automat, nu o constatare juridică. Nu se trunchiază explicația (o explicație tăiată
își poate pierde exact propoziția care nuanțează).
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
from functools import lru_cache

BASE_URL = "https://transparenta-pantelimon.eu"
OG_W, OG_H = 1200, 630

_ROOT = os.path.dirname(os.path.abspath(__file__))
_FONT_DIR = os.path.join(_ROOT, "assets", "fonts")

CULORI_SEV = {"CRITIC": "#A23B2C", "MAJOR": "#8F5A1E", "MEDIU": "#5E6B78"}
# Etichete afișate (datele păstrează CRITIC/MAJOR/MEDIU)
ETICHETE_SEV = {"CRITIC": "Semnal CRITIC", "MAJOR": "Semnal MAJOR", "MEDIU": "Semnal MEDIU"}
FUNDAL = "#14263D"
DISCLAIMER = "Indicator automat din datele SEAP, nu o constatare juridică."

# Tipuri fără contract individual: data din card e data analizei, nu a contractului
_TIPURI_ANALIZA = {"RISC_SISTEMIC_FIRMA", "SEDINTE_EXTRAORDINARE_EXCESIVE", "hcl_sedinta_extraordinara"}


# ──────────────────────────────────────────────────────────────────────────────
# Utilitare pure
# ──────────────────────────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 60) -> str:
    """Aceeași regulă ca `_slugify` din monitor (diacritice → ASCII, spații → '-')."""
    s = (text or "").strip().lower()
    s = re.sub(r"[șş]", "s", s)
    s = re.sub(r"[țţ]", "t", s)
    s = re.sub(r"[ăâ]", "a", s)
    s = re.sub(r"[î]", "i", s)
    s = s.replace("_", " ")
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len].strip("-")


def _id_scurt(contract_id: str) -> str:
    """'achizitie-directa-2025-51666' → '2025-51666'; altfel slug-ul întreg (max 80)."""
    m = re.search(r"(\d{4})-(\d+)$", contract_id.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return slugify(re.sub(r"\.pdf$", "", contract_id.strip(), flags=re.I), 80)


def slug_semnal(semnal: dict) -> str:
    """Slug stabil pentru un semnal: tip + id-urile contractelor (sau firma / data)."""
    tip = slugify(semnal.get("tip", "") or "semnal", 40) or "semnal"
    ids = [p for p in (semnal.get("contract_id") or "").split(",") if p.strip()]
    ids = [p for p in ids if p.strip().lower() not in ("global", "hcl-meta")]
    firma = slugify(semnal.get("firma", "") or "", 40)
    if ids:
        scurte = [_id_scurt(p) for p in ids]
        if len(scurte) > 2:
            ident = "-".join(x for x in (firma, scurte[0]) if x)
        else:
            ident = "-".join(scurte)
    elif firma:
        ident = firma
    else:
        ident = semnal.get("data", "") or "fara-data"
    return f"{tip}-{ident}".strip("-")[:110].strip("-")


def fmt_lei(valoare: float) -> str:
    """270000 → '270.000 RON' (sumă exactă, verificabilă)."""
    try:
        v = int(round(float(valoare)))
    except (TypeError, ValueError):
        return ""
    return f"{v:,}".replace(",", ".") + " RON"


def fmt_data(iso: str) -> str:
    """'2025-01-16' → '16.01.2025'; lasă neschimbat ce nu e ISO."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else (iso or "")


def eticheta_data(semnal: dict) -> str:
    return "Analiză" if semnal.get("tip") in _TIPURI_ANALIZA else "Data"


def ids_seap(semnal: dict) -> list:
    """Numerele SEAP (partea numerică finală) ale contractelor semnalului."""
    out = []
    for p in (semnal.get("contract_id") or "").split(","):
        m = re.search(r"-(\d{3,})$", p.strip())
        if m:
            out.append(m.group(1))
    return out


def data_maxima_contracte(contracte: list) -> str:
    """Cea mai recentă dată ISO (AAAA-LL-ZZ) din lista de contracte; '' dacă lipsește."""
    date_ok = [str(c.get("data", ""))[:10] for c in contracte or []
               if re.match(r"^\d{4}-\d{2}-\d{2}", str(c.get("data", "")))]
    return max(date_ok) if date_ok else ""


# ──────────────────────────────────────────────────────────────────────────────
# Extragere din HTML-ul generat
# ──────────────────────────────────────────────────────────────────────────────

def extrage_semnale(raport_html: str) -> list:
    """Citește cardurile `.tp-flag` din raport: ancoră, severitate, titlu, explicație etc."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raport_html, "html.parser")
    semnale = []
    for card in soup.select("div.tp-flag[id]"):
        antet = card.find("div")
        titlu = ""
        if antet is not None:
            for span in antet.find_all("span"):
                t = span.get_text(" ", strip=True)
                if t.startswith("—") and t.lstrip("—").strip():
                    titlu = t.lstrip("—").strip()
                    break
        p = card.find("p")
        explicatie = p.get_text(" ", strip=True) if p else ""
        explicatie = re.sub(r"\s+([,.;:])", r"\1", explicatie)
        explicatie = re.sub(r"\s*Verifică pe termene\.ro →\s*$", "", explicatie).strip()
        try:
            suma = float(card.get("data-sum-ron") or 0)
        except ValueError:
            suma = 0.0
        semnale.append({
            "ancora": card.get("id"),
            "severitate": (card.get("data-severity") or "MEDIU").upper(),
            "firma": (card.get("data-supplier") or "").strip().strip("—").strip(),
            "cui": (card.get("data-supplier-cif") or "").strip(),
            "suma": suma,
            "data": (card.get("data-date") or "").strip(),
            "contract_id": (card.get("data-contract-id") or "").strip(),
            "tip": (card.get("data-type") or "").strip(),
            "titlu": titlu or "Semnal automat",
            "explicatie": explicatie,
        })
    return semnale


def atribuie_sluguri(semnale: list) -> list:
    """Adaugă `slug` fiecărui semnal; coliziunile primesc sufix -2, -3 (determinist)."""
    vazute: dict = {}
    for s in semnale:
        baza = slug_semnal(s)
        n = vazute.get(baza, 0) + 1
        vazute[baza] = n
        s["slug"] = baza if n == 1 else f"{baza}-{n}"
    return semnale


def extrage_furnizor(pagina_html: str) -> dict:
    """Din pagina furnizori/<slug>.html: nume, CUI, nr. contracte, valoare, semnale pe severitate."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(pagina_html, "html.parser")
    h1 = soup.find("h1")
    info = {"nume": h1.get_text(" ", strip=True) if h1 else "", "cui": "",
            "contracte": "", "valoare": "", "CRITIC": 0, "MAJOR": 0, "MEDIU": 0}
    meta = soup.find("div", class_="meta")
    if meta:
        m = re.search(r"CUI:\s*([0-9A-Za-z]+)", meta.get_text(" ", strip=True))
        if m:
            info["cui"] = m.group(1)
    for stat in soup.select("div.stat"):
        val = stat.find(class_="stat-val")
        lbl = stat.find(class_="stat-lbl")
        if not val or not lbl:
            continue
        v, l = val.get_text(" ", strip=True), lbl.get_text(" ", strip=True).lower()
        if l.startswith("contracte"):
            info["contracte"] = v
        elif l.startswith("valoare"):
            info["valoare"] = v
        else:
            for sev in ("CRITIC", "MAJOR", "MEDIU"):
                if sev.lower() in l:
                    try:
                        info[sev] = int(re.sub(r"\D", "", v) or 0)
                    except ValueError:
                        pass
    return info


# ──────────────────────────────────────────────────────────────────────────────
# Desen imagini
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    nume = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in (
        os.path.join(_FONT_DIR, nume),
        os.path.join("/usr/share/fonts/truetype/dejavu", nume),
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _incadreaza(draw, text: str, font, max_w: int, max_linii: int) -> list:
    """Împarte textul pe rânduri de lățime max_w; ultimul rând primește „…” dacă e tăiat."""
    cuvinte = (text or "").split()
    linii, curent = [], ""
    for cuv in cuvinte:
        test = f"{curent} {cuv}".strip()
        if draw.textlength(test, font=font) <= max_w:
            curent = test
            continue
        if curent:
            linii.append(curent)
        curent = cuv
        while draw.textlength(curent, font=font) > max_w and len(curent) > 1:
            curent = curent[:-1]
    if curent:
        linii.append(curent)
    if len(linii) > max_linii:
        linii = linii[:max_linii]
        ultim = linii[-1]
        while ultim and draw.textlength(ultim + "…", font=font) > max_w:
            ultim = ultim[:-1].rstrip()
        linii[-1] = ultim + "…"
    return linii


def _text_potrivit(draw, text, bold, marimi, max_w, max_linii):
    """Alege cea mai mare mărime de font la care textul încape în max_linii rânduri întregi."""
    for m in marimi:
        f = _font(m, bold)
        linii = _incadreaza(draw, text, f, max_w, 10)
        if len(linii) <= max_linii:
            return f, linii, m
    f = _font(marimi[-1], bold)
    return f, _incadreaza(draw, text, f, max_w, max_linii), marimi[-1]


def _cadru(data_seap: str):
    """Fundal comun: bandă de accent, antet, subsol cu domeniu + limita datelor."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (OG_W, OG_H), FUNDAL)
    d = ImageDraw.Draw(img)
    d.text((64, 44), "Transparența Pantelimon", fill="#A9B8CC", font=_font(24, True))
    d.line([(64, 552), (OG_W - 64, 552)], fill="#2B4364", width=2)
    d.text((64, 570), "Verifică singur: transparenta-pantelimon.eu", fill="#ffffff", font=_font(26, True))
    if data_seap:
        t = f"Date SEAP până la {fmt_data(data_seap)}"
        f = _font(22)
        d.text((OG_W - 64 - d.textlength(t, font=f), 574), t, fill="#A9B8CC", font=f)
    return img, d


def _salveaza(img, output: str) -> None:
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    # Paletă redusă → PNG de ~15-30 KB; determinist (aceleași date → aceiași octeți)
    from PIL import Image
    img.quantize(colors=64, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(
        output, "PNG", compress_level=9)


def deseneaza_semnal(semnal: dict, output: str, data_seap: str = "") -> bool:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    img, d = _cadru(data_seap)
    sev = semnal.get("severitate", "MEDIU")
    culoare = CULORI_SEV.get(sev, "#64748b")
    d.rectangle([(0, 0), (12, OG_H)], fill=culoare)

    # Eticheta de severitate
    f_sev = _font(24, True)
    eticheta = ETICHETE_SEV.get(sev, "Semnal automat")
    w = d.textlength(eticheta, font=f_sev)
    d.rounded_rectangle([(64, 92), (64 + w + 32, 134)], radius=21, fill=culoare)
    d.text((80, 99), eticheta, fill="#ffffff", font=f_sev)

    y = 160
    f_t, linii_t, m_t = _text_potrivit(d, semnal.get("titlu", ""), True, (50, 44, 38, 34), OG_W - 128, 3)
    for linie in linii_t:
        d.text((64, y), linie, fill="#ffffff", font=f_t)
        y += int(m_t * 1.22)

    firma = semnal.get("firma", "")
    if firma:
        y += 14
        f_f, linii_f, m_f = _text_potrivit(d, firma, False, (36, 32, 28), OG_W - 128, 2)
        for linie in linii_f:
            d.text((64, y), linie, fill="#9CC0E6", font=f_f)
            y += int(m_f * 1.25)

    fapte = []
    if semnal.get("suma"):
        fapte.append(fmt_lei(semnal["suma"]))
    if semnal.get("data"):
        fapte.append(f"{eticheta_data(semnal)}: {fmt_data(semnal['data'])}")
    # Fără numerele din exportul data.gov.ro: nu sunt codurile DA căutabile în SEAP
    # (e-licitatie.ro/…/view/<nr> dă pagină goală) — un identificator de nevăzut la sursă
    # ar contrazice „verifică singur”.
    y_fapte = max(y + 18, 420)
    y_fapte = min(y_fapte, 460)
    f_fp = _font(30, True)
    x = 64
    for i, fapt in enumerate(fapte):
        sep = 30 if i else 0
        if x + sep + d.textlength(fapt, font=f_fp) > OG_W - 64:
            break
        if i:
            d.text((x, y_fapte), "·", fill="#5E7593", font=f_fp)
            x += sep
        d.text((x, y_fapte), fapt, fill="#E6ECF4", font=f_fp)
        x += d.textlength(fapt, font=f_fp) + 18

    d.text((64, 508), DISCLAIMER, fill="#A9B8CC", font=_font(22))
    _salveaza(img, output)
    return True


def deseneaza_furnizor(info: dict, output: str, data_seap: str = "") -> bool:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    img, d = _cadru(data_seap)
    d.rectangle([(0, 0), (12, OG_H)], fill="#4D86C2")
    d.text((64, 100), "Contractele cu Primăria Pantelimon", fill="#9CC0E6", font=_font(30))

    y = 150
    f_n, linii_n, m_n = _text_potrivit(d, info.get("nume", ""), True, (60, 52, 44, 38), OG_W - 128, 2)
    for linie in linii_n:
        d.text((64, y), linie, fill="#ffffff", font=f_n)
        y += int(m_n * 1.2)
    if info.get("cui"):
        d.text((64, y + 6), f"CUI {info['cui']}", fill="#A9B8CC", font=_font(24))
        y += 40

    # Trei cifre mari
    y_st = max(340, y + 24)
    coloane = [
        (info.get("contracte", ""), "contracte"),
        (info.get("valoare", ""), "valoare totală"),
    ]
    n_semn = sum(int(info.get(s, 0) or 0) for s in ("CRITIC", "MAJOR", "MEDIU"))
    coloane.append((str(n_semn), "semnale automate"))
    x = 64
    for val, lbl in coloane:
        if not val:
            continue
        f_v = _font(52, True)
        d.text((x, y_st), val, fill="#ffffff", font=f_v)
        d.text((x, y_st + 66), lbl, fill="#A9B8CC", font=_font(24))
        x += max(d.textlength(val, font=f_v), d.textlength(lbl, font=_font(24))) + 72

    detalii = []
    for sev in ("CRITIC", "MAJOR", "MEDIU"):
        if info.get(sev):
            detalii.append(f"{info[sev]} {sev}")
    if detalii:
        d.text((64, y_st + 112), "Din care: " + " · ".join(detalii), fill="#C3CEDD", font=_font(24))
    d.text((64, 508), "Semnalele sunt indicatori automați, nu constatări juridice.", fill="#A9B8CC", font=_font(22))
    _salveaza(img, output)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Pagini
# ──────────────────────────────────────────────────────────────────────────────

def linkuri_seap_semnal(semnal: dict, linkuri: dict | None) -> list:
    """[(cod, url)] pentru contractele semnalului care au link SEAP real (fără repetări)."""
    out, vazute = [], set()
    for cid in (semnal.get("contract_id") or "").split(","):
        url, cod = (linkuri or {}).get(cid.strip(), ("", ""))
        if url and url not in vazute:
            vazute.add(url)
            out.append((cod or "SEAP", url))
    return out


def pagina_semnal(semnal: dict, slug_furnizor: str = "", data_seap: str = "",
                  linkuri: dict | None = None) -> str:
    """Permalink ușor pentru un semnal (meta og:* proprii + rezumat + link spre raport)."""
    e = html_mod.escape
    slug = semnal["slug"]
    titlu = semnal.get("titlu", "Semnal automat")
    firma = semnal.get("firma", "")
    titlu_pagina = f"{titlu} — {firma}" if firma else titlu
    fapte = []
    if semnal.get("suma"):
        fapte.append(fmt_lei(semnal["suma"]))
    if semnal.get("data"):
        fapte.append(f"{eticheta_data(semnal)}: {fmt_data(semnal['data'])}")
    descriere_og = " · ".join(([firma] if firma else []) + fapte + ["Indicator automat din date SEAP."])
    url = f"{BASE_URL}/semnale/{slug}.html"
    img = f"{BASE_URL}/og/semnale/{slug}.png"
    culoare = CULORI_SEV.get(semnal.get("severitate"), "#64748b")

    # Linkuri directe la anunțurile SEAP (sursa SEAP API); altfel căutare în lista publică
    # (id-urile vechi din data.gov.ro erau numere de rând, nu deschideau anunțul).
    directe = linkuri_seap_semnal(semnal, linkuri)
    cid0 = semnal.get("contract_id") or ""
    if directe:
        linkuri_seap = "".join(
            f'<a class="btn sec" href="{e(url)}" target="_blank" rel="noopener noreferrer">'
            f'{e(cod)} în SEAP ↗</a>' for cod, url in directe[:3])
        if len(directe) > 3:
            linkuri_seap += (f'<span class="lim" style="margin:0;align-self:center">'
                             f'+ încă {len(directe) - 3} în SEAP</span>')
    elif cid0.startswith("achizitie-directa"):
        linkuri_seap = ('<a class="btn sec" href="https://e-licitatie.ro/pub/direct-acquisitions/list/1" '
                        'target="_blank" rel="noopener noreferrer">Caută în SEAP ↗</a>')
    elif cid0.startswith("contract"):
        linkuri_seap = ('<a class="btn sec" href="https://e-licitatie.ro/pub/notices/ca-notices/list/1" '
                        'target="_blank" rel="noopener noreferrer">Caută în SEAP ↗</a>')
    else:
        linkuri_seap = ""
    link_firma = (f'<a class="btn sec" href="../furnizori/{e(slug_furnizor)}.html">Toate contractele firmei →</a>'
                  if slug_furnizor else "")
    limita = (f'<p class="lim">Date SEAP până la {e(fmt_data(data_seap))}. Semnalul e generat automat; '
              f'nu este o constatare juridică. Documentele procedurii trebuie verificate.</p>'
              if data_seap else
              '<p class="lim">Semnalul e generat automat; nu este o constatare juridică. '
              'Documentele procedurii trebuie verificate.</p>')

    return f"""<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titlu_pagina)} — Transparența Pantelimon</title>
<meta name="description" content="{e(descriere_og)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Transparența Pantelimon">
<meta property="og:locale" content="ro_RO">
<meta property="og:title" content="{e(titlu_pagina)}">
<meta property="og:description" content="{e(descriere_og)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{img}">
<link rel="canonical" href="{url}">
<script src="../enhance.js" defer></script>
<style>
body{{font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;margin:0;background:#F4F6F9;color:#15243A}}
main{{max-width:760px;margin:0 auto;padding:24px 16px 48px}}
.card{{background:var(--tp-bg,#fff);border:1px solid var(--tp-border,#D7DEE8);border-left:4px solid {culoare};border-radius:6px;padding:24px 26px}}
.sev{{display:inline-block;background:color-mix(in srgb,{culoare} 12%,transparent);color:{culoare};font-size:14px;font-weight:700;padding:3px 12px;border-radius:999px}}
h1{{font-size:1.9rem;line-height:1.2;margin:14px 0 6px}}
.firma{{font-size:1.1rem;color:var(--tp-link,#2A5C8F);font-weight:600;margin:0 0 12px}}
.fapte{{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:16px;color:var(--tp-muted,#55627A);margin:0 0 14px}}
.expl{{font-size:17px;line-height:1.6;margin:0 0 18px;max-width:62ch}}
.btns{{display:flex;flex-wrap:wrap;gap:8px}}
.btn{{display:inline-flex;align-items:center;min-height:44px;padding:0 16px;border-radius:8px;background:var(--tp-accent,#2A5C8F);color:#fff;text-decoration:none;font-size:15px;font-weight:600}}
.btn.sec{{background:var(--tp-tint,#E6EDF5);color:var(--tp-accent-d,#1D3F63)}}
.lim{{font-size:14px;color:var(--tp-muted,#55627A);margin:18px 0 0;line-height:1.5}}
</style>
</head>
<body>
<main id="main-content">
  <article class="card" data-tp-share-title="{e(titlu)}" data-tp-share-firma="{e(firma)}" data-tp-share-suma="{e(fmt_lei(semnal['suma']) if semnal.get('suma') else '')}">
    <span class="sev">{e(ETICHETE_SEV.get(semnal.get('severitate', ''), 'Semnal automat'))}</span>
    <h1>{e(titlu)}</h1>
    {f'<p class="firma">{e(firma)}</p>' if firma else ''}
    <div class="fapte">{''.join(f'<span>{e(x)}</span>' for x in fapte)}</div>
    <p class="expl">{e(semnal.get('explicatie', ''))}</p>
    <div class="btns">
      <a class="btn" href="../raport_transparenta.html#{e(semnal['ancora'])}">Vezi semnalul în raport →</a>
      {link_firma}
      {linkuri_seap}
    </div>
    {limita}
  </article>
</main>
</body>
</html>
"""


NOTA_RETRAS = ('<p class="lim" data-tp-retras="1"><strong>Acest semnal nu mai apare în ultima analiză</strong> '
               '(datele sau regulile de detectare s-au schimbat). Pagina rămâne pentru cine are linkul.</p>')


def marcheaza_semnal_retras(pagina_html: str) -> str:
    """Pentru un semnal care a dispărut: linkul spre raport fără ancoră + o notă vizibilă."""
    if 'data-tp-retras="1"' in pagina_html:
        return pagina_html
    out = re.sub(r'href="\.\./raport_transparenta\.html#[^"]*"', 'href="../raport_transparenta.html"', pagina_html)
    out = out.replace("Vezi semnalul în raport →", "Vezi raportul actual →")
    return out.replace("  </article>", f"    {NOTA_RETRAS}\n  </article>", 1)


def actualizeaza_og_furnizor(pagina_html: str, slug: str) -> str:
    """Înlocuiește imaginea generală cu cea a furnizorului în og:image și twitter:image."""
    img = f"{BASE_URL}/og/furnizori/{slug}.png"
    out = re.sub(r'(<meta property="og:image" content=")[^"]*(")', rf"\g<1>{img}\g<2>", pagina_html)
    out = re.sub(r'(<meta name="twitter:image" content=")[^"]*(")', rf"\g<1>{img}\g<2>", out)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrare
# ──────────────────────────────────────────────────────────────────────────────

def _scrie_daca_difera(path: str, continut: str) -> bool:
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == continut:
                return False
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(continut)
    return True


def actualizeaza_delta(data_seap: str, path: str = "delta.json") -> bool:
    if not data_seap:
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            delta = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        delta = {}
    if delta.get("date_seap_pana_la") == data_seap:
        return False
    delta["date_seap_pana_la"] = data_seap
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(delta, fh, ensure_ascii=False, indent=2)
    return True


def genereaza_toate(root: str = ".", cu_imagini: bool = True) -> dict:
    """Punct de intrare. Întoarce un rezumat {semnale, furnizori, imagini}."""
    root = os.path.abspath(root)
    p = lambda *a: os.path.join(root, *a)  # noqa: E731

    try:
        with open(p("contracte.json"), encoding="utf-8") as fh:
            contracte = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        contracte = []
    if not isinstance(contracte, list):
        contracte = []
    data_seap = data_maxima_contracte(contracte)
    linkuri = {c["id"]: (c["url"], c.get("cod", "")) for c in contracte
               if isinstance(c, dict) and c.get("id") and c.get("url")}
    actualizeaza_delta(data_seap, p("delta.json"))

    # Furnizori
    furnizori = {}
    dir_f = p("furnizori")
    if os.path.isdir(dir_f):
        for fn in sorted(os.listdir(dir_f)):
            if not fn.endswith(".html") or fn == "index.html":
                continue
            slug = fn[:-5]
            with open(os.path.join(dir_f, fn), encoding="utf-8") as fh:
                pagina = fh.read()
            info = extrage_furnizor(pagina)
            furnizori[slug] = info
            imagine_ok = True
            if cu_imagini:
                imagine_ok = deseneaza_furnizor(info, p("og", "furnizori", f"{slug}.png"), data_seap)
            if imagine_ok and os.path.exists(p("og", "furnizori", f"{slug}.png")):
                _scrie_daca_difera(os.path.join(dir_f, fn), actualizeaza_og_furnizor(pagina, slug))

    # Semnale
    try:
        with open(p("raport_transparenta.html"), encoding="utf-8") as fh:
            semnale = atribuie_sluguri(extrage_semnale(fh.read()))
    except FileNotFoundError:
        semnale = []
    harta = {}
    sluguri_active = set()
    for s in semnale:
        sluguri_active.add(s["slug"])
        harta[s["ancora"]] = s["slug"]
        slug_f = slugify(s.get("firma", ""))
        if slug_f not in furnizori:
            slug_f = ""
        if cu_imagini:
            deseneaza_semnal(s, p("og", "semnale", f"{s['slug']}.png"), data_seap)
        _scrie_daca_difera(p("semnale", f"{s['slug']}.html"), pagina_semnal(s, slug_f, data_seap, linkuri))

    # Paginile semnalelor dispărute rămân (linkurile deja distribuite nu dau 404), dar nu mai
    # trimit spre o ancoră care acum poate aparține altui semnal.
    if semnale and os.path.isdir(p("semnale")):
        for fn in os.listdir(p("semnale")):
            if fn.endswith(".html") and fn[:-5] not in sluguri_active:
                with open(p("semnale", fn), encoding="utf-8") as fh:
                    vechi = fh.read()
                _scrie_daca_difera(p("semnale", fn), marcheaza_semnal_retras(vechi))
    if semnale:
        _scrie_daca_difera(p("semnale", "harta.json"),
                           json.dumps(harta, ensure_ascii=False, indent=1, sort_keys=True) + "\n")

    rezumat = {"semnale": len(semnale), "furnizori": len(furnizori), "date_seap_pana_la": data_seap}
    print(f"  [OK] Previzualizări: {len(semnale)} semnale, {len(furnizori)} furnizori "
          f"(date SEAP până la {fmt_data(data_seap) or '—'})")
    return rezumat


if __name__ == "__main__":
    genereaza_toate(os.path.dirname(os.path.abspath(__file__)))
