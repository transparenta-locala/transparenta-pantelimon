"""
tests/test_utils.py
PR #42 — teste unitare pentru functii utilitare din monitor_pantelimon.py:
  - _seap_url
  - _fmt_ron
  - _format_kpi
  - _similaritate_titlu
  - _termene_url
  - _incarca_cache_firme / _salveaza_cache_firme
  - _fmt_actionariat
  - _fmt_reprezentanti
Zero network, zero scraping.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from monitor_pantelimon import (
    _seap_url,
    _fmt_ron,
    _format_kpi,
    _similaritate_titlu,
    _termene_url,
    _incarca_cache_firme,
    _salveaza_cache_firme,
    _fmt_actionariat,
    _fmt_reprezentanti,
)


# ===========================================================================
# TestSeapUrl
# ===========================================================================

class TestSeapUrl:
    """_seap_url: link real dacă îl știm (sursa SEAP API), altfel lista publică SEAP.

    Id-urile vechi din data.gov.ro conțin numărul rândului din fișier, nu un
    număr SEAP — /view/<nr> deschidea o pagină goală, deci nu mai construim
    linkuri din ele.
    """

    def setup_method(self):
        from monitor_pantelimon import inregistreaza_linkuri_seap
        inregistreaza_linkuri_seap([
            {"id": "achizitie-directa-2025-118853764",
             "url_seap": "https://e-licitatie.ro/pub/direct-acquisition/view/118853764",
             "cod_seap": "DA37312670"},
            {"id": "contract-2025-1",
             "url_seap": "https://e-licitatie.ro/pub/notices/ca-notices/view-c/100566166",
             "cod_seap": "CAN1151813"},
        ])

    def teardown_method(self):
        from monitor_pantelimon import inregistreaza_linkuri_seap
        inregistreaza_linkuri_seap([])

    def test_link_real_din_registru(self):
        assert _seap_url("achizitie-directa-2025-118853764") == \
            "https://e-licitatie.ro/pub/direct-acquisition/view/118853764"

    def test_link_real_contract(self):
        assert _seap_url("contract-2025-1", "Licitatie deschisa").endswith("/view-c/100566166")

    def test_id_cu_virgula_ia_primul(self):
        url = _seap_url("contract-2025-1, achizitie-directa-2025-118853764")
        assert url.endswith("/view-c/100566166")

    def test_id_vechi_da_duce_la_lista_publica(self):
        """Id vechi (rând data.gov.ro) → lista publică de cumpărări directe, nu /view/<rând>."""
        url = _seap_url("achizitie-directa-2025-489392")
        assert url == "https://e-licitatie.ro/pub/direct-acquisitions/list/1"
        assert "489392" not in url

    def test_id_vechi_contract_duce_la_atribuiri(self):
        assert _seap_url("contract-2025-79964") == "https://e-licitatie.ro/pub/notices/ca-notices/list/1"

    def test_id_gol_fallback(self):
        assert "e-licitatie.ro" in _seap_url("")

    def test_seap_nr_coduri_reale(self):
        from monitor_pantelimon import _seap_nr
        assert _seap_nr("achizitie-directa-2025-118853764,contract-2025-1") == \
            "Cod SEAP: DA37312670, CAN1151813"

    def test_seap_nr_fara_cod_nu_afiseaza_numar_de_rand(self):
        from monitor_pantelimon import _seap_nr
        assert _seap_nr("achizitie-directa-2025-489392") == ""


# ===========================================================================
# TestFmtRon
# ===========================================================================

class TestFmtRon:

    def test_milioane(self):
        """Valori >= 1.000.000 → format 'X.XX mil. RON'."""
        assert "mil. RON" in _fmt_ron(1_500_000)

    def test_mii(self):
        """Valori >= 1.000 dar < 1.000.000 → format 'XK RON'."""
        result = _fmt_ron(125_000)
        assert "K RON" in result
        assert "125" in result

    def test_sub_mie(self):
        """Valori < 1.000 → format simplu 'X RON'."""
        result = _fmt_ron(500)
        assert "RON" in result
        assert "K" not in result
        assert "mil" not in result

    def test_exact_un_milion(self):
        """1.000.000 RON → format milioane."""
        assert "mil. RON" in _fmt_ron(1_000_000)

    def test_exact_o_mie(self):
        """1.000 RON → format K."""
        assert "K RON" in _fmt_ron(1_000)

    def test_zero(self):
        """Valoare 0 → string non-gol cu RON."""
        result = _fmt_ron(0)
        assert "RON" in result


# ===========================================================================
# TestFormatKpi
# ===========================================================================

class TestFormatKpi:

    def test_milioane_cu_virgula(self):
        """Milioane folosesc virgula ca separator zecimal (format roman)."""
        result = _format_kpi(12_300_000)
        assert "M RON" in result
        assert "," in result  # Romanian decimal separator

    def test_mii(self):
        """Mii → format 'XK RON'."""
        result = _format_kpi(500_000)
        assert "K RON" in result

    def test_sub_mie(self):
        """Sub 1000 → format integer RON."""
        result = _format_kpi(150)
        assert "150 RON" == result

    def test_un_milion(self):
        """1.000.000 → format milion."""
        result = _format_kpi(1_000_000)
        assert "M RON" in result

    def test_diferit_de_fmt_ron(self):
        """_format_kpi si _fmt_ron produc formate distincte pentru milioane."""
        kpi = _format_kpi(1_500_000)
        ron = _fmt_ron(1_500_000)
        # format_kpi: '1,5M RON' vs _fmt_ron: '1.50 mil. RON'
        assert kpi != ron


# ===========================================================================
# TestSimitatitluTitlu
# ===========================================================================

class TestSimitatitluTitlu:

    def test_titluri_identice(self):
        """Titluri identice → similaritate 1.0."""
        assert _similaritate_titlu("servicii curatenie", "servicii curatenie") == 1.0

    def test_titluri_total_diferite(self):
        """Titluri fara cuvinte comune → similaritate 0.0."""
        assert _similaritate_titlu("curatenie", "reparatii drumuri") == 0.0

    def test_titluri_partial_similare(self):
        """Titluri cu unele cuvinte comune → similaritate intre 0 si 1."""
        sim = _similaritate_titlu("servicii curatenie cladiri", "servicii reparatii cladiri")
        assert 0.0 < sim < 1.0

    def test_string_gol(self):
        """String gol → similaritate 0.0 (fara crash)."""
        assert _similaritate_titlu("", "curatenie") == 0.0
        assert _similaritate_titlu("curatenie", "") == 0.0

    def test_case_insensitive(self):
        """Comparatia este case-insensitive."""
        assert _similaritate_titlu("CURATENIE", "curatenie") == 1.0

    def test_simetrie(self):
        """Similaritatea este simetrica: sim(A,B) == sim(B,A)."""
        a, b = "servicii curatenie", "curatenie cladiri"
        assert _similaritate_titlu(a, b) == _similaritate_titlu(b, a)


# ===========================================================================
# TestTermeneUrl
# ===========================================================================

class TestTermeneUrl:

    def test_cui_numeric(self):
        """CUI numeric valid → URL termene.ro cu ID-ul firmei."""
        url = _termene_url("12345678")
        assert "termene.ro/firma/12345678" in url

    def test_cui_cu_prefix_ro(self):
        """CUI cu prefix RO → eliminat din URL."""
        url = _termene_url("RO12345678")
        assert "12345678" in url
        assert "RO" not in url.split("/")[-1]

    def test_cui_non_numeric_fallback(self):
        """CUI non-numeric → URL de cautare."""
        url = _termene_url("INVALID-CUI")
        assert "termene.ro" in url
        assert "cauta" in url

    def test_returneaza_string(self):
        """Returneaza intotdeauna un string."""
        assert isinstance(_termene_url("12345"), str)
        assert isinstance(_termene_url(""), str)


# ===========================================================================
# TestCacheFirme
# ===========================================================================

class TestCacheFirme:

    def test_incarca_fisier_inexistent(self, tmp_path):
        """Fisier cache inexistent → dict gol."""
        path = str(tmp_path / "cache.json")
        result = _incarca_cache_firme(path)
        assert result == {}

    def test_incarca_fisier_valid(self, tmp_path):
        """Fisier cache valid → returneaza continutul."""
        path = str(tmp_path / "cache.json")
        data = {"12345678": {"nume": "FIRMA X", "stare": "ACTIVA"}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = _incarca_cache_firme(path)
        assert result["12345678"]["stare"] == "ACTIVA"

    def test_incarca_fisier_corupt(self, tmp_path):
        """Fisier corupt (JSON invalid) → dict gol (fara crash)."""
        path = str(tmp_path / "corupt.json")
        with open(path, "w") as f:
            f.write("{INVALID JSON}")
        result = _incarca_cache_firme(path)
        assert result == {}

    def test_salveaza_creeaza_fisier(self, tmp_path):
        """_salveaza_cache_firme creeaza fisierul JSON."""
        path = str(tmp_path / "nou.json")
        _salveaza_cache_firme(path, {"99": {"date": "test"}})
        assert os.path.exists(path)

    def test_salveaza_si_incarca_roundtrip(self, tmp_path):
        """Salveaza si reincarca → acelasi continut."""
        path = str(tmp_path / "roundtrip.json")
        data = {"CUI1": {"nume": "FIRMA A"}, "CUI2": {"stare": "INACTIVA"}}
        _salveaza_cache_firme(path, data)
        loaded = _incarca_cache_firme(path)
        assert loaded == data

    def test_salveaza_unicode(self, tmp_path):
        """Datele cu diacritice sunt salvate/incarcate corect."""
        path = str(tmp_path / "unicode.json")
        data = {"1": {"nume": "Primăria Pantelimon — Transparență"}}
        _salveaza_cache_firme(path, data)
        loaded = _incarca_cache_firme(path)
        assert "Transparență" in loaded["1"]["nume"]


# ===========================================================================
# TestFmtActionariat
# ===========================================================================

class TestFmtActionariat:

    def test_info_gol_returneaza_gol(self):
        """Dict gol sau None → string gol."""
        assert _fmt_actionariat({}) == ""
        assert _fmt_actionariat(None) == ""

    def test_firma_radiata(self):
        """Firma radiata → mesaj de avertizare RADIATA in output."""
        info = {"radiata": True, "numar_reg_com": "J40/1234/2020"}
        result = _fmt_actionariat(info)
        assert "RADIATĂ" in result or "RADIATA" in result.upper()

    def test_numar_orc(self):
        """numar_reg_com apare in output HTML."""
        info = {"numar_reg_com": "J23/456/2019"}
        result = _fmt_actionariat(info)
        assert "J23/456/2019" in result

    def test_ultima_declaratie(self):
        """ultima_declaratie apare in output HTML."""
        info = {"ultima_declaratie": "2024-03-15"}
        result = _fmt_actionariat(info)
        assert "2024-03-15" in result

    def test_recom_url(self):
        """recom_url genereaza link in output HTML."""
        info = {"recom_url": "https://recom.ro/test-firma"}
        result = _fmt_actionariat(info)
        assert "recom.ro" in result
        assert "href=" in result

    def test_info_complet(self):
        """Info complet → toate campurile prezente in output."""
        info = {
            "radiata": False,
            "numar_reg_com": "J40/999/2021",
            "ultima_declaratie": "2025-01-10",
            "recom_url": "https://recom.ro/firma/12345",
        }
        result = _fmt_actionariat(info)
        assert "J40/999/2021" in result
        assert "2025-01-10" in result
        assert "recom.ro" in result


# ===========================================================================
# TestFmtReprezentanti
# ===========================================================================

class TestFmtReprezentanti:

    def test_info_gol_returneaza_gol(self):
        """Dict gol sau None → string gol."""
        assert _fmt_reprezentanti({}) == ""
        assert _fmt_reprezentanti(None) == ""

    def test_fara_reprezentanti_returneaza_gol(self):
        """Lista reprezentanti goala → string gol."""
        assert _fmt_reprezentanti({"reprezentanti": []}) == ""

    def test_reprezentant_simplu(self):
        """Un reprezentant → apare in output HTML."""
        onrc = {
            "reprezentanti": [
                {"nume": "Ion Popescu", "calitate": "ADMINISTRATOR", "localitate": "Bucuresti"}
            ],
            "cod_inmatriculare": ""
        }
        result = _fmt_reprezentanti(onrc)
        assert "Ion Popescu" in result
        assert "ADMINISTRATOR" in result

    def test_localitate_optionala(self):
        """Localitate prezenta → apare in output."""
        onrc = {
            "reprezentanti": [
                {"nume": "Maria Ion", "calitate": "ASOCIAT", "localitate": "Ilfov"}
            ],
            "cod_inmatriculare": ""
        }
        result = _fmt_reprezentanti(onrc)
        assert "Ilfov" in result

    def test_maxim_5_reprezentanti(self):
        """Mai mult de 5 reprezentanti → doar primii 5 sunt afisati."""
        onrc = {
            "reprezentanti": [
                {"nume": f"Persoana {i}", "calitate": "ASOCIAT", "localitate": ""}
                for i in range(10)
            ],
            "cod_inmatriculare": ""
        }
        result = _fmt_reprezentanti(onrc)
        assert result.count("ASOCIAT") <= 5

    def test_cod_inmatriculare_genereaza_link(self):
        """cod_inmatriculare prezent → link recom.ro in output."""
        onrc = {
            "reprezentanti": [
                {"nume": "Test", "calitate": "DIRECTOR", "localitate": ""}
            ],
            "cod_inmatriculare": "abc123"
        }
        result = _fmt_reprezentanti(onrc)
        assert "recom.ro" in result
        assert "abc123" in result
