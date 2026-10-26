"""Blocul „Date financiare ANAF” de pe fișele de firmă (firme_financiar.json)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import monitor_pantelimon as m  # noqa: E402


def _contract(cid, valoare, data="2025-03-10", tipc="achizitie-directa", titlu="Servicii de cadastru",
              cui="25145252", firma="Exemplu SRL"):
    return {"id": cid, "titlu": titlu, "valoare_ron": valoare, "data_publicare": data,
            "tip_procedura": "", "castigator": firma, "castigator_cui": cui, "nr_ofertanti": 1,
            "cod_seap": "DA1", "url_seap": "https://e-licitatie.ro/x", "cheie_seap": f"da:{cid}",
            "tip_contract": tipc}


def _fisa(contracte, financiar):
    return m.genereaza_pagina_furnizor("Exemplu SRL", "exemplu-srl", [], contracte, m.CONFIG,
                                       financiar=financiar)


def _bloc(html):
    g = re.search(r'<section class="tp-fin".*?</section>', html, re.S)
    return g.group(0) if g else ""


def test_blocul_arata_cifrele_si_sursa():
    bloc = _bloc(_fisa([_contract("1", 100_000)],
                       {"an": "2024", "cifra_afaceri": 4_512_300.0, "nr_salariati": 17}))
    assert "<h2>Date financiare ANAF 2024</h2>" in bloc
    assert "4.512.300 RON" in bloc
    assert "<dd>17</dd>" in bloc
    assert "https://data.gov.ro/dataset/situatii_financiare_2024" in bloc
    assert "Indicatori de verificat" not in bloc   # firmă fără indicatori → doar cifrele


def test_anul_din_seturile_uu_si_ong_e_doar_anul():
    bloc = _bloc(_fisa([_contract("1", 100_000)], {"an": "2024-uu", "cifra_afaceri": 1e6, "nr_salariati": 9}))
    assert "Date financiare ANAF 2024<" in bloc and "2024-uu" not in bloc


def test_fara_date_blocul_lipseste():
    assert _bloc(_fisa([_contract("1", 100_000)], None)) == ""
    assert _bloc(_fisa([_contract("1", 100_000)], {})) == ""
    assert _bloc(_fisa([_contract("1", 100_000)], {"an": "2024", "cifra_afaceri": None, "nr_salariati": None})) == ""


def test_cifra_de_afaceri_sub_jumatate_din_contract():
    bloc = _bloc(_fisa([_contract("1", 500_000, titlu="Lucrări <asfalt>"), _contract("2", 50_000)],
                       {"an": "2024", "cifra_afaceri": 100_000.0, "nr_salariati": 5}))
    assert 'data-cod="CIFRA_AFACERI_SUB_CONTRACT"' in bloc
    assert "sub jumătate din valoarea celui mai mare contract" in bloc and "500K RON" in bloc
    assert "Lucrări &lt;asfalt&gt;" in bloc            # titlul e escapat
    assert "nu concluzii" in bloc


def test_cifra_de_afaceri_sub_10_la_suta():
    bloc = _bloc(_fisa([_contract("1", 2_000_000, data="2026-02-01")],
                       {"an": "2024", "cifra_afaceri": 50_000.0, "nr_salariati": 4}))
    assert 'data-cod="CIFRA_AFACERI_MULT_SUB_CONTRACT"' in bloc and "sub 10%" in bloc


def test_acordul_cadru_nu_e_contract_de_referinta():
    """Acordul-cadru e un plafon, nu bani contractați."""
    bloc = _bloc(_fisa([_contract("1", 5_000_000, tipc="acord-cadru"), _contract("2", 80_000)],
                       {"an": "2024", "cifra_afaceri": 100_000.0, "nr_salariati": 5}))
    assert "CIFRA_AFACERI" not in bloc


def test_contractele_dinaintea_anului_datelor_nu_se_compara():
    """evaluate_shell_risk compară cu anul dinaintea contractului; un contract din 2023 nu are date 2022."""
    bloc = _bloc(_fisa([_contract("1", 5_000_000, data="2023-05-01")],
                       {"an": "2024", "cifra_afaceri": 10_000.0, "nr_salariati": 0}))
    assert "CIFRA_AFACERI_MULT" not in bloc
    assert 'data-cod="ZERO_ANGAJATI"' in bloc          # angajații nu depind de contract


def test_angajati_putini_si_cifra_de_afaceri_zero():
    bloc = _bloc(_fisa([_contract("1", 100_000)], {"an": "2024", "cifra_afaceri": 0.0, "nr_salariati": 2}))
    assert 'data-cod="CIFRA_AFACERI_ZERO"' in bloc
    assert 'data-cod="FOARTE_PUTINI_ANGAJATI"' in bloc and "angajați declarat pentru 2024 este 2." in bloc


def test_formulare_neutra_fara_etichete_de_severitate():
    bloc = _bloc(_fisa([_contract("1", 2_000_000)], {"an": "2024", "cifra_afaceri": 0.0, "nr_salariati": 0}))
    for cuvant in ("CRITIC", "MAJOR", "MEDIU", "fantomă", "suspect"):
        assert cuvant not in bloc


def test_incarca_financiar_normalizeaza_cui_si_tolereaza_lipsa(tmp_path):
    assert m.incarca_financiar_firme(str(tmp_path / "lipsa.json")) == {}
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"RO123": {"an": "2024", "cifra_afaceri": 1, "nr_salariati": 1}}), encoding="utf-8")
    assert "123" in m.incarca_financiar_firme(str(p))


def test_fisele_generate_iau_datele_dupa_cui_fara_ro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "firme_financiar.json").write_text(
        json.dumps({"25145252": {"an": "2024", "cifra_afaceri": 552150.0, "nr_salariati": 2}}), encoding="utf-8")
    contracte = [_contract("1", 100_000, cui="RO25145252"),
                 _contract("2", 70_000, cui="999", firma="Alta SRL")]
    m.genereaza_pagini_furnizori(contracte, [])
    cu_date = (tmp_path / "furnizori" / "exemplu-srl.html").read_text(encoding="utf-8")
    fara_date = (tmp_path / "furnizori" / "alta-srl.html").read_text(encoding="utf-8")
    assert "Date financiare ANAF 2024" in cu_date and "552.150 RON" in cu_date
    assert 'class="tp-fin"' not in fara_date
