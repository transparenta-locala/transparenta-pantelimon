"""Teste fără rețea pentru sursa_seap_api.py (contractele din API-ul public SEAP).

Datele de test sunt rânduri reale, scurtate, din API-ul SEAP (Primăria Pantelimon).
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sursa_seap_api as S  # noqa: E402


def da(id_, cod, pub, valoare, furnizor, stare=7, cpv="71354300-7 - Servicii cadastrale (Rev.2)",
       fin=None):
    return {
        "directAcquisitionId": id_, "uniqueIdentificationCode": cod,
        "directAcquisitionName": "Servicii Cadastrale",
        "sysDirectAcquisitionState": {"id": stare, "text": "x"},
        "cpvCode": cpv, "publicationDate": pub + "T16:02:00+02:00",
        "finalizationDate": (fin or pub) + "T16:28:00+02:00",
        "supplier": furnizor, "closingValue": valoare, "estimatedValueRon": valoare,
    }


ANUNT_SCOLI = {
    "caNoticeId": 100566166, "noticeNo": "CAN1151813", "noticeStateDate": "2025-08-05T10:00:00+03:00",
    "sysProcedureType": {"id": 1, "text": "Licitatie deschisa"},
    "cpvCodeAndName": "45214210-5 - Lucrari de constructii de scoli gimnaziale (Rev.2)",
    "contractTitle": "Construire scoala",
}
CONTRACT_ASOCIERE = {
    "caNoticeContractId": 108000001, "contractNo": "120", "contractDate": "2025-07-29T00:00:00+03:00",
    "contractTitle": "Contract de lucrari", "contractType": 1,
    "defaultCurrencyContractValue": 29508940.74, "contractValue": 29508940.74,
    "winners": [{"name": "ALA EXPERT CONSTRUCT", "fiscalNumber": "RO30056330"},
                {"name": "YARDMAN", "fiscalNumber": "RO 28250562"},
                {"name": "SANTIA PARTNER CONSTRUCT", "fiscalNumber": "27702350"}],
}


# ── funcții pure ──────────────────────────────────────────────────────────────

class TestFunctiiPure:
    def test_ferestre_lunare_acopera_intervalul(self):
        f = S.ferestre_lunare(date(2025, 11, 15), date(2026, 2, 3))
        assert f == [(date(2025, 11, 1), date(2025, 12, 1)), (date(2025, 12, 1), date(2026, 1, 1)),
                     (date(2026, 1, 1), date(2026, 2, 1)), (date(2026, 2, 1), date(2026, 3, 1))]

    @pytest.mark.parametrize("text,asteptat", [
        ("RO 14399840", "14399840"), ("ro27019056", "27019056"), ("35253022 KSA ROAD", "35253022"),
        ("", ""), (None, ""), ("FARA CUI", ""),
    ])
    def test_cifre_cui(self, text, asteptat):
        assert S.cifre_cui(text) == asteptat

    def test_separa_furnizor(self):
        assert S.separa_furnizor("RO37154246 HIDROCONSTRUCT SUD") == ("37154246", "HIDROCONSTRUCT SUD")
        assert S.separa_furnizor("35253022 KSA ROAD SERVICES") == ("35253022", "KSA ROAD SERVICES")
        assert S.separa_furnizor("Firma fara cod") == ("", "Firma fara cod")

    def test_denumire_cpv(self):
        assert S.denumire_cpv("22212100-0 - Publicatii periodice (Rev.2)") == "Publicatii periodice (Rev.2)"
        assert S.denumire_cpv("") == "Nespecificat"
        assert S.denumire_cpv("text liber") == "text liber"


class TestNormalizare:
    def test_da_acceptata(self):
        r = S.normalizeaza_da(da(118853764, "DA37312670", "2025-01-16", 270000.0,
                                 "RO25145252 CONSTOPOGRAF EXPERT"))
        assert r["castigator"] == "CONSTOPOGRAF EXPERT" and r["castigator_cui"] == "25145252"
        assert r["valoare_ron"] == 270000.0 and r["data_publicare"] == "2025-01-16"
        assert r["titlu"] == "Servicii cadastrale (Rev.2)"
        assert r["cod_seap"] == "DA37312670"
        assert r["url_seap"] == "https://e-licitatie.ro/pub/direct-acquisition/view/118853764"
        assert r["cheie_seap"] == "da:118853764" and r["tip_contract"] == "achizitie-directa"
        assert r["id"] == "achizitie-directa-2025-118853764"

    @pytest.mark.parametrize("stare", [1, 3, 5, 8, None])
    def test_da_neacceptata_e_exclusa(self, stare):
        """Ofertă refuzată / condiții refuzate etc. nu sunt achiziții făcute."""
        assert S.normalizeaza_da(da(1, "DA1", "2026-02-12", 91000.0, "RO25535239 PERCONS EU",
                                    stare=stare)) is None

    def test_contract_asociere_un_rand_pe_membru_aceeasi_cheie(self):
        r = S.normalizeaza_contracte_can(ANUNT_SCOLI, [CONTRACT_ASOCIERE])
        assert [x["castigator"] for x in r] == ["ALA EXPERT CONSTRUCT", "YARDMAN", "SANTIA PARTNER CONSTRUCT"]
        assert [x["castigator_cui"] for x in r] == ["30056330", "28250562", "27702350"]
        assert len({x["cheie_seap"] for x in r}) == 1
        assert len({x["id"] for x in r}) == 3
        assert all(x["valoare_ron"] == 29508940.74 for x in r)
        assert r[1]["asociere"] == ["ALA EXPERT CONSTRUCT", "SANTIA PARTNER CONSTRUCT"]
        assert r[0]["tip_procedura"] == "Licitatie deschisa" and r[0]["nr_ofertanti"] == 2
        assert r[0]["titlu"] == "Lucrari de constructii de scoli gimnaziale (Rev.2)"
        assert r[0]["url_seap"] == "https://e-licitatie.ro/pub/notices/ca-notices/view-c/100566166"
        assert r[0]["cod_seap"] == "CAN1151813" and r[0]["data_publicare"] == "2025-07-29"

    @pytest.mark.parametrize("tip,asteptat", [(1, "contract"), (2, "acord-cadru"), (3, "subsecvent")])
    def test_tip_contract(self, tip, asteptat):
        c = dict(CONTRACT_ASOCIERE, contractType=tip)
        assert S.normalizeaza_contracte_can(ANUNT_SCOLI, [c])[0]["tip_contract"] == asteptat

    def test_procedura_simplificata_un_ofertant_dedus(self):
        anunt = dict(ANUNT_SCOLI, sysProcedureType={"id": 2, "text": "Procedura simplificata"})
        assert S.normalizeaza_contracte_can(anunt, [CONTRACT_ASOCIERE])[0]["nr_ofertanti"] == 1

    def test_deduplica_acelasi_contract_in_doua_anunturi(self):
        r1 = S.normalizeaza_contracte_can(ANUNT_SCOLI, [CONTRACT_ASOCIERE])
        alt = dict(CONTRACT_ASOCIERE, caNoticeContractId=108999999)
        r2 = S.normalizeaza_contracte_can(dict(ANUNT_SCOLI, caNoticeId=1, noticeNo="CAN2"), [alt])
        d1 = S.normalizeaza_da(da(5, "DA5", "2025-01-02", 10.0, "1234 X"))
        assert len(S.deduplica(r1 + r2 + [d1, dict(d1)])) == 4


# ── păstrarea id-urilor și numelor din contracte.json ────────────────────────

class TestPastrare:
    def test_da_potrivita_dupa_cui_valoare_data(self):
        noi = [S.normalizeaza_da(da(118853764, "DA37312670", "2025-01-16", 270000.0,
                                    "RO25145252 CONSTOPOGRAF EXPERT"))]
        vechi = [{"id": "achizitie-directa-2025-51666", "valoare": 270000.0, "data": "2025-01-16",
                  "cui": "25145252", "firma": "CONSTOPOGRAF EXPERT"}]
        assert S.pastreaza_id_uri(noi, vechi) == 1
        assert noi[0]["id"] == "achizitie-directa-2025-51666"
        # linkul rămâne cel real
        assert noi[0]["url_seap"].endswith("/118853764")

    def test_da_cu_valoare_diferita_nu_se_potriveste(self):
        noi = [S.normalizeaza_da(da(7, "DA7", "2025-01-16", 270000.0, "RO25145252 C"))]
        vechi = [{"id": "achizitie-directa-2025-1", "valoare": 269000.0, "data": "2025-01-16", "cui": "25145252"}]
        assert S.pastreaza_id_uri(noi, vechi) == 0
        assert noi[0]["id"] == "achizitie-directa-2025-7"

    def test_contract_potrivit_cu_valoare_actualizata(self):
        """SEAP actualizează valoarea după acte adiționale (±5% acceptat)."""
        noi = S.normalizeaza_contracte_can(ANUNT_SCOLI, [dict(CONTRACT_ASOCIERE, defaultCurrencyContractValue=30_500_000.0)])
        vechi = [{"id": "contract-2025-58067", "valoare": 29508940.0, "data": "2025-07-29", "cui": "RO30056330"},
                 {"id": "contract-2025-58068", "valoare": 29508940.0, "data": "2025-07-29", "cui": "RO27702350"},
                 {"id": "contract-2025-58069", "valoare": 29508940.0, "data": "2025-07-29", "cui": "RO28250562"}]
        assert S.pastreaza_id_uri(noi, vechi) == 3
        assert [x["id"] for x in noi] == ["contract-2025-58067", "contract-2025-58069", "contract-2025-58068"]

    def test_da_nu_ia_id_de_contract(self):
        noi = [S.normalizeaza_da(da(9, "DA9", "2025-07-29", 100.0, "30056330 ALA"))]
        vechi = [{"id": "contract-2025-58067", "valoare": 100.0, "data": "2025-07-29", "cui": "30056330"}]
        assert S.pastreaza_id_uri(noi, vechi) == 0

    def test_rulare_urmatoare_potriveste_dupa_cheie(self):
        noi = [S.normalizeaza_da(da(118853764, "DA37312670", "2025-01-16", 999.0, "RO25145252 C"))]
        vechi = [{"id": "achizitie-directa-2025-51666", "valoare": 270000.0, "data": "2024-01-01",
                  "cui": "25145252", "k": "da:118853764"}]
        assert S.pastreaza_id_uri(noi, vechi) == 1 and noi[0]["id"] == "achizitie-directa-2025-51666"

    def test_un_id_vechi_nu_e_dat_de_doua_ori(self):
        noi = [S.normalizeaza_da(da(1, "DA1", "2025-03-01", 500.0, "11 F")),
               S.normalizeaza_da(da(2, "DA2", "2025-03-01", 500.0, "11 F"))]
        vechi = [{"id": "achizitie-directa-2025-3", "valoare": 500.0, "data": "2025-03-01", "cui": "11"}]
        assert S.pastreaza_id_uri(noi, vechi) == 1
        assert len({x["id"] for x in noi}) == 2

    def test_nume_firma_publicat_e_pastrat(self):
        noi = [S.normalizeaza_da(da(1, "DA1", "2025-03-01", 5.0, "RO24299482 FANPLACE IT")),
               S.normalizeaza_da(da(2, "DA2", "2025-03-01", 5.0, "999 FIRMA NOUA"))]
        vechi = [{"id": "a", "firma": "FANPLACE iT SRL", "cui": "RO 24299482"},
                 {"id": "b", "firma": "FANPLACE iT SRL", "cui": "24299482"},
                 {"id": "c", "firma": "FANPLACE IT", "cui": "24299482"}]
        assert S.pastreaza_nume_firme(noi, vechi) == 1
        assert noi[0]["castigator"] == "FANPLACE iT SRL"
        assert noi[1]["castigator"] == "FIRMA NOUA"


class TestPlauzibil:
    START = date(2025, 1, 1)

    def _rows(self, n, zi="2025-06-01", da_=False):
        pref = "achizitie-directa-2025-" if da_ else "contract-2025-"
        return [{"id": f"{pref}{i}", "data_publicare": zi} for i in range(n)]

    def test_complet_e_acceptat(self):
        assert S.verifica_plauzibil(self._rows(100), self._rows(100), self.START) == ""

    def test_trunchiat_e_respins(self):
        assert "incomplet" in S.verifica_plauzibil(self._rows(40), self._rows(100), self.START)

    def test_gol_e_respins(self):
        assert S.verifica_plauzibil([], self._rows(10), self.START)

    def test_fara_istoric_accepta_orice_nevid(self):
        assert S.verifica_plauzibil(self._rows(3), [], self.START) == ""

    def test_lipsa_contractelor_din_atribuiri_e_respinsa(self):
        """Doar DA, fără contractele din anunțuri (87% din valoare) → respins."""
        vechi = self._rows(300, da_=True) + self._rows(20)
        nou = self._rows(300, da_=True)
        assert "anunțuri de atribuire" in S.verifica_plauzibil(nou, vechi, self.START)

    def test_trecerea_in_anul_nou_nu_respinge_date_bune(self):
        """La 5 ian. 2027 fereastra începe la 1 ian. 2026: rândurile din 2025 din rularea
        anterioară nu trebuie comparate cu noile date."""
        vechi = (self._rows(400, "2025-05-01", True) + self._rows(300, "2026-05-01", True)
                 + self._rows(10, "2023-09-11"))
        nou = self._rows(305, "2026-05-01", True) + self._rows(10, "2023-09-11")
        assert S.verifica_plauzibil(nou, vechi, date(2026, 1, 1)) == ""


# ── client HTTP și fluxul complet, cu server simulat ─────────────────────────

class RaspunsFals:
    def __init__(self, status=200, json_=None, text=None):
        self.status_code = status
        self._json = json_
        self.text = text if text is not None else ("{}" if json_ is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("nu e json")
        return self._json


class SesiuneFalsa:
    def __init__(self, raspunsuri):
        self.headers = {}
        self.raspunsuri = list(raspunsuri)
        self.cereri = []

    def request(self, metoda, url, json=None, timeout=None, headers=None):
        self.cereri.append((metoda, url, json, headers))
        r = self.raspunsuri.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(url, json) if callable(r) else r


def client(raspunsuri, **kw):
    pauze = []
    c = S.ClientSeap(sesiune=SesiuneFalsa(raspunsuri), dormi=pauze.append, **kw)
    return c, pauze


class TestClient:
    def test_referer_trimis(self):
        c, _ = client([RaspunsFals(json_={"ok": 1})])
        assert c.cerere("GET", "/api-pub/x", "/pub/y") == {"ok": 1}
        assert c.s.cereri[0][3]["Referer"] == "https://e-licitatie.ro/pub/y"

    @pytest.mark.parametrize("status", [403, 429])
    def test_refuz_opreste_imediat(self, status):
        c, _ = client([RaspunsFals(status, text="nu")])
        with pytest.raises(S.SeapBlocat):
            c.cerere("GET", "/x", "/y")
        assert c.cereri == 1

    def test_pagina_acces_restrictionat(self):
        c, _ = client([RaspunsFals(200, text="<html><body>Acces restricționat</body></html>")])
        with pytest.raises(S.SeapBlocat):
            c.cerere("GET", "/x", "/y")

    def test_eroare_server_reincercata_apoi_abandon(self):
        c, pauze = client([RaspunsFals(502, text="x")] * 3)
        with pytest.raises(S.SeapIndisponibil):
            c.cerere("GET", "/x", "/y")
        assert c.cereri == 3 and pauze  # a așteptat între încercări

    def test_plafon_de_cereri(self):
        c, _ = client([RaspunsFals(json_={})] * 3, max_cereri=2)
        c.cerere("GET", "/a", "/r")
        c.cerere("GET", "/a", "/r")
        with pytest.raises(S.SeapIndisponibil):
            c.cerere("GET", "/a", "/r")

    def test_pauza_intre_cereri(self):
        c, pauze = client([RaspunsFals(json_={})] * 2, pauza=2.0)
        c.cerere("GET", "/a", "/r")
        c.cerere("GET", "/a", "/r")
        assert pauze and 0 < pauze[0] <= 2.0


def server_simulat(lista_da_pe_luna, anunturi, contracte_pe_anunt):
    def raspunde(url, corp):
        if "GetDirectAcquisitionList" in url:
            luna = corp["finalizationDateStart"][:7]
            items = lista_da_pe_luna.get(luna, [])
            return RaspunsFals(json_={"total": len(items), "items": items})
        if "GetCANoticeList" in url:
            return RaspunsFals(json_={"total": len(anunturi), "items": anunturi})
        if "GetCANoticeContracts" in url:
            items = contracte_pe_anunt.get(corp["caNoticeId"], [])
            return RaspunsFals(json_={"total": len(items), "items": items})
        return RaspunsFals(404, text="?")
    return raspunde


class TestFluxComplet:
    def test_aduce_da_si_contracte_si_pastreaza_id_uri(self):
        luni = {"2025-01": [da(118853764, "DA37312670", "2025-01-16", 270000.0, "RO25145252 CONSTOPOGRAF EXPERT"),
                            da(2, "DA2", "2025-01-20", 50.0, "RO1 X", stare=3),
                            da(3, "DA3", "2024-12-30", 9.0, "77 Y", fin="2025-01-02")]}
        vechi_anunt = dict(ANUNT_SCOLI, caNoticeId=1, noticeNo="CAN-VECHI", noticeStateDate="2024-03-01T00:00:00")
        raspunde = server_simulat(luni, [ANUNT_SCOLI, vechi_anunt],
                                  {100566166: [CONTRACT_ASOCIERE], 1: [CONTRACT_ASOCIERE]})
        n_luni = len(S.ferestre_lunare(date(2025, 1, 1), date(2026, 3, 10)))
        c, _ = client([raspunde] * (n_luni + 2))
        vechi = [{"id": "achizitie-directa-2025-51666", "valoare": 270000.0, "data": "2025-01-16", "cui": "25145252"}]
        rez, jurnal = S.fetch_contracte_seap_api(vechi, azi=date(2026, 3, 10), client=c)
        ids = [r["id"] for r in rez]
        assert "achizitie-directa-2025-51666" in ids            # id păstrat
        assert not any(r["cheie_seap"] == "da:2" for r in rez)  # refuzată → exclusă
        assert not any(r["cheie_seap"] == "da:3" for r in rez)  # publicată înainte de interval
        assert sum(1 for r in rez if r["cheie_seap"] == "can:108000001") == 3
        assert not any(r["cod_seap"] == "CAN-VECHI" for r in rez)  # anunț din afara intervalului
        assert c.cereri == n_luni + 2
        assert any("id-uri pastrate" in j for j in jurnal)

    def test_blocare_la_jumatate_nu_intoarce_date_partiale(self):
        luni = {"2025-01": [da(1, "DA1", "2025-01-16", 1.0, "1 X")]}
        raspunde = server_simulat(luni, [], {})
        c, _ = client([raspunde, RaspunsFals(403, text="blocat")])
        with pytest.raises(S.SeapBlocat):
            S.fetch_contracte_seap_api([], azi=date(2025, 3, 10), client=c)


# ── integrarea în monitor ─────────────────────────────────────────────────────

class TestExportMonitor:
    def test_export_si_inapoi_pastreaza_campurile_seap(self):
        from monitor_pantelimon import contract_din_export, contract_pentru_export
        r = S.normalizeaza_contracte_can(ANUNT_SCOLI, [CONTRACT_ASOCIERE])[0]
        exp = contract_pentru_export(r)
        assert exp["cod"] == "CAN1151813" and exp["k"] == "can:108000001" and exp["tipc"] == "contract"
        assert exp["url"].endswith("/view-c/100566166")
        inapoi = contract_din_export(exp)
        assert inapoi["cheie_seap"] == r["cheie_seap"] and inapoi["url_seap"] == r["url_seap"]
        assert inapoi["valoare_ron"] == r["valoare_ron"] and inapoi["castigator"] == r["castigator"]

    def test_export_vechi_fara_campuri_seap_ramane_la_fel(self):
        from monitor_pantelimon import contract_din_export, contract_pentru_export
        vechi = {"id": "achizitie-directa-2025-2637", "titlu": "Publicatii periodice (Rev.2)", "valoare": 66000.0,
                 "data": "2025-01-08", "tip": "", "firma": "X", "cui": "26181156", "ofertanti": 1}
        assert contract_pentru_export(contract_din_export(vechi)) == vechi


class TestTotaluri:
    def test_asocierea_se_numara_o_data(self):
        from monitor_pantelimon import contracte_unice, valoare_totala
        r = S.normalizeaza_contracte_can(ANUNT_SCOLI, [CONTRACT_ASOCIERE])
        d = S.normalizeaza_da(da(1, "DA1", "2025-01-16", 100.0, "1 X"))
        vechi = {"id": "achizitie-directa-2025-9", "valoare_ron": 5.0}
        fara_id = [{"valoare_ron": 1.0}, {"valoare_ron": 1.0}]
        toate = r + [d, vechi] + fara_id
        assert len(contracte_unice(toate)) == 5
        assert valoare_totala(toate) == pytest.approx(29508940.74 + 100.0 + 5.0 + 2.0)



class TestRobustete:
    def test_paginare_incompleta_e_eroare(self):
        """Serverul spune total=150 dar dă o singură pagină de 100 → nu acceptăm."""
        items = [da(i, f"DA{i}", "2025-01-10", 1.0, "1 X") for i in range(100)]
        def raspunde(url, corp):
            if "GetDirectAcquisitionList" in url:
                if corp["pageIndex"] == 0 and corp["finalizationDateStart"].startswith("2025-01"):
                    return RaspunsFals(json_={"total": 150, "items": items})
                return RaspunsFals(json_={"total": 150 if corp["finalizationDateStart"].startswith("2025-01") else 0,
                                          "items": []})
            return RaspunsFals(json_={"total": 0, "items": []})
        c, _ = client([raspunde] * 40)
        with pytest.raises(S.SeapIndisponibil):
            S.fetch_contracte_seap_api([], azi=date(2026, 1, 10), client=c)

    def test_anunt_fara_data_e_eroare(self):
        anunt = dict(ANUNT_SCOLI)
        anunt.pop("noticeStateDate")
        raspunde = server_simulat({}, [anunt], {})
        c, _ = client([raspunde] * 40)
        with pytest.raises(S.SeapIndisponibil):
            S.fetch_contracte_seap_api([], azi=date(2026, 1, 10), client=c)

    def test_contract_republicat_cu_alt_id_pastreaza_permalinkul(self):
        noi = S.normalizeaza_contracte_can(ANUNT_SCOLI, [dict(CONTRACT_ASOCIERE, caNoticeContractId=555)])
        vechi = [{"id": "contract-2025-58067", "valoare": 29508940.74, "data": "2025-07-29",
                  "cui": "30056330", "k": "can:108000001"}]
        assert S.pastreaza_id_uri(noi, vechi) == 1
        assert noi[0]["id"] == "contract-2025-58067"

    def test_suma_dedupata_pe_an_numara_asocierea_o_data(self):
        from monitor_pantelimon import _suma_seap_dedupata
        r = S.normalizeaza_contracte_can(ANUNT_SCOLI, [CONTRACT_ASOCIERE])
        # două achiziții directe identice în aceeași zi = două contracte
        d1 = S.normalizeaza_da(da(1, "DA1", "2025-05-19", 68000.0, "5 CULT"))
        d2 = S.normalizeaza_da(da(2, "DA2", "2025-05-19", 68000.0, "5 CULT"))
        total, n = _suma_seap_dedupata(r + [d1, d2], 2025)
        assert n == 3 and total == pytest.approx(29508940.74 + 136000.0)
