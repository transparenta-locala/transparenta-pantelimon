"""Teste pentru reparațiile din auditul din 26.10.2026 (cifre consecvente, legături între pagini)."""
import os
import re
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import monitor_pantelimon as m  # noqa: E402


# ── Anul bugetului ────────────────────────────────────────────────────────────

PAGINA_TE = """<html><head>
<meta name="description" content="ORASUL PANTELIMON din județul ILFOV. Venituri 147,97 mil. RON, Cheltuieli 146,43 mil. RON, Balanta 1,54 mil. RON pentru 2025."/>
</head><body>Venituri 2025 147,97 mil. RON <div><svg></svg>-<!-- -->8,19<!-- -->% <!-- -->YoY</div>
Cheltuieli 2025 <div><svg></svg>+<!-- -->5,93<!-- -->% <!-- -->YoY</div></body></html>"""


class _Raspuns:
    text = PAGINA_TE
    status_code = 200

    def raise_for_status(self):
        pass


def test_anul_bugetului_vine_din_pagina_nu_din_data_rularii():
    """În oct. 2026 site-ul eticheta execuția 2025 drept „2026”."""
    with mock.patch.object(m.requests, "get", return_value=_Raspuns()):
        b = m.fetch_budget_transparenta("4420759")
    assert b["an"] == 2025
    assert b["cheltuieli_mil_ron"] == 146.43


def test_variatia_anuala_e_citita_si_cu_comentarii_react():
    with mock.patch.object(m.requests, "get", return_value=_Raspuns()):
        b = m.fetch_budget_transparenta("4420759")
    assert b["yoy_venituri"] == "-8,19%"
    assert b["yoy_cheltuieli"] == "+5,93%"


# ── Date în română ────────────────────────────────────────────────────────────

def test_data_generarii_e_in_romana():
    assert m._data_generare_ro(datetime(2026, 10, 15, 10, 6)) == "15 octombrie 2026, 10:06"


# ── Ordinea semnalelor (raport.json ↔ HTML) ───────────────────────────────────

def test_sortarea_e_stabila_si_pe_severitate():
    flags = [{"severitate": "MEDIU", "id": 1}, {"severitate": "CRITIC", "id": 2},
             {"severitate": "MEDIU", "id": 3}, {"severitate": "MAJOR", "id": 4}]
    assert [f["id"] for f in m.sorteaza_dupa_severitate(flags)] == [2, 4, 1, 3]


# ── Instituții vs. firme ──────────────────────────────────────────────────────

def test_consiliul_local_nu_e_firma():
    assert m._este_institutie("Consiliul Local Pantelimon")
    assert m._este_institutie("Multiple")
    assert not m._este_institutie("Constopograf Expert")
    assert not m._este_institutie("")


# ── Raportul generat ──────────────────────────────────────────────────────────

def _contract(cid, firma, valoare, k=None, tipc="achizitie-directa", data="2025-01-16"):
    return {"id": cid, "titlu": "Servicii de cadastru", "valoare_ron": valoare, "data_publicare": data,
            "tip_procedura": "", "castigator": firma, "castigator_cui": "25145252", "nr_ofertanti": 1,
            "cod_seap": "DA1", "url_seap": "https://e-licitatie.ro/x", "cheie_seap": k or f"da:{cid}",
            "tip_contract": tipc}


def _raport(flags, contracte, flags_noi=()):
    cfg = dict(m.CONFIG)
    cfg.update({"_offline_mode": True, "_scor": {}, "_hcl_total": 0})
    m.inregistreaza_linkuri_seap(contracte)
    return m.genereaza_raport_html({"an": 2025}, contracte, flags, list(flags_noi), cfg)


def test_cardul_leaga_fisa_firmei_si_pagina_semnalului():
    c = [_contract("achizitie-directa-2025-1", "Constopograf Expert", 270000)]
    f = [{"severitate": "MAJOR", "titlu": "Un singur ofertant", "descriere": "x", "furnizor": "Constopograf Expert",
          "valoare": 270000, "data": "2025-01-16", "contract_id": "achizitie-directa-2025-1", "tip": "OFERTANT_UNIC"}]
    html = _raport(f, c)
    assert 'href="furnizori/constopograf-expert.html"' in html
    assert 'href="semnale/ofertant-unic-2025-1.html"' in html
    # nu mai copiem contractele și raport.json în pagină (sunt servite separat)
    assert 'id="contracte-data"' not in html
    assert 'id="tp-data"' not in html


def test_contractele_semnalului_se_numara_o_data():
    """Două semnale pe același contract → data-contracts are aceeași cheie (total pe contracte distincte)."""
    c = [_contract("achizitie-directa-2025-1", "Constopograf Expert", 270000)]
    base = {"titlu": "t", "descriere": "d", "furnizor": "Constopograf Expert", "valoare": 270000,
            "data": "2025-01-16", "contract_id": "achizitie-directa-2025-1"}
    f = [dict(base, severitate="MAJOR", tip="OFERTANT_UNIC"), dict(base, severitate="MEDIU", tip="APROAPE_DE_PRAG")]
    html = _raport(f, c)
    chei = re.findall(r'data-contracts="([^"]*)"', html)
    assert chei == ["da:achizitie-directa-2025-1:270000"] * 2


def test_acordurile_cadru_nu_intra_in_suma():
    c = [_contract("contract-2025-9", "Firma Mare", 5_000_000, tipc="acord-cadru")]
    f = [{"severitate": "MEDIU", "titlu": "t", "descriere": "d", "furnizor": "Firma Mare", "valoare": 5_000_000,
          "data": "2025-01-16", "contract_id": "contract-2025-9", "tip": "OFERTANT_UNIC"}]
    html = _raport(f, c)
    assert 'data-contracts="da:contract-2025-9:0"' in html


def test_semnalele_hcl_nu_apar_ca_firma():
    f = [{"severitate": "MAJOR", "titlu": "Ședințe extraordinare", "descriere": "d",
          "furnizor": "Consiliul Local Pantelimon", "valoare": 0, "data": "2026-10-01",
          "contract_id": "hcl-meta", "tip": "SEDINTE_EXTRAORDINARE_EXCESIVE"}]
    html = _raport(f, [_contract("achizitie-directa-2025-1", "Firma", 1000)])
    assert 'data-entity="institutie"' in html
    i = html.index('id="risc-firma-data"')
    assert "Consiliul Local" not in html[i:i + 2000]


def test_doar_primele_25_de_carduri_vizibile_la_incarcare():
    c = [_contract(f"achizitie-directa-2025-{i}", "F", 100 + i) for i in range(30)]
    f = [{"severitate": "MEDIU", "titlu": "t", "descriere": "d", "furnizor": "F", "valoare": 100 + i,
          "data": "2025-01-16", "contract_id": f"achizitie-directa-2025-{i}", "tip": "OFERTANT_UNIC"} for i in range(30)]
    html = _raport(f, c)
    assert html.count("tp-flag tp-pre-hidden") == 5


def test_slugurile_cardurilor_coincid_cu_previzualizarile():
    """Linkul „Pagina semnalului” din raport trebuie să ducă exact la pagina generată."""
    from genereaza_previzualizari import extrage_semnale, atribuie_sluguri
    c = [_contract("achizitie-directa-2025-1", "A", 1), _contract("achizitie-directa-2025-2", "B", 2)]
    f = [{"severitate": "MAJOR", "titlu": "t", "descriere": "d", "furnizor": "A", "valoare": 1, "data": "2025-01-16",
          "contract_id": "achizitie-directa-2025-1", "tip": "OFERTANT_UNIC"},
         {"severitate": "MAJOR", "titlu": "t", "descriere": "d", "furnizor": "B", "valoare": 2, "data": "2025-01-16",
          "contract_id": "achizitie-directa-2025-1", "tip": "OFERTANT_UNIC"}]   # coliziune de slug → sufix -2
    html = _raport(f, c)
    din_card = [s["slug_card"] for s in extrage_semnale(html)]
    recalculat = [dict(s, slug_card="") for s in extrage_semnale(html)]
    assert din_card == [s["slug"] for s in atribuie_sluguri(recalculat)]
    assert din_card[1].endswith("-2")


# ── Fișe de firmă ─────────────────────────────────────────────────────────────

def test_fisa_firmei_grupeaza_semnalele_pe_contract_si_numara_contracte_distincte():
    c = [_contract("achizitie-directa-2025-1", "Asociere SRL", 900_000, k="can:1"),
         _contract("achizitie-directa-2025-1b", "Asociere SRL", 900_000, k="can:1")]   # același contract, 2 rânduri
    f = [{"severitate": "MAJOR", "titlu": "Un singur ofertant", "descriere": "d", "furnizor": "Asociere SRL",
          "valoare": 900_000, "data": "2025-01-16", "contract_id": "achizitie-directa-2025-1", "tip": "OFERTANT_UNIC"}]
    html = m.genereaza_pagina_furnizor("Asociere SRL", "asociere-srl", f, c, m.CONFIG,
                                       sluguri_semnale={id(f[0]): "ofertant-unic-2025-1"})
    assert '<div class="stat-val">1</div><div class="stat-lbl">Contracte</div>' in html
    assert "900K RON" in html and "1.80 mil. RON" not in html
    assert 'href="../semnale/ofertant-unic-2025-1.html"' in html
    assert 'href="https://e-licitatie.ro/x"' in html


def test_contoare_index_scrise_static(tmp_path):
    p = tmp_path / "index.html"
    p.write_text('<span class="v" id="idx-contracte">506</span> <b id="idx-firme">181</b>', encoding="utf-8")
    export = [{"id": "1", "k": "da:1", "cui": "1", "firma": "A"}, {"id": "2", "k": "da:1", "cui": "2", "firma": "B"},
              {"id": "3", "k": "da:3", "cui": "1", "firma": "A"}]
    assert m.actualizeaza_contoare_index(export, str(p))
    t = p.read_text(encoding="utf-8")
    assert 'id="idx-contracte">2<' in t and 'id="idx-firme">2<' in t
