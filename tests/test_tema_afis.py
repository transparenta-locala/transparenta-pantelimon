"""Tema „afiș” (29.10.2026): cifra mare de pe prima pagină și fișierele temei (fără rețea)."""
import os

import monitor_pantelimon as m
import site_shell

RADACINA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPORT = [
    {"k": "da:1", "valoare": 1_200_000, "data": "2025-03-01", "tipc": "achizitie-directa", "cui": "1"},
    {"k": "da:1", "valoare": 1_200_000, "data": "2025-03-01", "tipc": "achizitie-directa", "cui": "2"},  # asociere
    {"k": "da:2", "valoare": 300_000, "data": "2026-01-10", "tipc": "achizitie-directa", "cui": "3"},
    {"k": "can:9", "valoare": 9_000_000, "data": "2024-05-05", "tipc": "contract", "cui": "4"},
]


def test_cumparari_directe_numara_fiecare_contract_o_data():
    n, val, an = m.cumparari_directe(EXPORT)
    assert (n, val, an) == (2, 1_500_000, "2025")


def test_mil_lei():
    assert m._mil_lei(27_490_000) == "27,5 mil. lei"
    assert m._mil_lei(840_000) == "840.000 lei"
    assert m._mil_lei(0) == ""


def test_index_primeste_cifra_mare(tmp_path):
    p = tmp_path / "index.html"
    p.write_text('<span class="v" id="idx-contracte">1</span> <b id="idx-firme">1</b>'
                 '<span id="idx-directe-val">x</span><span id="idx-directe-n">x</span>'
                 '<span id="idx-directe-din">x</span>', encoding="utf-8")
    assert m.actualizeaza_contoare_index(EXPORT, str(p))
    t = p.read_text(encoding="utf-8")
    assert 'id="idx-directe-val">1,5 mil. lei<' in t
    assert 'id="idx-directe-n">2<' in t and 'id="idx-directe-din">2025<' in t


def test_prima_pagina_are_cifra_mare_si_id_urile_monitorului():
    with open(os.path.join(RADACINA, "index.html"), encoding="utf-8") as f:
        t = f.read()
    for elem_id in ("idx-directe-val", "idx-directe-n", "idx-directe-din", "idx-contracte", "idx-firme",
                    "idx-nereguli", "idx-banner-nereguli", "idx-banner-critic", "idx-see-all",
                    "idx-cheltuieli", "idx-cheltuieli-label", "scor-val", "rezultate"):
        assert f'id="{elem_id}"' in t, elem_id


def test_fonturile_temei_exista_si_sunt_preincarcate():
    with open(os.path.join(RADACINA, "assets", "tp.css"), encoding="utf-8") as f:
        css = f.read()
    assert "TEMA „AFIȘ”" in css and '"TP Display"' in css
    for font in site_shell.FONTURI_PRELOAD:
        assert os.path.exists(os.path.join(RADACINA, font)), font
    assert os.path.exists(os.path.join(RADACINA, "assets", "tp-clasic.css"))


def test_pagina_semnalului_are_severitatea():
    import genereaza_previzualizari as g
    assert g.CULORI_SEV["CRITIC"] == "#E3001E"
    with open(os.path.join(RADACINA, "genereaza_previzualizari.py"), encoding="utf-8") as f:
        assert 'article class="card" data-sev=' in f.read()
