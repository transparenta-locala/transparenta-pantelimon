"""Teste pentru site_shell.py — cadrul comun scris static în toate paginile (oct. 2026).

Înainte, meniul, banda de date și tema erau adăugate de enhance.js după încărcare:
conținutul „sărea” (CLS 0,29–0,38) și paginile nu aveau legături între ele fără JS.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from site_shell import (  # noqa: E402
    aplica_pe_text, banda_date_html, data_ro, header_html, prefix_pentru,
)

PAGINA = """<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="UTF-8">
<title>Constopograf Expert — Transparența Pantelimon</title>
<script src="../enhance.js" defer></script>
<link rel="icon" href="/favicon.ico" sizes="any">
</head>
<body>
<main><h1>Constopograf Expert</h1></main>
</body>
</html>"""

DELTA = {"date_seap_pana_la": "2026-10-15", "data_curenta": "2026-10-15T10:06:16", "nereguli_noi": 5}


def test_prefix_dupa_adancime():
    assert prefix_pentru("index.html") == ""
    assert prefix_pentru("furnizori/x.html") == "../"
    assert prefix_pentru("semnale/y.html") == "../"


def test_404_foloseste_cai_absolute():
    """GitHub Pages servește 404.html la orice adresă greșită (și /a/b/c)."""
    assert prefix_pentru("404.html") == "/"


def test_data_ro():
    assert data_ro("2026-10-15T10:06:16") == "15.10.2026"
    assert data_ro("2026-10-15", lunga=True) == "15 octombrie 2026"
    assert data_ro("") == ""


def test_aplica_insereaza_head_meniu_si_subsol():
    out = aplica_pe_text(PAGINA, "furnizori/constopograf-expert.html", DELTA)
    assert "<!--tp:head-->" in out and "<!--tp:header-->" in out and "<!--tp:footer-->" in out
    assert 'href="../assets/tp.css?v=' in out
    assert 'src="../enhance.min.js?v=' in out
    assert 'class="tp-nav"' in out
    # scriptul vechi, fără versiune, a fost scos (altfel s-ar încărca de două ori)
    assert 'src="../enhance.js"' not in out


def test_aplica_e_idempotent():
    o1 = aplica_pe_text(PAGINA, "furnizori/a.html", DELTA)
    o2 = aplica_pe_text(o1, "furnizori/a.html", DELTA)
    assert o1 == o2
    assert o2.count("<!--tp:header-->") == 1
    assert o2.count('rel="icon" href="../favicon.ico"') == 1


def test_meniul_marcheaza_pagina_activa():
    h = header_html("furnizori/x.html", "X", DELTA)
    assert 'href="../furnizori/index.html" class="active" aria-current="page">Firme' in h
    h2 = header_html("semnale/y.html", "Y", DELTA)
    assert 'href="../raport_transparenta.html" class="active" aria-current="page">Semnale' in h2


def test_breadcrumb_doar_pe_paginile_de_detaliu():
    assert "tp-breadcrumb" in header_html("furnizori/x.html", "Firma X", DELTA)
    assert "tp-breadcrumb" not in header_html("despre.html", "Despre", DELTA)
    assert "tp-breadcrumb" not in header_html("furnizori/index.html", "Firme", DELTA)


def test_banda_unica_cu_date_si_semnale_noi():
    b = banda_date_html("index.html", DELTA)
    assert "Date SEAP până la 15.10.2026" in b
    assert 'href="raport_transparenta.html#noi">5 semnale noi' in b
    assert banda_date_html("index.html", {}) == ""


def test_nav_de_rezerva_din_index_e_inlocuit():
    pagina = PAGINA.replace("<main>", '<a href="#main-content" class="skip-link">Salt</a>\n'
                            '<nav class="static-nav" id="x"><a href="index.html">A</a></nav>\n<main>')
    out = aplica_pe_text(pagina, "index.html", DELTA)
    assert "static-nav" not in out
    assert 'class="tp-nav"' in out


def test_subsolul_leaga_toate_sectiunile():
    out = aplica_pe_text(PAGINA, "index.html", DELTA)
    for href in ("raport_transparenta.html", "furnizori/index.html", "transparenta_pantelimon.html",
                 "harta.html", "retele.html", "modele.html", "petitie.html", "presa.html", "despre.html"):
        assert f'href="{href}"' in out
