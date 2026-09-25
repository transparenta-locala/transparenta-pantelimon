"""
tests/test_scor_transparenta.py
PR #43 — teste unitare pentru calculeaza_scor_transparenta().

Acoperire:
  - structura returnata (chei, tipuri)
  - interval valid 0-100
  - subscore achizitii_directe (n_critic)
  - subscore ofertant_unic (nr_ofertanti, lista goala)
  - subscore sedinte_extraordinare (pct_extraordinare)
  - subscore fragmentare (tip==FRAGMENTARE)
  - valori hardcodate (documente_publicate=30, raspuns_544=50)
  - ponderi sumeaza 100%
  - floor la 0 pe toate subscorurile
  - campul data este format YYYY-MM-DD
Zero network, zero scraping.
"""
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from monitor_pantelimon import calculeaza_scor_transparenta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flag_critic():
    return {"severitate": "CRITIC", "tip": "ACHIZITIE_DIRECTA_PESTE_PRAG"}

def _flag_major():
    return {"severitate": "MAJOR", "tip": "CONCENTRARE"}

def _flag_fragmentare():
    return {"severitate": "MAJOR", "tip": "FRAGMENTARE"}

def _contract(nr_ofertanti=2):
    return {"nr_ofertanti": nr_ofertanti, "valoare_ron": 50_000}


# ===========================================================================
# TestStructuraReturnata
# ===========================================================================

class TestStructuraReturnata:

    def test_returneaza_dict(self):
        """Functia returneaza un dict."""
        result = calculeaza_scor_transparenta([], [], {})
        assert isinstance(result, dict)

    def test_cheile_obligatorii_prezente(self):
        """Dict-ul contine cheile scor, componente, ponderi, data."""
        result = calculeaza_scor_transparenta([], [], {})
        for cheie in ("scor", "componente", "ponderi", "componente_estimate", "metodologie", "data"):
            assert cheie in result, f"Cheia '{cheie}' lipseste"

    def test_estimarile_sunt_declarate_explicit(self):
        result = calculeaza_scor_transparenta([], [], {})
        assert set(result["componente_estimate"]) == {"documente_publicate", "raspuns_544"}
        assert "neoficial" in result["metodologie"].lower()

    def test_componente_are_6_subscoruri(self):
        """componente contine exact 6 subscoruri."""
        result = calculeaza_scor_transparenta([], [], {})
        componente = result["componente"]
        asteptate = {
            "achizitii_directe", "ofertant_unic", "sedinte_extraordinare",
            "fragmentare", "documente_publicate", "raspuns_544",
        }
        assert set(componente.keys()) == asteptate

    def test_ponderi_are_6_componente(self):
        """ponderi contine exact 6 chei cu valori numerice."""
        result = calculeaza_scor_transparenta([], [], {})
        assert len(result["ponderi"]) == 6
        for v in result["ponderi"].values():
            assert isinstance(v, (int, float))

    def test_ponderi_sumeaza_100(self):
        """Suma ponderilor este 100 (±1 din cauza rotunjirilor)."""
        result = calculeaza_scor_transparenta([], [], {})
        total = sum(result["ponderi"].values())
        assert abs(total - 100) <= 1

    def test_scor_este_int(self):
        """Campul scor este un intreg."""
        result = calculeaza_scor_transparenta([], [], {})
        assert isinstance(result["scor"], int)

    def test_data_format_iso(self):
        """Campul data respecta formatul YYYY-MM-DD."""
        result = calculeaza_scor_transparenta([], [], {})
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result["data"]), \
            f"Format data incorect: {result['data']}"


# ===========================================================================
# TestIntervalScor
# ===========================================================================

class TestIntervalScor:

    def test_scor_in_interval_0_100_stare_goala(self):
        """Stare goala → scor intre 0 si 100."""
        r = calculeaza_scor_transparenta([], [], {})
        assert 0 <= r["scor"] <= 100

    def test_scor_in_interval_multi_critic(self):
        """Multi flags CRITIC → scor >= 0."""
        flags = [_flag_critic()] * 50
        r = calculeaza_scor_transparenta(flags, [], {})
        assert 0 <= r["scor"] <= 100

    def test_scor_in_interval_toate_negative(self):
        """Combinatie defavorabila → scor >= 0 (nicicand negativ)."""
        flags = [_flag_critic()] * 50 + [_flag_fragmentare()] * 20
        contracte = [_contract(nr_ofertanti=1)] * 100
        hcl = {"pct_extraordinare": 200}
        r = calculeaza_scor_transparenta(flags, contracte, hcl)
        assert r["scor"] >= 0


# ===========================================================================
# TestSubscorAchizitiiDirecte
# ===========================================================================

class TestSubscorAchizitiiDirecte:

    def test_zero_critic_achizitii_100(self):
        """0 flags CRITIC → achizitii_directe = 100."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["achizitii_directe"] == 100

    def test_un_critic_achizitii_97(self):
        """1 flag CRITIC → achizitii_directe = 97 (100 - 1*3)."""
        r = calculeaza_scor_transparenta([_flag_critic()], [], {})
        assert r["componente"]["achizitii_directe"] == 97

    def test_cinci_critic_achizitii_85(self):
        """5 flags CRITIC → achizitii_directe = 85 (100 - 5*3)."""
        flags = [_flag_critic()] * 5
        r = calculeaza_scor_transparenta(flags, [], {})
        assert r["componente"]["achizitii_directe"] == 85

    def test_34_critic_achizitii_floor_zero(self):
        """34 flags CRITIC → achizitii_directe = 0 (floor)."""
        flags = [_flag_critic()] * 34
        r = calculeaza_scor_transparenta(flags, [], {})
        assert r["componente"]["achizitii_directe"] == 0

    def test_major_nu_afecteaza_achizitii(self):
        """Flags MAJOR nu afecteaza subscorul achizitii_directe."""
        r_cu = calculeaza_scor_transparenta([_flag_major()] * 10, [], {})
        r_fara = calculeaza_scor_transparenta([], [], {})
        assert r_cu["componente"]["achizitii_directe"] == r_fara["componente"]["achizitii_directe"]


# ===========================================================================
# TestSubscorOfertantUnic
# ===========================================================================

class TestSubscorOfertantUnic:

    def test_fara_contracte_default_70(self):
        """Lista contracte goala → ofertant_unic = 70 (default conservator)."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["ofertant_unic"] == 70

    def test_toti_doi_ofertanti_maxim(self):
        """Toate contractele cu 2 ofertanti → ofertant_unic = 100."""
        contracte = [_contract(nr_ofertanti=2)] * 10
        r = calculeaza_scor_transparenta([], contracte, {})
        assert r["componente"]["ofertant_unic"] == 100

    def test_toti_un_ofertant_scor_zero(self):
        """Toate contractele cu 1 ofertant (100%) → ofertant_unic = 0 (floor, 100 - 100*2 = -100 → 0)."""
        contracte = [_contract(nr_ofertanti=1)] * 10
        r = calculeaza_scor_transparenta([], contracte, {})
        assert r["componente"]["ofertant_unic"] == 0

    def test_jumatate_ofertant_unic(self):
        """50% contracte cu 1 ofertant → ofertant_unic = 0 (100 - 50*2 = 0)."""
        contracte = [_contract(1)] * 5 + [_contract(2)] * 5
        r = calculeaza_scor_transparenta([], contracte, {})
        assert r["componente"]["ofertant_unic"] == 0


# ===========================================================================
# TestSubscorSedinte
# ===========================================================================

class TestSubscorSedinte:

    def test_fara_hcl_sedinte_100(self):
        """statistici_hcl gol → pct_extraordinare=0 → sedinte_extraordinare=100."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["sedinte_extraordinare"] == 100

    def test_pct_40_sedinte_60(self):
        """pct_extraordinare=40 → sedinte_extraordinare=60 (100-40)."""
        r = calculeaza_scor_transparenta([], [], {"pct_extraordinare": 40})
        assert r["componente"]["sedinte_extraordinare"] == 60

    def test_pct_150_sedinte_floor_zero(self):
        """pct_extraordinare>100 → sedinte_extraordinare=0 (floor)."""
        r = calculeaza_scor_transparenta([], [], {"pct_extraordinare": 150})
        assert r["componente"]["sedinte_extraordinare"] == 0


# ===========================================================================
# TestSubscorFragmentare
# ===========================================================================

class TestSubscorFragmentare:

    def test_fara_fragmentare_scor_100(self):
        """0 flags FRAGMENTARE → fragmentare = 100."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["fragmentare"] == 100

    def test_un_flag_fragmentare_90(self):
        """1 flag FRAGMENTARE → fragmentare = 90 (100 - 1*10)."""
        r = calculeaza_scor_transparenta([_flag_fragmentare()], [], {})
        assert r["componente"]["fragmentare"] == 90

    def test_10_fragmentare_floor_zero(self):
        """10 flags FRAGMENTARE → fragmentare = 0 (floor)."""
        flags = [_flag_fragmentare()] * 10
        r = calculeaza_scor_transparenta(flags, [], {})
        assert r["componente"]["fragmentare"] == 0

    def test_critic_nu_afecteaza_fragmentare(self):
        """Flags CRITIC nu afecteaza subscorul fragmentare."""
        r_cu = calculeaza_scor_transparenta([_flag_critic()] * 10, [], {})
        r_fara = calculeaza_scor_transparenta([], [], {})
        assert r_cu["componente"]["fragmentare"] == r_fara["componente"]["fragmentare"]


# ===========================================================================
# TestValoriHardcodate
# ===========================================================================

class TestValoriHardcodate:

    def test_documente_publicate_hardcodat_30(self):
        """componente.documente_publicate este intotdeauna 30."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["documente_publicate"] == 30

    def test_raspuns_544_hardcodat_50(self):
        """componente.raspuns_544 este intotdeauna 50."""
        r = calculeaza_scor_transparenta([], [], {})
        assert r["componente"]["raspuns_544"] == 50

    def test_hardcodate_neschimbate_de_flags(self):
        """Valorile hardcodate nu se schimba indiferent de flags."""
        flags = [_flag_critic()] * 20 + [_flag_fragmentare()] * 10
        r = calculeaza_scor_transparenta(flags, [_contract(1)] * 50, {"pct_extraordinare": 80})
        assert r["componente"]["documente_publicate"] == 30
        assert r["componente"]["raspuns_544"] == 50
