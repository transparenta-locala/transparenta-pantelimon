"""Retușurile de după auditul din 26.10.2026: grafice la cerere (Buget), analiza pe categorii
fără stiluri inline, rândul „Distribuie” scris static, lista firmelor ca și carduri pe telefon."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import genereaza_previzualizari as gp  # noqa: E402
import monitor_pantelimon as m  # noqa: E402
import site_shell  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')


def _citeste(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _contract(cid, firma, valoare):
    return {"id": cid, "titlu": "Servicii de cadastru", "valoare_ron": valoare, "data_publicare": "2025-01-16",
            "tip_procedura": "", "castigator": firma, "castigator_cui": "25145252", "nr_ofertanti": 1,
            "cod_seap": "DA1", "url_seap": "https://e-licitatie.ro/x", "cheie_seap": f"da:{cid}",
            "tip_contract": "achizitie-directa"}


# ── Buget: Chart.js se încarcă la cerere ──────────────────────────────────────

def test_bugetul_nu_incarca_chartjs_odata_cu_pagina():
    html = _citeste("transparenta_pantelimon.html")
    assert '<script defer src="assets/vendor/chart.umd.min.js"></script>' not in html
    assert "IntersectionObserver" in html
    # toate cele 5 grafice au configurația înregistrată, nu un new Chart() la încărcare
    for cid in ("chartBugetCateg", "chartEvolutie", "chartPie", "chartProceduri", "chartLunar"):
        assert f"_GRAFICE.{cid} = {{" in html
        assert f'id="{cid}"' in html
    assert len(re.findall(r"new Chart\(", html)) == 1


def test_bugetul_pastreaza_tintele_functiilor_actualizeaza():
    """actualizeaza_kpi_seap / _tabel_contracte / _contoare_analiza modifică pagina prin regex."""
    html = _citeste("transparenta_pantelimon.html")
    assert re.search(r'<span class="val" id="kpi-val-total"[^>]*>[^<]*</span>', html)
    assert re.search(r'<tbody id="contracte-tbody">.*?</tbody>', html, re.S)
    assert re.search(r'<span[^>]*id="tp-nr-top10"[^>]*>\d+</span>', html)


# ── Raport: analiza pe categorii ──────────────────────────────────────────────

def test_analiza_pe_categorii_fara_stiluri_inline():
    c = [_contract("achizitie-directa-2025-1", "Constopograf Expert", 270000)]
    f = [{"severitate": "MAJOR", "titlu": "Un singur ofertant", "descriere": "x", "furnizor": "Constopograf Expert",
          "valoare": 270000, "data": "2025-01-16", "contract_id": "achizitie-directa-2025-1", "tip": "OFERTANT_UNIC"}]
    cfg = dict(m.CONFIG)
    cfg.update({"_offline_mode": True, "_scor": {}, "_hcl_total": 0})
    m.inregistreaza_linkuri_seap(c)
    html = m.genereaza_raport_html({"an": 2025}, c, f, [], cfg)
    a = html.index('<details class="tp-atp">')
    sectiune = html[a:html.index("</details>", a)]
    assert '<button type="button" class="tp-atp-card" data-tip="ofertant-unic" data-sev="MAJOR"' in sectiune
    assert 'aria-controls="atp-panel-ofertant-unic"' in sectiune
    assert '<div id="atp-panel-ofertant-unic" class="tp-atp-panel" data-sev="MAJOR" hidden>' in sectiune
    # singurul style rămas: lățimea barelor (procent din date)
    assert set(re.findall(r'style="([a-z-]+):', sectiune)) <= {"width"}
    assert "#777" not in sectiune and "#999" not in sectiune


def test_clasele_analizei_exista_in_tema():
    css = _citeste("assets/tp.css")
    for cls in (".tp-atp-grid", ".tp-atp-card", ".tp-atp-panel", ".tp-atp-close", ".tp-atp-bar", ".tp-atp-luna"):
        assert cls in css


def test_tintele_de_atingere_din_carduri_au_cel_putin_24px():
    css = _citeste("assets/tp.css")
    assert re.search(r"\.flag-firm a, \.flag-title, \.flag-code \{[^}]*min-height: 28px", css)
    assert re.search(r"\.tp-riskpill \{[^}]*min-height: 28px", css)
    assert "content-visibility: auto" not in css


# ── Rândul „Distribuie” scris static ──────────────────────────────────────────

def test_rand_distribuie_static():
    html = site_shell.rand_distribuie_html("https://transparenta-pantelimon.eu/furnizori/a & b.html", "Text „x”:")
    assert 'data-tp-share="1"' in html and 'class="tp-share no-print tp-share-page"' in html
    assert 'data-url="https://transparenta-pantelimon.eu/furnizori/a &amp; b.html"' in html
    assert "https://wa.me/?text=Text%20" in html
    assert "sharer.php?u=https%3A%2F%2Ftransparenta-pantelimon.eu%2Ffurnizori%2Fa%20%26%20b.html" in html
    assert '<button type="button" class="tp-sh-copy">Copiază link</button>' in html


def test_fisa_firmei_are_randul_distribuie_dupa_cifre():
    c = [_contract("achizitie-directa-2025-1", "Asociere SRL", 900_000)]
    html = m.genereaza_pagina_furnizor("Asociere SRL", "asociere-srl", [], c, m.CONFIG)
    assert html.count('data-tp-share="1"') == 1
    assert html.index('class="stats"') < html.index("tp-share-page") < html.index('class="tp-firm-links"')
    assert 'data-url="https://transparenta-pantelimon.eu/furnizori/asociere-srl.html"' in html


def test_pagina_semnalului_are_randul_distribuie():
    s = {"slug": "ofertant-unic-2025-1", "titlu": "Un singur ofertant", "firma": "Constopograf Expert",
         "suma": 270000, "data": "2025-01-16", "severitate": "MAJOR", "ancora": "nereguli-1",
         "contract_id": "achizitie-directa-2025-1", "explicatie": "x"}
    html = gp.pagina_semnal(s)
    assert html.count('data-tp-share="1"') == 1
    assert 'data-url="https://transparenta-pantelimon.eu/semnale/ofertant-unic-2025-1.html"' in html
    assert html.index('class="btns"') < html.index("tp-share-page")


def test_enhance_leaga_randul_static_in_loc_sa_insereze_altul():
    js = _citeste("enhance.js")
    assert "function leagaShareRow(row, url)" in js
    assert "$('.tp-share-page[data-url]')" in js


# ── Lista firmelor pe telefon ─────────────────────────────────────────────────

def test_lista_firmelor_devine_carduri_sub_640px():
    css = _citeste("assets/tp.css")
    bloc = css[css.index("/* Lista firmelor pe telefon"):]
    bloc = bloc[:bloc.index("\n}\n")]
    assert "@media (max-width: 640px)" in bloc
    assert ".tp-page-firme .tp-table tr { display: grid;" in bloc
    assert 'content: "Valoare contracte"' in bloc
