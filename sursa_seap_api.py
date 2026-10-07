"""Contractele Primăriei Pantelimon direct din API-ul public SEAP (e-licitatie.ro).

Înlocuiește exportul trimestrial de pe data.gov.ro, care blochează runnerele
GitHub Actions și rămâne cu 3-6 luni în urmă. API-ul public SEAP răspunde din CI
dacă cererile au header-ul `Referer`.

Ce aduce:
  * cumpărările directe (DA) acceptate — o cerere pe lună, filtrat după
    data finalizării (filtrul pe data publicării e ignorat de server);
  * contractele din anunțurile de atribuire (CAN / SCNA): contracte, acorduri-cadru
    și contracte subsecvente, cu câștigătorii lor.

Schema rezultată este cea internă a monitorului (aceleași câmpuri ca la
data.gov.ro), plus câteva câmpuri noi: `cod_seap`, `url_seap`, `cheie_seap`,
`tip_contract`, `asociere`.

Ca la data.gov.ro, un contract atribuit unei asocieri apare pe câte un rând
pentru fiecare membru (fiecare cu valoarea întreagă). Rândurile aceluiași
contract au aceeași `cheie_seap`, ca totalurile să poată număra contractul o
singură dată.

SEAP blochează IP-urile care fac mult trafic automat. De aceea:
  * cel puțin `PAUZA_SECUNDE` între cereri (implicit 2 s);
  * plafon de cereri pe rulare (`MAX_CERERI`);
  * dacă serverul refuză (403/429 sau pagina „Acces restricționat”), ne oprim
    imediat (`SeapBlocat`) — monitorul trece pe contracte.json din rularea
    anterioară, cu avertisment. Nu publicăm niciodată date parțiale.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import requests

SEAP_BASE = "https://e-licitatie.ro"
ID_PRIMARIA_PANTELIMON = 842          # contractingAuthorityId în SEAP (CUI 4420759)
PAUZA_SECUNDE = 2.0
MAX_CERERI = 250
STARE_OFERTA_ACCEPTATA = 7            # sysDirectAcquisitionState.id
TIPURI_ANUNT_ATRIBUIRE = [3, 13, 18, 19]  # CAN, SCNA și variantele lor

TIP_CONTRACT = {1: "contract", 2: "acord-cadru", 3: "subsecvent"}

URL_DA = SEAP_BASE + "/pub/direct-acquisition/view/{id}"
URL_CAN = SEAP_BASE + "/pub/notices/ca-notices/view-c/{id}"


class SeapBlocat(RuntimeError):
    """Serverul SEAP a refuzat cererile (limitare de trafic / IP blocat)."""


class SeapIndisponibil(RuntimeError):
    """O cerere a eșuat de mai multe ori (rețea, 5xx, răspuns invalid)."""


# ──────────────────────────────────────────────────────────────────────────────
# Client HTTP prudent
# ──────────────────────────────────────────────────────────────────────────────

class ClientSeap:
    """Sesiune HTTP cu pauză între cereri, plafon și oprire la blocare."""

    def __init__(self, pauza: float = PAUZA_SECUNDE, max_cereri: int = MAX_CERERI,
                 sesiune: requests.Session | None = None, dormi=time.sleep):
        self.pauza = pauza
        self.max_cereri = max_cereri
        self.cereri = 0
        self._ultima = 0.0
        self._dormi = dormi
        self.s = sesiune or requests.Session()
        self.s.headers.update({
            "Origin": SEAP_BASE,
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": ("Mozilla/5.0 (monitor civic transparenta-pantelimon.eu; "
                           "o cerere la 2 secunde)"),
        })

    def _asteapta(self):
        if self._ultima:
            ramas = self.pauza - (time.monotonic() - self._ultima)
            if ramas > 0:
                self._dormi(ramas)
        self._ultima = time.monotonic()

    def cerere(self, metoda: str, cale: str, referer: str, corp: dict | None = None,
               incercari: int = 3, timeout=(20, 60)):
        if self.cereri >= self.max_cereri:
            raise SeapIndisponibil(f"plafon de {self.max_cereri} cereri atins")
        ultima_eroare = None
        for incercare in range(incercari):
            self._asteapta()
            self.cereri += 1
            try:
                r = self.s.request(metoda, SEAP_BASE + cale, json=corp, timeout=timeout,
                                   headers={"Referer": SEAP_BASE + referer})
            except requests.exceptions.RequestException as e:
                ultima_eroare = f"{type(e).__name__}: {e}"
                self._dormi(10 * (incercare + 1))
                continue
            text_inceput = (r.text or "")[:2000].lower()
            if r.status_code in (403, 429) or "restric" in text_inceput and "<html" in text_inceput:
                raise SeapBlocat(f"HTTP {r.status_code} la {cale}")
            if r.status_code >= 500:
                ultima_eroare = f"HTTP {r.status_code}"
                self._dormi(10 * (incercare + 1))
                continue
            if r.status_code != 200:
                raise SeapIndisponibil(f"HTTP {r.status_code} la {cale}")
            try:
                return r.json()
            except ValueError:
                ultima_eroare = "răspuns care nu e JSON"
                self._dormi(10 * (incercare + 1))
        raise SeapIndisponibil(f"{cale}: {ultima_eroare}")


# ──────────────────────────────────────────────────────────────────────────────
# Funcții pure (testate fără rețea)
# ──────────────────────────────────────────────────────────────────────────────

def ferestre_lunare(start: date, sfarsit: date) -> list:
    """[(început_lună, început_luna_următoare), …] care acoperă [start, sfarsit]."""
    out = []
    d = date(start.year, start.month, 1)
    while d <= sfarsit:
        urm = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append((d, urm))
        d = urm
    return out


def _iso_z(d: date) -> str:
    return d.isoformat() + "T00:00:00.000Z"


def cifre_cui(text) -> str:
    """'RO 14399840' / 'ro27019056' / '35253022 KSA ROAD' → cifrele CUI-ului."""
    m = re.match(r"\s*(?:RO)?\s*(\d{2,10})", str(text or ""), re.I)
    return m.group(1) if m else ""


def separa_furnizor(text: str) -> tuple:
    """'35253022 KSA ROAD SERVICES' → ('35253022', 'KSA ROAD SERVICES')."""
    m = re.match(r"\s*(?:RO)?\s*(\d{2,10})\s+(.*\S)\s*$", str(text or ""), re.I)
    if m:
        return m.group(1), m.group(2)
    return "", str(text or "").strip()


def denumire_cpv(cpv: str) -> str:
    """'22212100-0 - Publicatii periodice (Rev.2)' → 'Publicatii periodice (Rev.2)'."""
    t = str(cpv or "").strip()
    m = re.match(r"^\d{8}-\d\s*-\s*(.+)$", t)
    return m.group(1).strip() if m else (t or "Nespecificat")


def _zi(iso: str) -> str:
    return str(iso or "")[:10]


def _nr_ofertanti(tip_procedura: str) -> int:
    # Ca la data.gov.ro: exportul nu are numărul de oferte; îl deducem din procedură.
    t = (tip_procedura or "").lower()
    return 2 if any(k in t for k in ("deschis", "restrâns", "restrans", "competitiv")) else 1


def normalizeaza_da(item: dict) -> dict | None:
    """Un rând din GetDirectAcquisitionList → schema internă (None dacă nu e acceptată)."""
    stare = (item.get("sysDirectAcquisitionState") or {}).get("id")
    if stare != STARE_OFERTA_ACCEPTATA:
        return None
    da_id = item.get("directAcquisitionId")
    cui, nume = separa_furnizor(item.get("supplier", ""))
    valoare = item.get("closingValue")
    if valoare is None:
        valoare = item.get("estimatedValueRon") or 0
    data_pub = _zi(item.get("publicationDate"))
    return {
        "id": f"achizitie-directa-{data_pub[:4] or '0000'}-{da_id}",
        "numar": item.get("uniqueIdentificationCode") or str(da_id),
        "titlu": denumire_cpv(item.get("cpvCode")),
        "denumire": (item.get("directAcquisitionName") or "").strip(),
        "valoare_ron": float(valoare or 0),
        "moneda": "RON",
        "tip_procedura": "",
        "data_publicare": data_pub,
        "data_finalizare": _zi(item.get("finalizationDate")),
        "castigator": nume or "Necunoscut",
        "castigator_cui": cui,
        "nr_ofertanti": 1,
        "sursa": "SEAP API/cumparare directa",
        "tip_contract": "achizitie-directa",
        "cod_seap": item.get("uniqueIdentificationCode") or "",
        "url_seap": URL_DA.format(id=da_id),
        "cheie_seap": f"da:{da_id}",
        "asociere": [],
    }


def normalizeaza_contracte_can(anunt: dict, contracte: list) -> list:
    """Un anunț de atribuire + contractele lui → rânduri în schema internă.

    Un rând pentru fiecare câștigător (ca la data.gov.ro); rândurile aceluiași
    contract au aceeași `cheie_seap`.
    """
    tip_proc = ((anunt.get("sysProcedureType") or {}).get("text") or "").strip()
    titlu = denumire_cpv(anunt.get("cpvCodeAndName"))
    can_id = anunt.get("caNoticeId")
    nr_anunt = anunt.get("noticeNo") or ""
    out = []
    for c in contracte or []:
        cid = c.get("caNoticeContractId")
        castigatori = c.get("winners") or ([c["winner"]] if c.get("winner") else [])
        if not castigatori:
            castigatori = [{"name": c.get("winnerCaption") or "Necunoscut", "fiscalNumber": ""}]
        valoare = c.get("defaultCurrencyContractValue")
        if valoare is None:
            valoare = c.get("contractValue") or 0
        data_c = _zi(c.get("contractDate"))
        nume_toti = [(w.get("name") or "").strip() for w in castigatori]
        for i, w in enumerate(castigatori):
            out.append({
                "id": f"contract-{data_c[:4] or '0000'}-{int(cid) * 10 + i if cid else 0}",
                "numar": (c.get("contractNo") or "").strip() or nr_anunt,
                "titlu": titlu,
                "denumire": (c.get("contractTitle") or anunt.get("contractTitle") or "").strip(),
                "valoare_ron": float(valoare or 0),
                "moneda": "RON",
                "tip_procedura": tip_proc,
                "data_publicare": data_c,
                "castigator": (w.get("name") or "").strip() or "Necunoscut",
                "castigator_cui": cifre_cui(w.get("fiscalNumber")),
                "nr_ofertanti": _nr_ofertanti(tip_proc),
                "sursa": "SEAP API/anunt de atribuire",
                "tip_contract": TIP_CONTRACT.get(c.get("contractType"), "contract"),
                "cod_seap": nr_anunt,
                "url_seap": URL_CAN.format(id=can_id),
                "cheie_seap": f"can:{cid}",
                "asociere": [n for j, n in enumerate(nume_toti) if j != i and n],
            })
    return out


def deduplica(randuri: list) -> list:
    """Scoate rândurile repetate (aceeași DA, sau același contract în două anunțuri)."""
    vazute, out = set(), []
    for r in randuri:
        if r["cheie_seap"].startswith("da:"):
            k = (r["cheie_seap"],)
        else:
            k = (r["castigator_cui"] or r["castigator"].lower(), r["data_publicare"],
                 round(r["valoare_ron"], 2), r["numar"], r["tip_contract"])
        if k in vazute:
            continue
        vazute.add(k)
        out.append(r)
    return out


def _cui_vechi(c: dict) -> str:
    return cifre_cui(c.get("castigator_cui", c.get("cui", "")))


def _val(c: dict) -> float:
    try:
        return float(c.get("valoare_ron", c.get("valoare", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _data(c: dict) -> str:
    return str(c.get("data_publicare", c.get("data", "")) or "")[:10]


def _zile_intre(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 9999


def pastreaza_id_uri(noi: list, anterioare: list) -> int:
    """Refolosește id-urile din contracte.json pentru aceleași contracte.

    Paginile de semnal (semnale/<slug>.html) au slug-ul construit din id-urile
    contractelor; dacă id-urile s-ar schimba, linkurile deja distribuite ar
    ajunge la pagini „semnal retras”. Potrivirea:
      1. după `cheie_seap` (rulări anterioare făcute deja din API);
      2. altfel, pentru rândurile vechi din data.gov.ro: același CUI și aceeași
         categorie, valoare apropiată, data cea mai apropiată (max. 3 zile la
         DA; la contracte aceeași dată, valoare în ±5% — SEAP actualizează
         valoarea după modificări).
    Returnează câte id-uri au fost păstrate.
    """
    ramase = list(anterioare or [])
    dupa_cheie = {}
    for c in ramase:
        k = c.get("cheie_seap") or c.get("k")
        if k:
            dupa_cheie.setdefault((k, cifre_cui(c.get("castigator_cui", c.get("cui", "")))), c)
    folosite = set()
    potrivite = set()
    pastrate = 0
    for i, r in enumerate(noi):
        k = (r["cheie_seap"], r["castigator_cui"])
        if k in dupa_cheie and id(dupa_cheie[k]) not in folosite:
            vechi = dupa_cheie[k]
            folosite.add(id(vechi))
            potrivite.add(i)
            r["id"] = vechi["id"]
            pastrate += 1
    for i, r in enumerate(noi):
        if i in potrivite:
            continue
        este_da = r["tip_contract"] == "achizitie-directa"
        candidati = []
        for c in ramase:
            if id(c) in folosite or (c.get("cheie_seap") or c.get("k")):
                continue
            if str(c.get("id", "")).startswith("achizitie-directa") != este_da:
                continue
            if _cui_vechi(c) != r["castigator_cui"] or not r["castigator_cui"]:
                continue
            zile = _zile_intre(_data(c), r["data_publicare"])
            v_vechi, v_nou = _val(c), r["valoare_ron"]
            if este_da:
                if abs(v_vechi - v_nou) > 1.0 or zile > 3:
                    continue
            else:
                if zile > 0 or abs(v_vechi - v_nou) > 0.05 * max(v_vechi, v_nou, 1):
                    continue
            candidati.append((zile, abs(v_vechi - v_nou), c))
        if candidati:
            candidati.sort(key=lambda t: (t[0], t[1]))
            vechi = candidati[0][2]
            folosite.add(id(vechi))
            r["id"] = vechi["id"]
            pastrate += 1
    # id-uri unice (un id vechi nu poate fi luat de două rânduri; cele noi sunt deja unice)
    vazute = set()
    for r in noi:
        if r["id"] in vazute:
            r["id"] = r["id"] + "-b"
        vazute.add(r["id"])
    return pastrate


def pastreaza_nume_firme(noi: list, anterioare: list) -> int:
    """Pentru un CUI deja cunoscut, folosește numele firmei din contracte.json.

    SEAP afișează numele actual al firmei (ex. „FANPLACE IT”), exportul vechi
    numele de la data contractului („FANPLACE iT SRL”). Paginile de furnizor și
    unele sluguri de semnal se construiesc din nume, deci păstrăm numele deja
    publicat (cel mai frecvent pentru acel CUI). Firmele noi primesc numele din SEAP.
    Returnează câte rânduri au primit numele vechi.
    """
    from collections import Counter
    nume = {}
    for c in anterioare or []:
        cui = _cui_vechi(c)
        n = (c.get("castigator") or c.get("firma") or "").strip()
        if cui and n:
            nume.setdefault(cui, Counter())[n] += 1
    schimbate = 0
    for r in noi:
        cnt = nume.get(r["castigator_cui"])
        if cnt:
            ales = cnt.most_common(1)[0][0]
            if ales != r["castigator"]:
                r["castigator"] = ales
                schimbate += 1
    return schimbate


# ──────────────────────────────────────────────────────────────────────────────
# Descărcare
# ──────────────────────────────────────────────────────────────────────────────

def descarca_da(client: ClientSeap, id_autoritate: int, start: date, sfarsit: date,
                jurnal: list) -> list:
    """Toate cumpărările directe finalizate în [start, sfarsit], lună cu lună."""
    brute, vazute = [], set()
    for inceput, urmator in ferestre_lunare(start, sfarsit):
        pagina = 0
        while True:
            corp = {
                "pageSize": 100, "pageIndex": pagina, "showOngoingDa": False,
                "cookieContext": None, "sysDirectAcquisitionStateId": None,
                "contractingAuthorityId": id_autoritate,
                "finalizationDateStart": _iso_z(inceput),
                "finalizationDateEnd": _iso_z(urmator),
                "publicationDateStart": None, "publicationDateEnd": None,
            }
            j = client.cerere("POST", "/api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList/",
                              "/pub/direct-acquisitions/list/1", corp)
            if not isinstance(j, dict) or "items" not in j:
                raise SeapIndisponibil(f"DA {inceput:%Y-%m}: răspuns fără listă")
            if j.get("searchTooLong"):
                raise SeapIndisponibil(f"DA {inceput:%Y-%m}: căutare prea lungă")
            for it in j["items"]:
                k = it.get("directAcquisitionId")
                if k not in vazute:
                    vazute.add(k)
                    brute.append(it)
            total = int(j.get("total") or 0)
            if (pagina + 1) * 100 >= total:
                break
            pagina += 1
        jurnal.append(f"DA {inceput:%Y-%m}: total={total}")
    return brute


def descarca_atribuiri(client: ClientSeap, id_autoritate: int, start: date,
                       jurnal: list) -> list:
    """[(anunț, [contracte])] pentru anunțurile de atribuire publicate din `start`."""
    anunturi, pagina = [], 0
    while True:
        j = client.cerere("POST", "/api-pub/NoticeCommon/GetCANoticeList/",
                          "/pub/notices/ca-notices/list/1",
                          {"sysNoticeTypeIds": TIPURI_ANUNT_ATRIBUIRE, "sortProperties": [],
                           "pageSize": 100, "pageIndex": pagina,
                           "contractingAuthorityId": id_autoritate,
                           "hasUnansweredQuestions": False})
        if not isinstance(j, dict) or "items" not in j:
            raise SeapIndisponibil("lista anunțurilor de atribuire: răspuns fără listă")
        anunturi += j["items"]
        if (pagina + 1) * 100 >= int(j.get("total") or 0):
            break
        pagina += 1
    alese = [a for a in anunturi if _zi(a.get("noticeStateDate")) >= start.isoformat()]
    jurnal.append(f"Anunturi de atribuire: {len(anunturi)} in total, {len(alese)} din {start}")
    rezultat = []
    for a in alese:
        contracte, skip = [], 0
        while True:
            corp = {"caNoticeId": a["caNoticeId"], "contractNo": None, "winnerTitle": None,
                    "winnerFiscalNumber": None, "contractDate": {"from": None, "to": None},
                    "contractValue": {"from": None, "to": None},
                    "contractMinOffer": {"from": None, "to": None},
                    "contractMaxOffer": {"from": None, "to": None}, "contractTitle": None,
                    "lots": None, "sortOrder": [], "sysContractFrameworkType": {},
                    "skip": skip, "take": 100}
            j = client.cerere("POST", "/api-pub/C_PUBLIC_CANotice/GetCANoticeContracts",
                              f"/pub/notices/ca-notices/view-c/{a['caNoticeId']}", corp)
            if not isinstance(j, dict) or "items" not in j:
                raise SeapIndisponibil(f"{a.get('noticeNo')}: răspuns fără contracte")
            contracte += j["items"]
            if skip + 100 >= int(j.get("total") or 0):
                break
            skip += 100
        jurnal.append(f"{a.get('noticeNo')}: {len(contracte)} contracte")
        rezultat.append((a, contracte))
    return rezultat


def fetch_contracte_seap_api(contracte_anterioare: list | None = None,
                             id_autoritate: int = ID_PRIMARIA_PANTELIMON,
                             azi: date | None = None,
                             client: ClientSeap | None = None) -> tuple:
    """(contracte, jurnal) — de la 1 ianuarie anul trecut până azi.

    Ridică SeapBlocat / SeapIndisponibil dacă nu se poate aduce TOT; apelantul
    decide fallback-ul (nu returnăm niciodată o listă parțială).
    """
    azi = azi or date.today()
    start = date(azi.year - 1, 1, 1)
    client = client or ClientSeap()
    jurnal = [f"SEAP API: autoritate={id_autoritate} interval {start}..{azi}"]
    t0 = time.monotonic()

    da = [normalizeaza_da(x) for x in descarca_da(client, id_autoritate, start, azi, jurnal)]
    da = [x for x in da if x and x["data_publicare"] >= start.isoformat()]
    contracte = []
    for anunt, lista in descarca_atribuiri(client, id_autoritate, start, jurnal):
        contracte += normalizeaza_contracte_can(anunt, lista)

    toate = deduplica(da + contracte)
    toate.sort(key=lambda c: (c["data_publicare"], c["id"]))
    pastrate = pastreaza_id_uri(toate, contracte_anterioare or [])
    nume = pastreaza_nume_firme(toate, contracte_anterioare or [])
    jurnal.append(f"SEAP API: {len(da)} DA acceptate, {len(contracte)} randuri din atribuiri, "
                  f"{len(toate)} dupa deduplicare; {pastrate} id-uri pastrate, "
                  f"{nume} nume de firma pastrate; "
                  f"{client.cereri} cereri in {time.monotonic() - t0:.0f}s")
    return toate, jurnal


def verifica_plauzibil(noi: list, anterioare: list) -> str:
    """Mesaj de eroare dacă rezultatul pare incomplet față de rularea anterioară, altfel ''.

    Comparăm doar perioada comună: o scădere mare a numărului de rânduri pe
    aceeași perioadă înseamnă aproape sigur un răspuns trunchiat.
    """
    if not anterioare:
        return "" if noi else "SEAP API nu a întors niciun contract"
    if not noi:
        return "SEAP API nu a întors niciun contract"
    inceput = min(_data(c) for c in noi if _data(c)) if any(_data(c) for c in noi) else ""
    sfarsit = max(_data(c) for c in anterioare if _data(c)) if any(_data(c) for c in anterioare) else ""
    vechi = [c for c in anterioare if inceput <= _data(c) <= sfarsit]
    nou = [c for c in noi if inceput <= _data(c) <= sfarsit]
    if len(vechi) >= 50 and len(nou) < 0.8 * len(vechi):
        return (f"SEAP API pare incomplet: {len(nou)} rânduri în {inceput}..{sfarsit}, "
                f"față de {len(vechi)} în rularea anterioară")
    return ""
