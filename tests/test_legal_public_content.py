"""Gărzi pentru praguri legale și afirmații publice sensibile."""

from pathlib import Path

from bs4 import BeautifulSoup

from config import (
    PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON,
    PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON,
)
from monitor_pantelimon import _detect_flag_simple, _prag_pentru_contract


ROOT = Path(__file__).resolve().parent.parent


def test_praguri_centralizate_curente():
    assert PRAG_ACHIZITIE_DIRECTA_PRODUSE_SERVICII_RON == 270_120
    assert PRAG_ACHIZITIE_DIRECTA_LUCRARI_RON == 900_400


def test_pragul_selectat_dupa_categoria_contractului():
    assert _prag_pentru_contract({"titlu": "Servicii de curățenie"}) == (270_120, "produse/servicii")
    assert _prag_pentru_contract({"titlu": "Lucrări de reabilitare drum"}) == (900_400, "lucrări")


def test_lucrari_sub_pragul_lor_nu_sunt_marcat_critic():
    contract = {"titlu": "Lucrări de reabilitare", "valoare": 500_000, "firma": "F"}
    assert _detect_flag_simple(contract, {("F", "lucrări"): 500_000}) != "CRITIC"


def test_formularul_placeholder_nu_mai_exista():
    petitie = (ROOT / "petitie.html").read_text(encoding="utf-8")
    assert "YOUR_FORM_ID" not in petitie
    assert "formspree.io" not in petitie
    assert "Colectarea online a semnăturilor este indisponibilă" in petitie


def test_paginile_metodologice_nu_citeaza_legea_abrogata():
    for filename in ("despre.html", "presa.html"):
        content = (ROOT / filename).read_text(encoding="utf-8")
        assert "L215/2001" not in content
        assert "Legea 363/2018" not in content


def test_linkurile_externe_din_index_folosesc_noopener():
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    for fragment in index.split('target="_blank"')[1:]:
        tag_tail = fragment.split(">", 1)[0]
        assert "noopener" in tag_tail


def test_toate_linkurile_externe_generate_folosesc_noopener():
    for path in ROOT.rglob("*.html"):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for link in soup.find_all("a", target="_blank"):
            assert "noopener" in (link.get("rel") or []), f"Lipsește noopener în {path}: {link.get('href')}"


def test_paginile_publice_nu_pastreaza_praguri_sau_afirmatii_vechi():
    texte = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.html"))
    for fragment in (
        "130.000 RON",
        "L215/2001",
        "Legea 363/2018",
        "YOUR_FORM_ID",
        "nu e coincidență — e un pattern sistematic",
    ):
        assert fragment not in texte
