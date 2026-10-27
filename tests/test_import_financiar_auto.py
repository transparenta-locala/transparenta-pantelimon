"""Importul automat al situațiilor financiare ANAF (cel mai recent an de pe data.gov.ro).

Până în oct. 2026 anul era scris fix („--an 2024” în workflow), așa că situațiile pe 2025,
publicate pe 14.10.2026, n-ar fi fost preluate niciodată de rularea automată.
"""
import io
import json
import os
import sys
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import import_financiar_datagov as imp  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _pachet(an, fisiere):
    return _Resp(json.dumps({"success": True, "result": {"resources": [
        {"name": f, "url": f"https://data.gov.ro/x/{f.lower()}"} for f in fisiere]}}).encode())


def test_descopera_doar_fisierele_bl_si_uu():
    fis = [f"WEB_BL_BS_SL_AN2025.txt", "WEB_UU_AN2025.txt", "WEB_ONG_AN2025.txt", "WEB_BL_BS_SL_AN2025.csv"]
    with mock.patch("urllib.request.urlopen", return_value=_pachet(2025, fis)):
        r = imp.descopera_resurse_an(2025)
    assert set(r) == {"", "-uu"}            # ONG are altă numerotare a indicatorilor
    assert r[""].endswith("web_bl_bs_sl_an2025.txt")


def test_an_nepublicat_404_inseamna_gol():
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        assert imp.descopera_resurse_an(2026) == {}


def test_an_in_date_citeste_si_sufixele(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"1": {"an": "2024-uu"}, "2": {"an": "2025"}}), encoding="utf-8")
    assert imp.an_in_date(str(p)) == 2025
    assert imp.an_in_date(str(tmp_path / "lipsa.json")) == 0


def test_nu_descarca_daca_anul_nu_e_mai_nou(monkeypatch):
    monkeypatch.setattr(imp, "an_in_date", lambda *a: 2025)
    monkeypatch.setattr(imp, "descopera_resurse_an", lambda an: {"": "u", "-uu": "v"} if an == 2025 else {})
    descarcari = []
    monkeypatch.setattr(imp, "descarca_cu_reluare", lambda url: descarcari.append(url))
    assert imp.import_automat() == 0
    assert descarcari == []


def test_portal_indisponibil_nu_opreste_rularea(monkeypatch, capsys):
    def _cade(an):
        raise TimeoutError("connect timeout")
    monkeypatch.setattr(imp, "descopera_resurse_an", _cade)
    assert imp.import_automat() == 0
    assert "::warning::" in capsys.readouterr().out


def test_cui_din_contracte(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"cui": "RO 123"}, {"cui": "456"}, {"cui": ""}]), encoding="utf-8")
    assert imp.get_cui_set_from_contracte(str(p)) == {123, 456}
