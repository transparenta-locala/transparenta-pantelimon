"""
tests/test_state_analytics.py
PR #40 — teste unitare pentru:
  - incarca_stare_anterioara / salveaza_stare / detecteaza_flags_noi
  - calculeaza_analiza_per_tip
  - _slugify
  - _detect_flag_simple
  - render_contracte_tbody_rows
Zero network, zero scraping.
"""
import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from monitor_pantelimon import (
    incarca_stare_anterioara,
    salveaza_stare,
    detecteaza_flags_noi,
    calculeaza_analiza_per_tip,
    _slugify,
    _detect_flag_simple,
    render_contracte_tbody_rows,
)


# ===========================================================================
# Fixtures
# ===========================================================================

FLAGS_SAMPLE = [
    {"contract_id": "ad-2025-001", "tip": "ACHIZITIE_DIRECTA_PRAG",
     "severitate": "MAJOR", "valoare": 126500, "furnizor": "FIRMA A",
     "data": "2025-03-15"},
    {"contract_id": "ad-2025-002", "tip": "FRAGMENTARE",
     "severitate": "CRITIC", "valoare": 270000, "furnizor": "FIRMA B",
     "data": "2025-04-20"},
    {"contract_id": "ad-2025-003", "tip": "FRAGMENTARE",
     "severitate": "CRITIC", "valoare": 260000, "furnizor": "FIRMA B",
     "data": "2025-05-10"},
]

CONTRACTE_SAMPLE = [
    {"id": "ad-2025-100", "titlu": "Servicii curatenie", "valoare": 45000,
     "data": "2025-03-01", "tip": "achizitie-directa",
     "firma": "CLEAN SRL", "cui": "RO111", "ofertanti": 1},
    {"id": "ad-2025-101", "titlu": "Lucrari drumuri", "valoare": 135000,
     "data": "2025-04-01", "tip": "achizitie-directa",
     "firma": "DRUM SA", "cui": "RO222", "ofertanti": 0},
    {"id": "ad-2025-102", "titlu": "Combustibil 2025", "valoare": 350000,
     "data": "2025-01-10", "tip": "licitatie-deschisa",
     "firma": "PETRO SRL", "cui": "RO333", "ofertanti": 3},
]


# ===========================================================================
# TestIncarcaSalveazaStare
# ===========================================================================

class TestIncarcaSalveazaStare:

    def test_incarca_fisier_inexistent(self, tmp_path):
        """Fisier inexistent → returneaza struct implicita."""
        path = str(tmp_path / "stare_test.json")
        result = incarca_stare_anterioara(path)
        assert isinstance(result, dict)
        assert "flags_anterioare" in result
        assert result["flags_anterioare"] == []
        assert result["data_ultima_rulare"] is None

    def test_incarca_fisier_valid(self, tmp_path):
        """Fisier JSON valid → returneaza continutul sau."""
        path = str(tmp_path / "stare.json")
        stare = {
            "flags_anterioare": ["ad-001_FRAGMENTARE", "ad-002_OFERTANT_UNIC"],
            "contracte_vazute": ["ad-001", "ad-002"],
            "data_ultima_rulare": "2026-04-15T10:00:00",
            "total_flags": 2,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stare, f)
        result = incarca_stare_anterioara(path)
        assert result["flags_anterioare"] == stare["flags_anterioare"]
        assert result["total_flags"] == 2
        assert result["data_ultima_rulare"] == "2026-04-15T10:00:00"

    def test_salveaza_creeaza_fisier(self, tmp_path):
        """salveaza_stare creeaza fisierul daca nu exista."""
        path = str(tmp_path / "stare_noua.json")
        salveaza_stare(path, FLAGS_SAMPLE, CONTRACTE_SAMPLE)
        assert os.path.exists(path)

    def test_salveaza_format_flag_id(self, tmp_path):
        """Fiecare flag e salvat ca 'contract_id_tip'."""
        path = str(tmp_path / "stare.json")
        salveaza_stare(path, FLAGS_SAMPLE, CONTRACTE_SAMPLE)
        with open(path, encoding="utf-8") as f:
            stare = json.load(f)
        assert "ad-2025-001_ACHIZITIE_DIRECTA_PRAG" in stare["flags_anterioare"]
        assert "ad-2025-002_FRAGMENTARE" in stare["flags_anterioare"]

    def test_salveaza_contracte_vazute(self, tmp_path):
        """IDs contracte sunt salvate in contracte_vazute."""
        path = str(tmp_path / "stare.json")
        salveaza_stare(path, FLAGS_SAMPLE, CONTRACTE_SAMPLE)
        with open(path, encoding="utf-8") as f:
            stare = json.load(f)
        assert "ad-2025-100" in stare["contracte_vazute"]
        assert "ad-2025-101" in stare["contracte_vazute"]

    def test_salveaza_total_flags(self, tmp_path):
        """total_flags reflecta numarul corect de flag-uri."""
        path = str(tmp_path / "stare.json")
        salveaza_stare(path, FLAGS_SAMPLE, CONTRACTE_SAMPLE)
        with open(path, encoding="utf-8") as f:
            stare = json.load(f)
        assert stare["total_flags"] == len(FLAGS_SAMPLE)

    def test_salveaza_data_ultima_rulare(self, tmp_path):
        """data_ultima_rulare este populat (non-null)."""
        path = str(tmp_path / "stare.json")
        salveaza_stare(path, [], [])
        with open(path, encoding="utf-8") as f:
            stare = json.load(f)
        assert stare["data_ultima_rulare"] is not None
        assert "T" in stare["data_ultima_rulare"]  # format ISO

    def test_salveaza_fara_hcl(self, tmp_path):
        """hcl_list None nu crapa — hcl_urls_vazute devine lista goala."""
        path = str(tmp_path / "stare.json")
        salveaza_stare(path, [], [], hcl_list=None)
        with open(path, encoding="utf-8") as f:
            stare = json.load(f)
        assert stare["hcl_urls_vazute"] == []


# ===========================================================================
# TestDetecteazaFlagsNoi
# ===========================================================================

class TestDetecteazaFlagsNoi:

    def test_stare_goala_toate_sunt_noi(self):
        """Stare anterioara goala → toate flag-urile sunt 'noi'."""
        noi = detecteaza_flags_noi(FLAGS_SAMPLE, {"flags_anterioare": []})
        assert len(noi) == len(FLAGS_SAMPLE)

    def test_flag_deja_vazut_nu_apare(self):
        """Flag deja in starea anterioara → nu apare in lista noilor."""
        stare = {"flags_anterioare": ["ad-2025-001_ACHIZITIE_DIRECTA_PRAG"]}
        noi = detecteaza_flags_noi(FLAGS_SAMPLE, stare)
        ids_noi = [f["contract_id"] + "_" + f["tip"] for f in noi]
        assert "ad-2025-001_ACHIZITIE_DIRECTA_PRAG" not in ids_noi
        assert len(noi) == len(FLAGS_SAMPLE) - 1

    def test_toate_vazute_lista_goala(self):
        """Toate flag-urile deja in starea anterioara → lista goala."""
        stare = {
            "flags_anterioare": [
                f["contract_id"] + "_" + f["tip"] for f in FLAGS_SAMPLE
            ]
        }
        noi = detecteaza_flags_noi(FLAGS_SAMPLE, stare)
        assert noi == []

    def test_stare_anterioara_lipsa(self):
        """Stare anterioara fara cheia flags_anterioare → toate noi."""
        noi = detecteaza_flags_noi(FLAGS_SAMPLE, {})
        assert len(noi) == len(FLAGS_SAMPLE)

    def test_flags_curente_goale(self):
        """Fara flag-uri curente → lista goala indiferent de stare."""
        noi = detecteaza_flags_noi([], {"flags_anterioare": ["abc_FRAGMENTARE"]})
        assert noi == []


# ===========================================================================
# TestCalculeazaAnalitaPerTip
# ===========================================================================

class TestCalculeazaAnalitaPerTip:

    def test_lista_goala_rezultat_gol(self):
        """Fara flag-uri → lista goala."""
        result = calculeaza_analiza_per_tip([], [])
        assert result == []

    def test_tipuri_distincte(self):
        """Returneaza un item per tip distinct."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        tipuri = [r["tip"] for r in result]
        assert "FRAGMENTARE" in tipuri
        assert "ACHIZITIE_DIRECTA_PRAG" in tipuri
        assert len(tipuri) == 2  # 2 tipuri distincte

    def test_total_corect(self):
        """Campul 'total' reflecta numarul de flag-uri per tip."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        frag = next(r for r in result if r["tip"] == "FRAGMENTARE")
        assert frag["total"] == 2  # 2 flags FRAGMENTARE in sample

    def test_severitati_numarate_corect(self):
        """n_critic / n_major / n_mediu sunt corecte."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        frag = next(r for r in result if r["tip"] == "FRAGMENTARE")
        assert frag["n_critic"] == 2
        assert frag["n_major"] == 0
        achiz = next(r for r in result if r["tip"] == "ACHIZITIE_DIRECTA_PRAG")
        assert achiz["n_major"] == 1
        assert achiz["n_critic"] == 0

    def test_valoare_totala(self):
        """valoare_totala este suma valorilor flag-urilor per tip."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        frag = next(r for r in result if r["tip"] == "FRAGMENTARE")
        assert frag["valoare_totala"] == 270000 + 260000

    def test_top_furnizori_prezenti(self):
        """top_furnizori contine firmele cu cel mai mare total per tip."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        frag = next(r for r in result if r["tip"] == "FRAGMENTARE")
        firme = [f for f, _ in frag["top_furnizori"]]
        assert "FIRMA B" in firme

    def test_luni_prezente(self):
        """luni contine lunile cu contracte aferente."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        frag = next(r for r in result if r["tip"] == "FRAGMENTARE")
        luni_keys = [luna for luna, _ in frag["luni"]]
        assert "2025-04" in luni_keys
        assert "2025-05" in luni_keys

    def test_tip_necunoscut_are_label_fallback(self):
        """Tip nerecunoscut primeste label derivat din codul tipului."""
        flags = [{"contract_id": "x", "tip": "TIP_INEXISTENT",
                  "severitate": "MEDIU", "valoare": 10000, "furnizor": "F", "data": "2025-01-01"}]
        result = calculeaza_analiza_per_tip(flags, [])
        assert len(result) == 1
        assert result[0]["tip"] == "TIP_INEXISTENT"
        assert result[0]["label"] != ""

    def test_sortare_descrescatoare_dupa_total(self):
        """Tipul cu cele mai multe flag-uri apare primul."""
        result = calculeaza_analiza_per_tip(FLAGS_SAMPLE, [])
        assert result[0]["tip"] == "FRAGMENTARE"  # 2 vs 1


# ===========================================================================
# TestSlugify
# ===========================================================================

class TestSlugify:

    def test_ascii_simplu(self):
        """Nume ASCII simplu → lowercase cu cratime."""
        assert _slugify("MIDAS ROAD SRL") == "midas-road-srl"

    def test_diacritice_romanesti(self):
        """Diacriticele românești sunt transliterate corect."""
        assert _slugify("Servicii Șosele și Trotuare") == "servicii-sosele-si-trotuare"
        assert _slugify("Firmă cu Ț") == "firma-cu-t"
        assert _slugify("Âncă Înainte") == "anca-inainte"

    def test_caractere_speciale_eliminate(self):
        """Punctuatie, paranteze etc. sunt eliminate."""
        slug = _slugify("FIRMA & CO. (BUCHAREST)")
        assert "&" not in slug
        assert "." not in slug
        assert "(" not in slug

    def test_spatii_multiple_devin_cratime_singulare(self):
        """Spatii multiple → un singur cratima."""
        slug = _slugify("FIRMA   MARE   SRL")
        assert "--" not in slug
        assert slug == "firma-mare-srl"

    def test_truncare_la_60_chars(self):
        """Slug-ul nu depaseste 60 caractere."""
        lung = "Societatea Comerciala de Constructii si Servicii Publice Generale SRL"
        slug = _slugify(lung)
        assert len(slug) <= 60

    def test_sir_gol_returneaza_furnizor(self):
        """String gol sau doar caractere speciale → 'furnizor'."""
        assert _slugify("") == "furnizor"
        assert _slugify("!!!") == "furnizor"

    def test_fara_cratime_la_margini(self):
        """Slug-ul nu incepe sau termina cu cratima."""
        slug = _slugify("  - FIRMA -  ")
        assert not slug.startswith("-")
        assert not slug.endswith("-")


# ===========================================================================
# TestDetectFlagSimple
# ===========================================================================

class TestDetectFlagSimple:

    def test_peste_prag_critic(self):
        """Valoare servicii > 270.120 RON → CRITIC."""
        c = {"valoare": 300000, "firma": "F", "ofertanti": 2}
        assert _detect_flag_simple(c, {}) == "CRITIC"

    def test_exact_la_prag_critic(self):
        """Valoare = 270.121 → CRITIC."""
        c = {"valoare": 270121, "firma": "F", "ofertanti": 2}
        assert _detect_flag_simple(c, {}) == "CRITIC"

    def test_aproape_de_prag_major(self):
        """Valoare intre 97% si 100% din prag → MAJOR."""
        c = {"valoare": 265000, "firma": "F", "ofertanti": 2}
        assert _detect_flag_simple(c, {}) == "MAJOR"

    def test_valoare_mai_mica_decat_97pct_ok(self):
        """Valoare < 97% din prag, 1 ofertant sub 50k → OK."""
        c = {"valoare": 40000, "firma": "F", "ofertanti": 3}
        assert _detect_flag_simple(c, {}) == "OK"

    def test_ofertant_unic_mediu(self):
        """1 ofertant si valoare > 50.000 → MEDIU."""
        c = {"valoare": 80000, "firma": "F", "ofertanti": 1}
        assert _detect_flag_simple(c, {}) == "MEDIU"

    def test_ofertant_unic_sub_50k_ok(self):
        """1 ofertant dar valoare <=50k → OK (sub pragul de interes)."""
        c = {"valoare": 30000, "firma": "F", "ofertanti": 1}
        assert _detect_flag_simple(c, {}) == "OK"

    def test_suma_firma_depaseste_pragul_major(self):
        """Firma cu total >270.120 și contract > jumătate din prag → MAJOR."""
        c = {"valoare": 150000, "firma": "FRAG SRL", "ofertanti": 2}
        firma_sums = {("FRAG SRL", "produse/servicii"): 300000}
        assert _detect_flag_simple(c, firma_sums) == "MAJOR"

    def test_valoare_zero_ok(self):
        """Valoare 0 → OK."""
        c = {"valoare": 0, "firma": "F", "ofertanti": 0}
        assert _detect_flag_simple(c, {}) == "OK"

    def test_valoare_none_ok(self):
        """Valoare None → OK (fara crash)."""
        c = {"valoare": None, "firma": "F", "ofertanti": 0}
        assert _detect_flag_simple(c, {}) == "OK"


# ===========================================================================
# TestRenderContracteTbodyRows
# ===========================================================================

class TestRenderContracteTbodyRows:

    def test_lista_goala_mesaj_gol(self):
        """Lista goala → randul 'Nicio dată disponibila'."""
        result = render_contracte_tbody_rows([])
        assert "Nicio" in result
        assert "<tr" in result

    def test_returneaza_string(self):
        """Functia returneaza intotdeauna un string."""
        result = render_contracte_tbody_rows(CONTRACTE_SAMPLE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_numar_randuri_limitat(self):
        """top_n limiteaza numarul de randuri returnate."""
        result_all = render_contracte_tbody_rows(CONTRACTE_SAMPLE, top_n=100)
        result_1 = render_contracte_tbody_rows(CONTRACTE_SAMPLE, top_n=1)
        assert result_1.count("<tr") < result_all.count("<tr")

    def test_sortare_dupa_valoare(self):
        """Contractul cu cea mai mare valoare apare primul in HTML."""
        result = render_contracte_tbody_rows(CONTRACTE_SAMPLE, top_n=10)
        pos_350k = result.find("350")
        pos_135k = result.find("135")
        assert pos_350k < pos_135k

    def test_xss_escape_titlu(self):
        """Titluri cu caractere HTML sunt escapate."""
        contracte_xss = [{
            "id": "x-001",
            "titlu": "<script>alert('xss')</script>",
            "valoare": 50000,
            "firma": "F",
            "ofertanti": 1,
        }]
        result = render_contracte_tbody_rows(contracte_xss)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_flag_critic_in_html(self):
        """Contract peste prag → clasa sev-critic in HTML."""
        contracte = [{
            "id": "x-002",
            "titlu": "Contract mare",
            "valoare": 300000,
            "firma": "BIG SRL",
            "ofertanti": 0,
        }]
        result = render_contracte_tbody_rows(contracte)
        assert "sev-critic" in result

    def test_contract_normal_sev_ok(self):
        """Contract normal → sev-ok in HTML."""
        contracte = [{
            "id": "x-003",
            "titlu": "Serviciu mic",
            "valoare": 10000,
            "firma": "SMALL SRL",
            "ofertanti": 3,
        }]
        result = render_contracte_tbody_rows(contracte)
        assert "sev-ok" in result

    def test_steag_rosu_la_neregula(self):
        """Contract cu flag adauga pictograma steag in HTML."""
        contracte = [{
            "id": "x-004",
            "titlu": "Contract suspect",
            "valoare": 140000,
            "firma": "SUSPECT SRL",
            "ofertanti": 1,
        }]
        result = render_contracte_tbody_rows(contracte)
        assert "🚩" in result
