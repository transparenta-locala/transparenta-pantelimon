"""Previzualizări de partajare, permalinkuri de semnal, bandă date SEAP, meniu și partajare (fără rețea)."""
import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import genereaza_previzualizari as gp  # noqa: E402

try:
    from PIL import Image
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

CARD = '''
<div class="tp-flag" id="nereguli-{n}" data-severity="{sev}" data-supplier="{firma}"
     data-sum-ron="{suma}" data-date="{data}" data-contract-id="{cid}" data-type="{tip}"
     data-procedure="" data-supplier-cif="">
  <div style="display:flex">
    <span>#{n}</span><span>🔴</span><strong>[{sev}]</strong>
    <span style="font-weight:700">{firma_afis}</span>
    <span> — {titlu}</span>
    <span class="flag-arrow">▼ detalii</span>
  </div>
  <p><strong>{firma}</strong> a primit 2 contracte similare. Semnal automat. <a href="#">Verifică pe termene.ro →</a></p>
  <div class="flag-detail" style="display:none"></div>
</div>'''


def _card(n, **kw):
    d = dict(sev="CRITIC", firma="Constopograf Expert", suma="540000", data="2025-01-16",
             cid="achizitie-directa-2025-51666,achizitie-directa-2025-69059", tip="FRAGMENTARE",
             titlu="Semnal de posibilă fragmentare a contractelor")
    d.update(kw)
    d.setdefault("firma_afis", d["firma"] or "—")
    return CARD.format(n=n, **d)


RAPORT = "<html><body>" + _card(1) + _card(
    2, sev="MEDIU", firma="", firma_afis="—", suma="29508940", data="2025-07-29", cid="",
    tip="VALORI_IDENTICE_ACEEASI_ZI", titlu="Aceeași valoare la 3 firme, în aceeași zi") + _card(
    3, sev="CRITIC", suma="1890000", data="2026-09-25", cid="global", tip="RISC_SISTEMIC_FIRMA",
    titlu="Furnizor cu indicatori cumulați — 4 categorii") + "</body></html>"


# ── utilitare ────────────────────────────────────────────────────────────────

def test_slug_semnal_stabil_din_tip_si_contracte():
    s = {"tip": "FRAGMENTARE", "contract_id": "achizitie-directa-2025-51666,achizitie-directa-2025-69059"}
    assert gp.slug_semnal(s) == "fragmentare-2025-51666-2025-69059"


def test_slug_semnal_pastreaza_separatorii_din_tip():
    assert gp.slug_semnal({"tip": "OFERTANT_UNIC", "contract_id": "contract-2025-37370"}) == "ofertant-unic-2025-37370"


def test_slug_semnal_global_foloseste_firma():
    s = {"tip": "RISC_SISTEMIC_FIRMA", "contract_id": "global", "firma": "Constopograf Expert"}
    assert gp.slug_semnal(s) == "risc-sistemic-firma-constopograf-expert"


def test_slug_semnal_fara_contract_si_firma_foloseste_data():
    s = {"tip": "BURST_CONTRACTE", "contract_id": "", "firma": "", "data": "2025-12-03"}
    assert gp.slug_semnal(s) == "burst-contracte-2025-12-03"


def test_slug_hcl_distinge_documente_cu_nume_apropiate():
    a = {"tip": "hcl_sedinta_extraordinara", "contract_id": "P.V.-sedinta-extraodinara-cu-convocare-de-indata-din-26.11.2025.pdf"}
    b = {"tip": "hcl_sedinta_extraordinara", "contract_id": "P.V.-sedinta-extraodinara-cu-convocare-de-indata-din-21.11.2025.pdf"}
    assert gp.slug_semnal(a) != gp.slug_semnal(b)


def test_coliziunile_primesc_sufix_determinist():
    s = gp.atribuie_sluguri([{"tip": "X", "contract_id": "a-2025-1"}, {"tip": "X", "contract_id": "a-2025-1"}])
    assert [x["slug"] for x in s] == ["x-2025-1", "x-2025-1-2"]


def test_fmt_lei_si_data():
    assert gp.fmt_lei(270000) == "270.000 RON"
    assert gp.fmt_lei(1890000.4) == "1.890.000 RON"
    assert gp.fmt_data("2026-03-30") == "30.03.2026"


def test_data_maxima_contracte():
    c = [{"data": "2025-01-08"}, {"data": "2026-03-30"}, {"data": ""}, {"data": "nu"}]
    assert gp.data_maxima_contracte(c) == "2026-03-30"
    assert gp.data_maxima_contracte([]) == ""


def test_eticheta_data_pentru_semnale_de_analiza():
    assert gp.eticheta_data({"tip": "RISC_SISTEMIC_FIRMA"}) == "Analiză"
    assert gp.eticheta_data({"tip": "OFERTANT_UNIC"}) == "Data"


# ── extragere ────────────────────────────────────────────────────────────────

def test_extrage_semnale_din_carduri():
    s = gp.extrage_semnale(RAPORT)
    assert [x["ancora"] for x in s] == ["nereguli-1", "nereguli-2", "nereguli-3"]
    assert s[0]["titlu"] == "Semnal de posibilă fragmentare a contractelor"
    assert s[0]["suma"] == 540000.0
    assert "termene.ro" not in s[0]["explicatie"]


def test_titlul_nu_e_confundat_cu_firma_lipsa():
    s = gp.extrage_semnale(RAPORT)[1]
    assert s["firma"] == ""
    assert s["titlu"] == "Aceeași valoare la 3 firme, în aceeași zi"


def test_titlu_cu_liniuta_interioara_ramane_intreg():
    s = gp.extrage_semnale(RAPORT)[2]
    assert s["titlu"] == "Furnizor cu indicatori cumulați — 4 categorii"


def test_extrage_furnizor_din_pagina_reala():
    with open(os.path.join(REPO_ROOT, "furnizori", "constopograf-expert.html"), encoding="utf-8") as fh:
        info = gp.extrage_furnizor(fh.read())
    assert info["nume"] == "Constopograf Expert"
    assert info["cui"] == "25145252"
    assert info["contracte"] == "7"
    assert info["CRITIC"] >= 1


# ── pagini ───────────────────────────────────────────────────────────────────

def test_pagina_semnal_are_meta_og_proprii():
    s = gp.atribuie_sluguri(gp.extrage_semnale(RAPORT))[0]
    html = gp.pagina_semnal(s, "constopograf-expert", "2026-03-30")
    slug = s["slug"]
    assert f'og:url" content="https://transparenta-pantelimon.eu/semnale/{slug}.html"' in html
    assert f'og:image" content="https://transparenta-pantelimon.eu/og/semnale/{slug}.png"' in html
    assert 'href="../raport_transparenta.html#nereguli-1"' in html
    assert 'href="../furnizori/constopograf-expert.html"' in html
    assert "Date SEAP până la 30.03.2026" in html
    assert "nu este o constatare juridică" in html
    assert "view/51666" in html


def test_pagina_semnal_fara_redirect_meta():
    """Facebook urmează <meta refresh> și ar lua imaginea paginii-țintă."""
    s = gp.atribuie_sluguri(gp.extrage_semnale(RAPORT))[0]
    assert "http-equiv" not in gp.pagina_semnal(s).lower()


def test_semnal_retras_pierde_ancora_si_primeste_nota():
    s = gp.atribuie_sluguri(gp.extrage_semnale(RAPORT))[0]
    out = gp.marcheaza_semnal_retras(gp.pagina_semnal(s))
    assert "#nereguli-" not in out
    assert "nu mai apare în ultima analiză" in out
    assert gp.marcheaza_semnal_retras(out) == out


def test_actualizeaza_og_furnizor():
    html = ('<meta property="og:image" content="https://transparenta-pantelimon.eu/og-image.png">'
            '<meta name="twitter:image" content="https://transparenta-pantelimon.eu/og-image.png">')
    out = gp.actualizeaza_og_furnizor(html, "abc")
    assert out.count("/og/furnizori/abc.png") == 2
    assert "og-image.png" not in out


BANNED = re.compile(r"nereguli|ilegal|fraud|coinciden|artificial|peste pragul legal|creștere între versiuni", re.I)


def test_textele_generate_nu_contin_formulari_interzise():
    s = gp.atribuie_sluguri(gp.extrage_semnale(RAPORT))
    for x in s:
        html = gp.pagina_semnal(x, "", "2026-03-30")
        vizibil = re.sub(r'(href|id|content)="[^"]*"', "", html)
        assert not BANNED.search(vizibil.replace(x["explicatie"], "")), x["slug"]


# ── orchestrare pe o copie ───────────────────────────────────────────────────

@pytest.fixture
def repo_mic(tmp_path):
    (tmp_path / "furnizori").mkdir()
    pagina = _citeste("furnizori", "constopograf-expert.html")
    # starea de după monitor: imaginea generală (previzualizările o înlocuiesc)
    pagina = re.sub(r"https://transparenta-pantelimon\.eu/og/furnizori/[a-z0-9-]+\.png",
                    "https://transparenta-pantelimon.eu/og-image.png", pagina)
    (tmp_path / "furnizori" / "constopograf-expert.html").write_text(pagina, encoding="utf-8")
    (tmp_path / "raport_transparenta.html").write_text(RAPORT, encoding="utf-8")
    (tmp_path / "contracte.json").write_text(json.dumps([{"data": "2026-03-30"}, {"data": "2025-01-01"}]), encoding="utf-8")
    (tmp_path / "delta.json").write_text(json.dumps({"scor_transparenta": 37}), encoding="utf-8")
    return tmp_path


def test_genereaza_toate_fara_imagini(repo_mic):
    rez = gp.genereaza_toate(str(repo_mic), cu_imagini=False)
    assert rez == {"semnale": 3, "furnizori": 1, "date_seap_pana_la": "2026-03-30"}
    harta = json.loads((repo_mic / "semnale" / "harta.json").read_text(encoding="utf-8"))
    assert harta["nereguli-1"] == "fragmentare-2025-51666-2025-69059"
    assert (repo_mic / "semnale" / "fragmentare-2025-51666-2025-69059.html").exists()
    delta = json.loads((repo_mic / "delta.json").read_text(encoding="utf-8"))
    assert delta["date_seap_pana_la"] == "2026-03-30" and delta["scor_transparenta"] == 37
    # fără imagine, pagina furnizorului păstrează imaginea generală
    assert "og-image.png" in (repo_mic / "furnizori" / "constopograf-expert.html").read_text(encoding="utf-8")


@pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
def test_genereaza_toate_cu_imagini(repo_mic):
    gp.genereaza_toate(str(repo_mic))
    png = repo_mic / "og" / "semnale" / "fragmentare-2025-51666-2025-69059.png"
    assert Image.open(png).size == (1200, 630)
    assert Image.open(repo_mic / "og" / "furnizori" / "constopograf-expert.png").size == (1200, 630)
    pagina = (repo_mic / "furnizori" / "constopograf-expert.html").read_text(encoding="utf-8")
    assert "/og/furnizori/constopograf-expert.png" in pagina


@pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
def test_imaginile_sunt_deterministe(repo_mic):
    gp.genereaza_toate(str(repo_mic))
    png = repo_mic / "og" / "semnale" / "fragmentare-2025-51666-2025-69059.png"
    a = png.read_bytes()
    gp.genereaza_toate(str(repo_mic))
    assert png.read_bytes() == a


def test_semnal_disparut_ramane_dar_fara_ancora(repo_mic):
    gp.genereaza_toate(str(repo_mic), cu_imagini=False)
    (repo_mic / "raport_transparenta.html").write_text("<html><body>" + _card(1) + "</body></html>", encoding="utf-8")
    gp.genereaza_toate(str(repo_mic), cu_imagini=False)
    vechi = (repo_mic / "semnale" / "risc-sistemic-firma-constopograf-expert.html").read_text(encoding="utf-8")
    assert "#nereguli-" not in vechi


# ── fișierele din repo ───────────────────────────────────────────────────────

def _citeste(*parti):
    with open(os.path.join(REPO_ROOT, *parti), encoding="utf-8") as fh:
        return fh.read()


def test_fisiere_generate_in_repo_sunt_coerente():
    harta = json.loads(_citeste("semnale", "harta.json"))
    raport = _citeste("raport_transparenta.html")
    for ancora, slug in harta.items():
        assert f'id="{ancora}"' in raport
        assert os.path.exists(os.path.join(REPO_ROOT, "semnale", f"{slug}.html"))
        assert os.path.exists(os.path.join(REPO_ROOT, "og", "semnale", f"{slug}.png"))


def test_fisele_de_furnizor_au_imagine_proprie():
    for fn in os.listdir(os.path.join(REPO_ROOT, "furnizori")):
        if fn.endswith(".html") and fn != "index.html":
            slug = fn[:-5]
            assert f"/og/furnizori/{slug}.png" in _citeste("furnizori", fn), fn
            assert os.path.exists(os.path.join(REPO_ROOT, "og", "furnizori", f"{slug}.png")), fn


def test_meniul_are_link_modele_si_merge_din_subdirectoare():
    js = _citeste("enhance.js")
    assert "href: 'modele.html'" in js
    assert "function siteBase()" in js
    assert "(furnizori|semnale)" in js
    assert 'href="modele.html"' in _citeste("index.html").split('id="static-nav-fallback"')[1].split("</nav>")[0]


def test_banda_si_partajarea_sunt_in_enhance_si_in_min():
    js, mn = _citeste("enhance.js"), _citeste("enhance.min.js")
    for marker in ("tp-data-band", "Date SEAP până la", "date_seap_pana_la", "tp-share",
                   "wa.me/?text=", "facebook.com/sharer/sharer.php", "Copiază link", "semnale/harta.json"):
        assert marker in js, marker
        assert marker in mn, marker


def test_delta_are_limita_datelor():
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", json.loads(_citeste("delta.json"))["date_seap_pana_la"])


def test_workflow_comite_previzualizarile():
    assert "git add og/ semnale/" in _citeste(".github", "workflows", "update-report.yml")
