"""
tests/test_press_kit.py
§5.1 Generare press kit JSON + Markdown — teste unitare

Toate testele rulează offline (fără rețea).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitor_pantelimon import genereaza_press_kit


# ── Fixture helpers ──────────────────────────────────────────────────────────

CONFIG_TEST = {
    "nume_entitate": "Primăria Pantelimon",
    "cui": "4420759",
    "judet": "IF",
    "email_to": "test@example.com",
    "uat_search": "Pantelimon",
}

NEREGULI_OK = [
    {
        "titlu": "Achiziție directă aproape de prag",
        "severitate": "CRITIC",
        "descriere": "Valoare apropiată de pragul legal.",
        "furnizor": "FIRMA ALPHA SRL",
        "valoare": 128_000,
        "data": "2025-03-10",
        "tip": "ACHIZITIE_DIRECTA_APROAPE_PRAG",
        "contract_id": "achizitie-directa-2025-001",
    },
    {
        "titlu": "Fragmentare artificială",
        "severitate": "MAJOR",
        "descriere": "Contracte similare fracționate.",
        "furnizor": "FIRMA BETA SRL",
        "valoare": 250_000,
        "data": "2025-04-01",
        "tip": "FRAGMENTARE_ARTIFICIALA",
        "contract_id": "achizitie-directa-2025-002",
    },
    {
        "titlu": "Furnizor monopol",
        "severitate": "MEDIU",
        "descriere": "Același furnizor pe 90% din contracte.",
        "furnizor": "FIRMA GAMMA SRL",
        "valoare": 75_000,
        "data": "2025-05-15",
        "tip": "FURNIZOR_MONOPOL",
        "contract_id": "achizitie-directa-2025-003",
    },
]

CONTRACTE_OK = [
    {"castigator": "FIRMA ALPHA SRL", "valoare_ron": 128_000},
    {"castigator": "FIRMA ALPHA SRL", "valoare_ron": 95_000},
    {"castigator": "FIRMA BETA SRL",  "valoare_ron": 250_000},
    {"castigator": "FIRMA GAMMA SRL", "valoare_ron": 75_000},
    {"castigator": "",                "valoare_ron": 10_000},  # fără câștigător
]

SCOR_OK = {"scor": 42, "detalii": {}}


# ── §5.1 genereaza_press_kit ──────────────────────────────────────────────────

class TestGenereazaPressKit:

    def test_returneaza_dict(self, tmp_path, monkeypatch):
        """Funcția returnează un dict."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        assert isinstance(rez, dict)

    def test_schema_version_prezenta(self, tmp_path, monkeypatch):
        """Câmpul schema_version este prezent."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        assert rez.get("schema_version") == "1.1"

    def test_statistici_corecte(self, tmp_path, monkeypatch):
        """Statisticile reflectă datele de intrare."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        st = rez["statistici"]
        assert st["total_nereguli"] == 3
        assert st["critice"] == 1
        assert st["majore"] == 1
        assert st["medii"] == 1
        assert st["total_contracte"] == len(CONTRACTE_OK)
        assert st["scor_transparenta"] == 42

    def test_top_nereguli_sortat_critic_primul(self, tmp_path, monkeypatch):
        """Top nereguli: CRITIC înaintea MAJOR și MEDIU."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        top = rez["top_nereguli"]
        assert len(top) >= 1
        assert top[0]["severitate"] == "CRITIC"

    def test_top_nereguli_maxim_10(self, tmp_path, monkeypatch):
        """Top nereguli conține cel mult 10 intrări."""
        nereguli_many = [
            {
                "titlu": f"Neregulă {i}",
                "severitate": "MEDIU",
                "descriere": "desc",
                "furnizor": f"FIRMA {i} SRL",
                "valoare": 10_000 * i,
                "data": "2025-01-01",
                "tip": "TEST",
                "contract_id": f"c-{i}",
            }
            for i in range(1, 16)
        ]
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(nereguli_many, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        assert len(rez["top_nereguli"]) <= 10

    def test_top_firme_sortat_dupa_valoare(self, tmp_path, monkeypatch):
        """Top firme: firma cu cea mai mare valoare e prima."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        top = rez["top_firme"]
        assert len(top) >= 2
        assert top[0]["valoare_ron"] >= top[1]["valoare_ron"]

    def test_firma_fara_castigator_exclusa(self, tmp_path, monkeypatch):
        """Contractele fără câștigător nu apar în top firme."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        for firma in rez["top_firme"]:
            assert firma["nume"] != ""

    def test_scrie_press_kit_json(self, tmp_path, monkeypatch):
        """Fișierul press_kit.json este scris pe disc."""
        monkeypatch.chdir(tmp_path)
        genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        json_path = tmp_path / "press_kit.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "statistici" in data

    def test_scrie_press_kit_md(self, tmp_path, monkeypatch):
        """Fișierul press_kit.md este scris pe disc."""
        monkeypatch.chdir(tmp_path)
        genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, SCOR_OK, CONFIG_TEST)
        md_path = tmp_path / "press_kit.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Press kit" in content
        assert "Statistici" in content

    def test_nereguli_goale_nu_crasha(self, tmp_path, monkeypatch):
        """Funcția nu aruncă excepție cu liste goale."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit([], [], {}, CONFIG_TEST)
        assert rez["statistici"]["total_nereguli"] == 0
        assert rez["top_nereguli"] == []
        assert rez["top_firme"] == []

    def test_scor_none_nu_crasha(self, tmp_path, monkeypatch):
        """Scor None → scor_transparenta este None în output."""
        monkeypatch.chdir(tmp_path)
        rez = genereaza_press_kit(NEREGULI_OK, CONTRACTE_OK, None, CONFIG_TEST)
        assert rez["statistici"]["scor_transparenta"] is None

    def test_json_valid_utf8(self, tmp_path, monkeypatch):
        """press_kit.json este JSON valid cu caractere UTF-8 corecte."""
        monkeypatch.chdir(tmp_path)
        nereguli_unicode = [{
            "titlu": "Achiziție cu caractere speciale: ș, ț, â, î, ă",
            "severitate": "CRITIC",
            "descriere": "Descriere în română.",
            "furnizor": "FIRMĂ SPECIALĂ SRL",
            "valoare": 100_000,
            "data": "2025-01-01",
            "tip": "TEST",
            "contract_id": "c-unicode",
        }]
        genereaza_press_kit(nereguli_unicode, [], SCOR_OK, CONFIG_TEST)
        raw = (tmp_path / "press_kit.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["top_nereguli"][0]["furnizor"] == "FIRMĂ SPECIALĂ SRL"
