"""
site_shell.py — „cadrul” comun al tuturor paginilor: <head>, meniu, bandă de date, subsol.

De ce există: până în oct. 2026, meniul, banda „Date SEAP până la…”, bannerul
„semnale noi” și toată tema vizuală erau adăugate de enhance.js DUPĂ încărcarea
paginii. Conținutul „sărea” (CLS 0,29–0,38 pe toate paginile), iar pentru
motoarele de căutare și pentru cine are JavaScript lent paginile nu aveau
legături între ele (fișa unei firme avea un singur link: „înapoi la raport”).

Acum cadrul e scris direct în HTML, între marcaje:

    <!--tp:head-->   … <!--/tp:head-->     înainte de </head>
    <!--tp:header--> … <!--/tp:header-->   imediat după <body>
    <!--tp:footer--> … <!--/tp:footer-->   înainte de </body>

`aplica_pe_site()` rulează la finalul monitorului (GitHub Actions) și în
workflow-ul „Build assets” — orice pagină din site (statică sau generată)
primește aceeași versiune a cadrului. Rularea e idempotentă: o pagină deja
la zi nu se rescrie.

Se poate rula și singur:  python site_shell.py
"""

from __future__ import annotations

import glob
import hashlib
import html as html_mod
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))

NAV_PRINCIPAL = [
    ("index.html", "Acasă"),
    ("raport_transparenta.html", "Semnale"),
    ("furnizori/index.html", "Firme"),
    ("transparenta_pantelimon.html", "Buget"),
    ("modele.html", "Modele de cereri"),
    ("despre.html", "Despre"),
]
NAV_MAI_MULT = [
    ("petitie.html", "Petiție"),
    ("harta.html", "Harta firmelor"),
    ("retele.html", "Rețele de firme"),
    ("presa.html", "Pentru presă"),
]
NAV_EXTERN = [
    ("https://transparenta.eu/entities/4420759", "Date ANAF (transparenta.eu)"),
    ("https://github.com/transparenta-locala/transparenta-pantelimon", "Codul sursă (GitHub)"),
]

# Fonturile din primul ecran (restul se încarcă la nevoie, prin unicode-range)
FONTURI_PRELOAD = (
    "assets/fonts/source-sans-3-latin-400-normal.woff2",
    "assets/fonts/source-serif-4-latin-600-normal.woff2",
)

# Paginile din rădăcină care NU primesc cadrul (pagina offline a service worker-ului
# trebuie să rămână minimă; fișierele de test/ciornă nu sunt publicate)
EXCLUSE = {"offline.html"}

_MARCAJE = {
    "head": ("<!--tp:head-->", "<!--/tp:head-->"),
    "header": ("<!--tp:header-->", "<!--/tp:header-->"),
    "footer": ("<!--tp:footer-->", "<!--/tp:footer-->"),
}

LUNI_RO = ("ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie",
           "august", "septembrie", "octombrie", "noiembrie", "decembrie")


# ──────────────────────────────────────────────────────────────────────────────
# Utilitare
# ──────────────────────────────────────────────────────────────────────────────

def data_ro(iso: str, lunga: bool = False) -> str:
    """'2026-10-15…' → '15.10.2026' (sau '15 octombrie 2026' cu lunga=True)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    if lunga:
        return f"{int(m.group(3))} {LUNI_RO[int(m.group(2)) - 1]} {m.group(1)}"
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"


def versiune_fisier(rel_path: str, root: str = ROOT) -> str:
    """Primele 8 caractere din SHA-1 al fișierului (pentru ?v= — cache busting)."""
    try:
        with open(os.path.join(root, rel_path), "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:8]
    except OSError:
        return "0"


def prefix_pentru(rel_path: str) -> str:
    """Calea relativă spre rădăcina site-ului: '' pentru index.html, '../' pentru furnizori/x.html.

    404.html e servită de GitHub Pages la ORICE adresă greșită (și /a/b/c), deci
    folosește căi absolute."""
    rel = rel_path.replace("\\", "/")
    if rel == "404.html":
        return "/"
    return "../" * rel.count("/")


def citeste_delta(root: str = ROOT) -> dict:
    try:
        with open(os.path.join(root, "delta.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _e(s) -> str:
    return html_mod.escape(str(s or ""), quote=True)


# ──────────────────────────────────────────────────────────────────────────────
# Fragmentele cadrului
# ──────────────────────────────────────────────────────────────────────────────

def head_html(rel_path: str, root: str = ROOT) -> str:
    p = prefix_pentru(rel_path)
    v_css = versiune_fisier("assets/tp.css", root)
    v_js = versiune_fisier("enhance.min.js", root)
    preload = "".join(
        f'<link rel="preload" href="{p}{f}" as="font" type="font/woff2" crossorigin>'
        for f in FONTURI_PRELOAD
    )
    # Tema (deschisă/întunecată) se aplică ÎNAINTE de prima desenare, altfel
    # pagina clipește din alb în negru la cei care au ales tema întunecată.
    tema = ("<script>(function(d){d.classList.add('tp-theme');try{var t=localStorage.getItem('tp-theme');"
            "if(t)d.dataset.tpTheme=t;else if(matchMedia('(prefers-color-scheme: dark)').matches)"
            "d.dataset.tpTheme='dark'}catch(e){}})(document.documentElement)</script>")
    return (
        f"{_MARCAJE['head'][0]}\n"
        f"{preload}\n"
        f'<link rel="stylesheet" href="{p}assets/tp.css?v={v_css}">\n'
        f'<link rel="icon" href="{p}favicon.ico" sizes="any">'
        f'<link rel="icon" href="{p}icon-192.png" type="image/png" sizes="192x192">'
        f'<link rel="apple-touch-icon" href="{p}apple-touch-icon.png">\n'
        f'<link rel="manifest" href="{p}manifest.webmanifest"><meta name="theme-color" content="#14263D">\n'
        f"{tema}\n"
        f'<script src="{p}enhance.min.js?v={v_js}" defer></script>\n'
        f"{_MARCAJE['head'][1]}"
    )


def _activ(rel_path: str, href: str) -> bool:
    rel = rel_path.replace("\\", "/")
    if href == "furnizori/index.html":
        return rel.startswith("furnizori/")
    if href == "raport_transparenta.html":
        return rel == href or rel.startswith("semnale/")
    return rel == href


def _breadcrumb(rel_path: str, titlu_pagina: str) -> str:
    rel = rel_path.replace("\\", "/")
    p = prefix_pentru(rel_path)
    if rel.startswith("furnizori/") and rel != "furnizori/index.html":
        parinte = (f"{p}furnizori/index.html", "Firme")
    elif rel.startswith("semnale/"):
        parinte = (f"{p}raport_transparenta.html", "Semnale")
    else:
        return ""
    return (
        '<nav class="tp-breadcrumb" aria-label="Breadcrumb"><ol>'
        f'<li><a href="{p}index.html">Acasă</a></li>'
        f'<li><a href="{parinte[0]}">{parinte[1]}</a></li>'
        f'<li aria-current="page">{_e(titlu_pagina)}</li>'
        "</ol></nav>"
    )


def banda_date_html(rel_path: str, delta: dict) -> str:
    """O singură bandă (înainte erau două: „semnale noi” + „Date SEAP până la”)."""
    p = prefix_pentru(rel_path)
    bucati = []
    seap = data_ro(delta.get("date_seap_pana_la", ""))
    if seap:
        bucati.append(f"<strong>Date SEAP până la {seap}</strong>")
    analiza = data_ro(delta.get("data_curenta", ""))
    if analiza:
        bucati.append(f"analiză automată din {analiza}")
    noi = int(delta.get("nereguli_noi") or 0)
    if noi > 0:
        cuvant = "semnal nou" if noi == 1 else "semnale noi"
        bucati.append(f'<a href="{p}raport_transparenta.html#noi">{noi} {cuvant} față de analiza anterioară</a>')
    if not bucati:
        return ""
    bucati.append(f'<a href="{p}despre.html#schimbare-surse">Despre date</a>')
    return ('<div class="tp-data-band" role="note"><div class="tp-data-band-in">'
            + ' <span aria-hidden="true">·</span> '.join(bucati)
            + "</div></div>")


def header_html(rel_path: str, titlu_pagina: str = "", delta: dict | None = None) -> str:
    p = prefix_pentru(rel_path)
    delta = delta or {}

    def link(href, text):
        if _activ(rel_path, href):
            return f'<a href="{p}{href}" class="active" aria-current="page">{text}</a>'
        return f'<a href="{p}{href}">{text}</a>'

    principale = "".join(link(h, t) for h, t in NAV_PRINCIPAL)
    mai_mult = "".join(link(h, t) for h, t in NAV_MAI_MULT) + "".join(
        f'<a href="{h}" target="_blank" rel="noopener">{t}</a>' for h, t in NAV_EXTERN
    )
    return (
        f"{_MARCAJE['header'][0]}\n"
        '<a class="tp-skip-link" href="#main-content">Salt la conținut</a>\n'
        '<nav class="tp-nav" aria-label="Navigare principală"><div class="tp-nav-inner">'
        f'<a href="{p}index.html" class="tp-nav-brand">Transparența Pantelimon<small>Inițiativă civică</small></a>'
        '<button class="tp-hamburger" id="tp-hamburger" type="button" aria-label="Meniu" aria-expanded="false" '
        'aria-controls="tp-nav-links"><span></span><span></span><span></span></button>'
        f'<div class="tp-nav-links" id="tp-nav-links">{principale}'
        f'<details class="tp-more"><summary>Mai mult</summary><div class="tp-more-list">{mai_mult}</div></details>'
        "</div>"
        '<button class="tp-theme-toggle" id="tp-theme-btn" type="button" aria-label="Comută tema luminoasă/întunecată" '
        'title="Temă luminoasă / întunecată"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20">'
        '<circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="1.8"/>'
        '<path d="M10 2a8 8 0 0 1 0 16z" fill="currentColor"/></svg></button>'
        "</div></nav>\n"
        f"{banda_date_html(rel_path, delta)}\n"
        f"{_breadcrumb(rel_path, titlu_pagina)}\n"
        f"{_MARCAJE['header'][1]}"
    )


def footer_html(rel_path: str) -> str:
    p = prefix_pentru(rel_path)
    site = [
        ("raport_transparenta.html", "Semnale"), ("furnizori/index.html", "Firme"),
        ("transparenta_pantelimon.html", "Buget"), ("harta.html", "Harta firmelor"),
        ("retele.html", "Rețele de firme"), ("modele.html", "Modele de cereri"),
        ("petitie.html", "Petiție"), ("presa.html", "Pentru presă"),
        ("despre.html", "Despre și metodologie"), ("gdpr.html", "Date personale"),
    ]
    date = [
        ("raport.json", "raport.json"), ("contracte.csv", "contracte.csv"),
        ("contracte.json", "contracte.json"), ("feed.xml", "Flux RSS"),
    ]
    lista = lambda xs: "".join(f'<li><a href="{p}{h}">{t}</a></li>' for h, t in xs)
    return (
        f"{_MARCAJE['footer'][0]}\n"
        '<footer class="tp-site-footer"><div class="tp-site-footer-in">'
        f'<div><strong>Transparența Pantelimon</strong><p>Inițiativă civică. Inițiatorul este membru USR Pantelimon; '
        'proiectul nu este un proiect oficial al partidului. Monitorizare bazată exclusiv pe date publice oficiale '
        '(SEAP, ANAF/MF, Consiliul Local). Semnalele sunt indicatori automați, nu concluzii juridice.</p></div>'
        f'<nav aria-label="Paginile site-ului"><ul>{lista(site)}</ul></nav>'
        f'<nav aria-label="Date deschise"><ul>{lista(date)}'
        '<li><a href="https://github.com/transparenta-locala/transparenta-pantelimon" target="_blank" rel="noopener">Cod sursă</a></li>'
        "</ul></nav>"
        "</div></footer>\n"
        f"{_MARCAJE['footer'][1]}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Aplicare pe o pagină
# ──────────────────────────────────────────────────────────────────────────────

# Elemente pe care cadrul le înlocuiește (scoase din afara marcajelor)
_DE_SCOS_HEAD = [
    re.compile(r'[ \t]*<script\s+src="(?:\.\./)*enhance(?:\.min)?\.js(?:\?v=\w+)?"\s+defer\s*>\s*</script>[ \t]*\n?', re.I),
    re.compile(r'[ \t]*<link\s+rel="(?:icon|apple-touch-icon|manifest)"[^>]*>[ \t]*\n?', re.I),
    re.compile(r'[ \t]*<meta\s+name="theme-color"[^>]*>[ \t]*\n?', re.I),
    re.compile(r'[ \t]*<link\s+rel="preload"\s+href="/?assets/fonts/[^"]+"[^>]*>[ \t]*\n?', re.I),
]
def rand_distribuie_html(url: str, text: str) -> str:
    """Rândul „Distribuie” al fișelor de firmă și al paginilor de semnal, scris static.

    Înainte îl insera enhance.js după încărcare (mic CLS, ~0,02). Markup-ul e același
    ca în buildShareRow() din enhance.js; acolo se leagă doar butonul „Copiază link”
    (data-url), iar rândul se mai construiește din JS numai dacă lipsește din pagină.
    """
    from urllib.parse import quote
    wa = "https://wa.me/?text=" + quote(f"{text} {url}", safe="")
    fb = "https://www.facebook.com/sharer/sharer.php?u=" + quote(url, safe="")
    return (
        f'<div class="tp-share no-print tp-share-page" data-tp-share="1" data-url="{_e(url)}">'
        '<span class="tp-share-lbl">Distribuie:</span>'
        f'<a class="tp-sh-wa" href="{_e(wa)}" target="_blank" rel="noopener noreferrer" aria-label="Distribuie pe WhatsApp">WhatsApp</a>'
        f'<a class="tp-sh-fb" href="{_e(fb)}" target="_blank" rel="noopener noreferrer" aria-label="Distribuie pe Facebook">Facebook</a>'
        '<button type="button" class="tp-sh-copy">Copiază link</button></div>'
    )


# Navigarea de rezervă scrisă de mână (index.html) — înlocuită de meniul static
_NAV_REZERVA = re.compile(
    r'[ \t]*<a href="#main-content" class="skip-link">[^<]*</a>\s*'
    r'<nav class="static-nav"[^>]*>.*?</nav>[ \t]*\n?', re.S)


def _inlocuieste_bloc(text: str, cheie: str, bloc: str, ancora: str) -> str:
    """Înlocuiește blocul dintre marcaje; dacă lipsește, îl inserează la ancoră."""
    start, end = _MARCAJE[cheie]
    i = text.find(start)
    if i != -1:
        j = text.find(end, i)
        if j != -1:
            return text[:i] + bloc + text[j + len(end):]
    if ancora == "head":
        k = text.find("</head>")
        return text if k == -1 else text[:k] + bloc + "\n" + text[k:]
    if ancora == "body-start":
        m = re.search(r"<body[^>]*>", text)
        if not m:
            return text
        return text[:m.end()] + "\n" + bloc + "\n" + text[m.end():]
    if ancora == "body-end":
        k = text.rfind("</body>")
        return text if k == -1 else text[:k] + bloc + "\n" + text[k:]
    return text


def _titlu_pagina(text: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    if not m:
        m = re.search(r"<title>(.*?)</title>", text, re.S)
    t = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
    t = html_mod.unescape(re.sub(r"\s+", " ", t)).strip()
    return t.split(" — ")[0].strip()


def aplica_pe_text(text: str, rel_path: str, delta: dict | None = None, root: str = ROOT) -> str:
    k = text.find("</head>")
    if k == -1:
        return text
    # Curățăm din <head> (în afara marcajului nostru) elementele preluate de cadru
    cap, rest = text[:k], text[k:]
    s, e = _MARCAJE["head"]
    if s in cap:
        i = cap.find(s); j = cap.find(e, i)
        inainte, bloc, dupa = cap[:i], cap[i:j + len(e)], cap[j + len(e):]
    else:
        inainte, bloc, dupa = cap, "", ""
    for rx in _DE_SCOS_HEAD:
        inainte = rx.sub("", inainte)
        dupa = rx.sub("", dupa)
    # Scriptul din <body> (unele pagini îl aveau la final)
    for rx in _DE_SCOS_HEAD[:1]:
        rest = rx.sub("", rest)
    rest = _NAV_REZERVA.sub("", rest, count=1)
    text = inainte + bloc + dupa + rest

    text = _inlocuieste_bloc(text, "head", head_html(rel_path, root), "head")
    text = _inlocuieste_bloc(text, "header", header_html(rel_path, _titlu_pagina(text), delta), "body-start")
    text = _inlocuieste_bloc(text, "footer", footer_html(rel_path), "body-end")
    return text


def pagini_site(root: str = ROOT) -> list:
    out = []
    for pat in ("*.html", "furnizori/*.html", "semnale/*.html"):
        for f in sorted(glob.glob(os.path.join(root, pat))):
            rel = os.path.relpath(f, root).replace("\\", "/")
            if rel in EXCLUSE:
                continue
            out.append(rel)
    return out


def aplica_pe_site(root: str = ROOT, verbose: bool = True) -> int:
    """Aplică cadrul pe toate paginile; întoarce câte fișiere s-au modificat."""
    delta = citeste_delta(root)
    modificate = 0
    for rel in pagini_site(root):
        path = os.path.join(root, rel)
        with open(path, encoding="utf-8") as fh:
            vechi = fh.read()
        nou = aplica_pe_text(vechi, rel, delta, root)
        if nou != vechi:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(nou)
            modificate += 1
    if verbose:
        print(f"  [OK] Cadrul comun (meniu, bandă de date, subsol) aplicat: {modificate} pagini actualizate")
    return modificate


if __name__ == "__main__":
    aplica_pe_site()
