"""Teste pentru căutarea după nume de firmă și pentru profilul de firmă.

Context (bug raportat 04.08.2026): căutarea „DAV GARDEN&SERVICE SRL" returna
zero rezultate, deși firma exista în date sub forma „DAV  GARDEN & SERVICE"
(două spații, fără sufix juridic). Cauza: potrivire de subșir brută, fără
normalizare, atât în `enhance.js` cât și în profilul de firmă.

Testele de mai jos blochează regresia pe ambele fronturi:
  1. normalizarea de nume din `monitor_pantelimon.py`
  2. conținutul template-ului JS generat (profil firmă)
  3. sincronizarea `enhance.js` ↔ `enhance.min.js`
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor_pantelimon import (  # noqa: E402
    SUFIXE_JURIDICE,
    _cui_pentru_furnizor,
    construieste_index_cui,
    normalizeaza_nume_firma,
    nume_firma_esential,
)

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')


class TestNormalizareNumeFirma(unittest.TestCase):
    """`normalizeaza_nume_firma` — forma canonică a unui nume de firmă."""

    def test_colapseaza_spatii_multiple(self):
        self.assertEqual(
            normalizeaza_nume_firma("DAV  GARDEN & SERVICE"),
            "dav garden and service",
        )

    def test_ampersand_fara_spatii_egal_cu_ampersand_cu_spatii(self):
        self.assertEqual(
            normalizeaza_nume_firma("DAV GARDEN&SERVICE"),
            normalizeaza_nume_firma("DAV  GARDEN & SERVICE"),
        )

    def test_abrevieri_punctate(self):
        self.assertEqual(normalizeaza_nume_firma("PERCONS EU S.R.L."), "percons eu srl")
        self.assertEqual(normalizeaza_nume_firma("DEDEMAN S.R.L."), "dedeman srl")

    def test_diacritice_eliminate(self):
        self.assertEqual(
            normalizeaza_nume_firma("Construcţii Şi Ţevi"), "constructii si tevi"
        )
        # ambele variante de ș/ț (cedilă U+015F și virgulă U+0219) dau același rezultat
        self.assertEqual(
            normalizeaza_nume_firma("ŞTEFAN"), normalizeaza_nume_firma("ȘTEFAN")
        )

    def test_input_gol_sau_none(self):
        self.assertEqual(normalizeaza_nume_firma(""), "")
        self.assertEqual(normalizeaza_nume_firma(None), "")

    def test_idempotenta(self):
        o = normalizeaza_nume_firma("SC  Oltenia Garden S.R.L.")
        self.assertEqual(normalizeaza_nume_firma(o), o)


class TestNumeFirmaEsential(unittest.TestCase):
    """`nume_firma_esential` — numele fără sufixe juridice."""

    def test_scoate_srl_indiferent_de_scriere(self):
        for varianta in ("DAV GARDEN&SERVICE SRL", "DAV  GARDEN & SERVICE S.R.L.",
                         "DAV GARDEN & SERVICE"):
            self.assertEqual(
                nume_firma_esential(varianta), "dav garden and service", varianta
            )

    def test_scoate_prefixul_sc(self):
        self.assertEqual(nume_firma_esential("SC OLTENIA GARDEN SRL"), "oltenia garden")

    def test_pastreaza_cuvintele_reale(self):
        self.assertEqual(
            nume_firma_esential("GEROM INTERNATIONAL PRODIMEX S.R.L."),
            "gerom international prodimex",
        )

    def test_sufixele_sunt_lowercase_fara_punctuatie(self):
        for s in SUFIXE_JURIDICE:
            self.assertEqual(s, s.lower())
            self.assertNotIn(".", s)


class TestRegresieBugDavGarden(unittest.TestCase):
    """Regresia exactă raportată: interogarea utilizatorului vs. forma din date."""

    NUME_IN_DATE = "DAV  GARDEN & SERVICE"      # exact așa apare în export SEAP
    INTEROGARE = "DAV GARDEN&SERVICE SRL"       # exact așa a căutat utilizatorul

    def test_interogarea_utilizatorului_se_potriveste_cu_datele(self):
        self.assertEqual(
            nume_firma_esential(self.INTEROGARE),
            nume_firma_esential(self.NUME_IN_DATE),
        )

    def test_potrivire_partiala_pe_tokenuri(self):
        hay = nume_firma_esential(self.NUME_IN_DATE)
        for token in nume_firma_esential("dav garden").split():
            self.assertIn(token, hay)

    def test_ordinea_cuvintelor_nu_conteaza_la_potrivirea_pe_tokenuri(self):
        hay = nume_firma_esential(self.NUME_IN_DATE)
        self.assertTrue(all(t in hay for t in nume_firma_esential("garden dav").split()))


class TestProfilFirmaTemplate(unittest.TestCase):
    """Profilul de firmă din raportul generat (funcția `openFirmaPanel`)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, 'monitor_pantelimon.py'), encoding='utf-8') as f:
            cls.sursa = f.read()

    def test_flagurile_din_profil_au_descriere_si_ancora(self):
        """Fără acestea, profilul afișa acuzații fără nicio justificare."""
        self.assertIn('"descriere": _f.get("descriere", "")', self.sursa)
        self.assertIn('"anchor": f"nereguli-{_i}"', self.sursa)

    def test_profilul_randeaza_descrierea(self):
        self.assertIn('f.descriere', self.sursa)

    def test_neregulile_din_profil_sunt_linkuri_catre_ancora(self):
        self.assertIn("'<a href=\"#'+anchor+'\"", self.sursa)

    def test_nu_mai_exista_linkul_seap_generic(self):
        """`/list/0/0` deschidea o pagină goală — arăta ca un buton stricat."""
        self.assertNotIn(
            "var seapUrl    = 'https://e-licitatie.ro/pub/notices/da-direct-acquisition/list/0/0'",
            self.sursa,
        )

    def test_valoarea_afisata_e_suma_contractelor_nu_suma_semnalelor(self):
        """`rd.valoare_totala` numără același contract o dată per semnal."""
        self.assertIn('Valoare contracte cu Primăria', self.sursa)
        self.assertNotIn(
            "Valoare totală expusă: <strong>'+fmtV(rd.valoare_totala||0)", self.sursa
        )

    def test_contoarele_se_calculeaza_din_lista_de_flaguri(self):
        self.assertIn('_rd["n_total"]  = len(_sevs)', self.sursa)

    def test_contractele_firmei_sunt_deduplicate(self):
        """Exporturile trimestriale repetă același contract cu id-uri diferite."""
        self.assertIn('var _vazute = {{}};', self.sursa)


class TestEnhanceJsSincronizat(unittest.TestCase):
    """`enhance.min.js` e servit în producție — trebuie regenerat la fiecare fix."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, 'enhance.js'), encoding='utf-8') as f:
            cls.src = f.read()
        with open(os.path.join(REPO_ROOT, 'enhance.min.js'), encoding='utf-8') as f:
            cls.minified = f.read()

    def test_sursa_are_normalizarea(self):
        self.assertIn('function nzText', self.src)
        self.assertIn('function nzCore', self.src)
        self.assertIn('function matchesQuery', self.src)

    def test_sursa_nu_mai_face_potrivire_bruta(self):
        self.assertNotIn('it.haystack.includes(q)', self.src)

    def test_minificatul_contine_aceleasi_functionalitati(self):
        """Markeri care supraviețuiesc minificării (string-uri literale)."""
        for marker in ('data-suggest', 'Ai vrut să spui', 'and '):
            self.assertIn(marker, self.minified, f'lipsește „{marker}" din enhance.min.js')

    def test_minificatul_nu_e_mai_vechi_decat_sursa(self):
        t_src = os.path.getmtime(os.path.join(REPO_ROOT, 'enhance.js'))
        t_min = os.path.getmtime(os.path.join(REPO_ROOT, 'enhance.min.js'))
        self.assertGreaterEqual(
            t_min, t_src - 1,
            'enhance.min.js e mai vechi decât enhance.js — rulează: '
            'npx terser enhance.js --compress --mangle --comments "/^!/" -o enhance.min.js'
        )

    def test_lista_sufixelor_juridice_e_aceeasi_in_js_si_python(self):
        m = re.search(r'const TP_LEGAL_TOKENS = \{(.*?)\};', self.src, re.S)
        self.assertIsNotNone(m, 'nu am găsit TP_LEGAL_TOKENS în enhance.js')
        js_tokens = set(re.findall(r'(\w+):\s*1', m.group(1)))
        self.assertEqual(
            js_tokens, SUFIXE_JURIDICE,
            'sufixele juridice diferă între enhance.js și monitor_pantelimon.py'
        )


if __name__ == '__main__':
    unittest.main()


class TestIndexCui(unittest.TestCase):
    """Exportul SEAP nu pune CUI pe anunțuri — îl recuperăm din contracte."""

    CONTRACTE = [
        {"castigator": "DAV  GARDEN & SERVICE", "castigator_cui": "RO 28167751"},
        {"firma": "Constopograf Expert", "cui": "25145252"},
        {"castigator": "FĂRĂ CUI", "castigator_cui": ""},
    ]

    def setUp(self):
        # fără fișier de geocodare — testul rămâne independent de date externe
        self.index = construieste_index_cui(self.CONTRACTE, cale_geocoded="")

    def test_indexul_e_pe_nume_normalizat(self):
        self.assertEqual(self.index[normalizeaza_nume_firma("DAV GARDEN&SERVICE")], "RO 28167751")

    def test_accepta_ambele_scheme_de_campuri(self):
        """Schema internă (castigator/castigator_cui) și cea de export (firma/cui)."""
        self.assertIn(normalizeaza_nume_firma("Constopograf Expert"), self.index)

    def test_firmele_fara_cui_nu_intra_in_index(self):
        self.assertNotIn(normalizeaza_nume_firma("FĂRĂ CUI"), self.index)

    def test_cuiul_propriu_al_flagului_are_prioritate(self):
        self.assertEqual(_cui_pentru_furnizor("DAV  GARDEN & SERVICE", "RO 111", self.index), "RO 111")

    def test_cade_pe_index_cand_flagul_nu_are_cui(self):
        self.assertEqual(_cui_pentru_furnizor("dav garden&service srl", "", self.index), "RO 28167751")

    def test_furnizor_necunoscut_returneaza_gol(self):
        self.assertEqual(_cui_pentru_furnizor("Firma Inexistenta", "", self.index), "")

    def test_toate_caile_care_scriu_raport_json_pun_cui(self):
        """Sunt trei locuri care serializeaza flagurile — toate trebuie sa aiba CUI."""
        with open(os.path.join(REPO_ROOT, 'monitor_pantelimon.py'), encoding='utf-8') as f:
            sursa = f.read()
        serializari = sursa.count('"explanation": fl.get("descriere"') + sursa.count('"explanation": flag.get("descriere"')
        cu_cui = sursa.count('"supplier_cif": _cui_pentru') + sursa.count('"supplier_cif": _cui_pentru_furnizor')
        self.assertGreaterEqual(cu_cui, serializari,
                                f'{serializari} serializari de flaguri, dar doar {cu_cui} pun CUI')

    def test_index_gol_nu_arunca(self):
        self.assertEqual(_cui_pentru_furnizor("Orice", "", {}), "")
        self.assertEqual(construieste_index_cui([], cale_geocoded=""), {})


class TestPlafonListaSemnale(unittest.TestCase):
    """Badge-urile numără toate semnalele; lista din panou e plafonată."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, 'monitor_pantelimon.py'), encoding='utf-8') as f:
            cls.sursa = f.read()

    def test_totalul_real_e_expus_langa_lista_plafonata(self):
        """Fără `n_total`, «29 semnale» lângă o listă de 20 pare o contradicție."""
        self.assertIn('"n_total": len(rd["flags"])', self.sursa)

    def test_panoul_anunta_semnalele_care_nu_incap(self):
        self.assertIn('_nAscunse', self.sursa)
        self.assertIn('nu încap în panou', self.sursa)

    def test_exista_scapare_catre_lista_completa(self):
        self.assertIn('function _filtreazaFurnizor', self.sursa)

    def test_plafonul_acopera_cea_mai_incarcata_firma(self):
        m = re.search(r'"flags": rd\["flags"\]\[:(\d+)\]', self.sursa)
        self.assertIsNotNone(m, 'nu am găsit plafonul listei de flaguri')
        self.assertGreaterEqual(int(m.group(1)), 30, 'plafonul e sub maximul real (29 semnale/firmă)')


class TestTitluFaraRevizie(unittest.TestCase):
    """Titlul canonic al unui contract, fără sufixul de revizie."""

    def test_elimina_orice_numar_de_revizie(self):
        from monitor_pantelimon import _titlu_fara_revizie
        for varianta in ("Amenajare spatii verzi (Rev.2)", "Amenajare spatii verzi (Rev.12)",
                         "Amenajare spatii verzi (rev. 3)", "Amenajare spatii verzi ( Rev.4 )"):
            self.assertEqual(_titlu_fara_revizie(varianta), "Amenajare spatii verzi", varianta)

    def test_titlu_fara_revizie_ramane_neschimbat(self):
        from monitor_pantelimon import _titlu_fara_revizie
        self.assertEqual(_titlu_fara_revizie("Reparatii drum"), "Reparatii drum")

    def test_input_gol(self):
        from monitor_pantelimon import _titlu_fara_revizie
        self.assertEqual(_titlu_fara_revizie(None), "")


class TestCrestereBruscaCronologica(unittest.TestCase):
    """Algoritm 7 — «creștere bruscă» trebuie să însemne creștere ÎN TIMP.

    Varianta veche sorta versiunile după valoare și raporta mereu min→max,
    deci anunța „+300%" și când valoarea SCĂZUSE. Pe DAV GARDEN & SERVICE
    afirma public o creștere de la 1.15 mil. la 4.62 mil., când în realitate
    contractul mersese 4.62 mil. (11.12.2025) → 1.15 mil. (27.02.2026).
    """

    @staticmethod
    def _contract(cid, titlu, valoare, data, firma="TEST SRL", numar=None):
        # versiunile aceluiași contract au același număr de contract/anunț
        return {"id": cid, "numar": numar or cid, "titlu": titlu, "valoare_ron": valoare,
                "data_publicare": data, "tip_procedura": "Licitatie deschisa",
                "castigator": firma, "castigator_cui": "RO 1", "nr_ofertanti": 2}

    def _cresteri(self, contracte):
        # funcție pură, fără rețea — de aceea a fost extrasă din analizeaza_red_flags
        from monitor_pantelimon import detect_crestere_brusca_valoare
        return detect_crestere_brusca_valoare(contracte)

    def test_scaderea_in_timp_nu_e_crestere(self):
        """Regresia exactă raportată de utilizator (DAV GARDEN & SERVICE)."""
        contracte = [
            self._contract("c1", "Amenajare spatii verzi (Rev.2)", 4_615_582, "2025-12-11"),
            self._contract("c2", "Amenajare spatii verzi (Rev.2)", 1_153_895, "2026-02-27"),
        ]
        self.assertEqual(self._cresteri(contracte), [])

    def test_cresterea_in_timp_e_detectata(self):
        contracte = [
            self._contract("c1", "Reparatii drum", 1_000_000, "2025-01-10", numar="CTR-7"),
            self._contract("c2", "Reparatii drum (Rev.2)", 4_000_000, "2025-06-10", numar="CTR-7"),
        ]
        flags = self._cresteri(contracte)
        self.assertEqual(len(flags), 1)
        self.assertIn("300%", flags[0]["descriere"])

    def test_descrierea_contine_ambele_date(self):
        """Cititorul trebuie să poată verifica singur ordinea cronologică."""
        contracte = [
            self._contract("c1", "Reparatii drum", 1_000_000, "2025-01-10", numar="CTR-7"),
            self._contract("c2", "Reparatii drum (Rev.2)", 4_000_000, "2025-06-10", numar="CTR-7"),
        ]
        descriere = self._cresteri(contracte)[0]["descriere"]
        self.assertIn("2025-01-10", descriere)
        self.assertIn("2025-06-10", descriere)

    def test_copiile_din_exporturi_diferite_nu_se_compara_intre_ele(self):
        """Același contract, republicat trimestrial cu alt id, nu e o revizie."""
        contracte = [
            self._contract("contract-2025-113859", "Amenajare (Rev.2)", 4_615_582, "2025-12-11"),
            self._contract("contract-2026-168284", "Amenajare (Rev.2)", 4_615_582, "2025-12-11"),
        ]
        self.assertEqual(self._cresteri(contracte), [])

    def test_firme_diferite_cu_acelasi_obiect_nu_se_compara(self):
        contracte = [
            self._contract("a", "Servicii curatenie", 100_000, "2025-01-01", firma="ALFA SRL"),
            self._contract("b", "Servicii curatenie", 900_000, "2025-05-01", firma="BETA SRL"),
        ]
        self.assertEqual(self._cresteri(contracte), [])

    def test_flagul_indica_versiunea_finala(self):
        contracte = [
            self._contract("vechi", "Lucrari X", 200_000, "2025-01-01", numar="CTR-9"),
            self._contract("nou", "Lucrari X (Rev.12)", 800_000, "2025-09-01", numar="CTR-9"),
        ]
        flag = self._cresteri(contracte)[0]
        self.assertEqual(flag["contract_id"], "nou")
        self.assertEqual(flag["data"], "2025-09-01")
        self.assertEqual(flag["valoare"], 800_000)


    def test_input_gol_sau_o_singura_versiune(self):
        self.assertEqual(self._cresteri([]), [])
        self.assertEqual(self._cresteri(None), [])
        self.assertEqual(self._cresteri([self._contract("x", "Unic", 9_000_000, "2025-01-01")]), [])

    def test_cresterile_mici_nu_sunt_semnalate(self):
        """Prag: +50% și valoare finală peste 50.000 RON."""
        contracte = [
            self._contract("c1", "Servicii", 1_000_000, "2025-01-01"),
            self._contract("c2", "Servicii (Rev.2)", 1_200_000, "2025-06-01"),
        ]
        self.assertEqual(self._cresteri(contracte), [])

    def test_aceeasi_data_nu_afirma_o_directie(self):
        """Fara ordine cronologica nu avem dreptul sa spunem ca „a crescut"."""
        contracte = [
            self._contract("a", "Utilaje", 1_460_000, "2025-02-24"),
            self._contract("b", "Utilaje (Rev.2)", 2_910_000, "2025-02-24"),
        ]
        flag = self._cresteri(contracte)[0]
        self.assertNotIn("a crescut", flag["descriere"])
        self.assertIn("aceeași dată", flag["descriere"])
        self.assertIn("Nu se poate stabili", flag["descriere"])
        self.assertEqual(flag["severitate"], "MEDIU")

    def test_achizitii_separate_cu_acelasi_cpv_nu_sunt_versiuni(self):
        """Regresia GEMCO TRADE: „(Rev.2)" e revizia CPV, nu a contractului.

        Două achiziții directe distincte (piatră, 01.2025 și 03.2026) erau
        raportate ca „creștere de 95% între versiuni".
        """
        contracte = [
            self._contract("achizitie-directa-2025-80581", "Piatra de cariera si concasata (Rev.2)",
                           137_750, "2025-01-22", firma="GEMCO TRADE"),
            self._contract("achizitie-directa-2026-299822", "Piatra de cariera si concasata (Rev.2)",
                           268_800, "2026-03-03", firma="GEMCO TRADE"),
        ]
        self.assertEqual(self._cresteri(contracte), [])

    def test_aceeasi_data_pastreaza_semnalul(self):
        """Diferenta ramane un semnal legitim, doar formularea se schimba."""
        contracte = [
            self._contract("a", "Utilaje", 1_460_000, "2025-02-24"),
            self._contract("b", "Utilaje (Rev.2)", 2_910_000, "2025-02-24"),
        ]
        flags = self._cresteri(contracte)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["tip"], "CRESTERE_BRUSCA_VALOARE")

    def test_severitatea_creste_cu_procentul(self):
        mic = [self._contract("a", "X", 1_000_000, "2025-01-01", numar="N1"),
               self._contract("b", "X (Rev.2)", 2_000_000, "2025-06-01", numar="N1")]      # +100%
        mare = [self._contract("c", "Y", 1_000_000, "2025-01-01", numar="N2"),
                self._contract("d", "Y (Rev.2)", 4_000_000, "2025-06-01", numar="N2")]     # +300%
        self.assertEqual(self._cresteri(mic)[0]["severitate"], "MAJOR")
        self.assertEqual(self._cresteri(mare)[0]["severitate"], "CRITIC")


class TestDedupContracteInPanou(unittest.TestCase):
    """Tabelul «Toate contractele cu…» dubla valoarea firmei."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO_ROOT, 'monitor_pantelimon.py'), encoding='utf-8') as f:
            cls.sursa = f.read()

    def test_showFirmaContracts_dedupleaza(self):
        idx = self.sursa.find('function showFirmaContracts')
        self.assertGreater(idx, 0)
        bloc = self.sursa[idx:idx + 2000]
        self.assertIn('_vazuteC', bloc, 'lipsește deduplicarea în showFirmaContracts')

    def test_showFirmaContracts_potriveste_normalizat(self):
        idx = self.sursa.find('function showFirmaContracts')
        bloc = self.sursa[idx:idx + 2000]
        self.assertIn('_nzFirma', bloc)
        self.assertNotIn('firmaLow.indexOf(cl.substring(0, 12))', bloc,
                         'potrivirea veche pe primele 12 caractere a rămas în cod')

