"""
Teste unitare pentru detectori Faza 3:
  - detect_fragmentare_temporara   (§2.1)
  - detect_concentrare_furnizor    (§2.2)
  - detect_sedinte_extraordinare   (§2.6)
  - detect_publicare_intarziata    (§2.7)

Rulare: py -m pytest tests/test_detectors.py -v
Sau:    py tests/test_detectors.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_pantelimon import (
    detect_fragmentare_temporara,
    detect_concentrare_furnizor,
    detect_sedinte_extraordinare,
    detect_publicare_intarziata,
)

# ---------------------------------------------------------------------------
# Config minimal (folosit de §2.1 + §2.2)
# ---------------------------------------------------------------------------
CFG = {"prag_servicii_furnizare": 270_120, "prag_lucrari": 900_400}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(titlu, cui, valoare, data='2025-03-01'):
    """Contract schema interna (valoare_ron / castigator_cui / data_publicare)."""
    return {
        'id': f'test-{titlu[:8]}-{cui}',
        'numar': f'C-{titlu[:4]}',
        'titlu': titlu,
        'valoare_ron': float(valoare),
        'data_publicare': data,
        'castigator': f'FIRMA_{cui}',
        'castigator_cui': cui,
        'tip_procedura': 'Achizitie directa',
        'nr_ofertanti': 1,
    }


def _ce(titlu, cui, valoare, data='2025-03-01'):
    """Contract schema export (valoare / cui / data) — pentru compatibilitate cross-schema."""
    return {
        'id': f'exp-{titlu[:8]}-{cui}',
        'titlu': titlu,
        'valoare': float(valoare),
        'data': data,
        'firma': f'FIRMA_{cui}',
        'cui': cui,
        'tip': 'Achizitie directa',
        'ofertanti': 1,
    }


# ===========================================================================
# §2.1  detect_fragmentare_temporara
# ===========================================================================

def test_frag_detecteaza_3_contracte_sub_prag():
    """3 contracte sub-prag, titluri similare, fereastră 30 zile → CRITIC."""
    contracte = [
        _c('Servicii curatenie strazi', 'CUI1', 100_000, '2025-03-01'),
        _c('Servicii curatenie strazi', 'CUI1', 100_000, '2025-03-15'),
        _c('Servicii curatenie strazi', 'CUI1', 100_000, '2025-03-25'),
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 1, f'Asteptat 1 flag, got {len(flags)}'
    f = flags[0]
    assert f['tip'] == 'FRAGMENTARE_TEMPORARA'
    assert f['severitate'] == 'CRITIC'
    assert f['valoare'] == 300_000.0
    assert f['nr_contracte'] == 3


def test_frag_niciun_flag_sub_suma():
    """2 contracte de lucrări de 40k → sumă sub pragul de 900.400 → fără flag."""
    contracte = [
        _c('Reparatii drum', 'CUI2', 40_000, '2025-04-01'),
        _c('Reparatii drum', 'CUI2', 40_000, '2025-04-15'),
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 0


def test_frag_niciun_flag_interval_mare():
    """Contracte similare dar la 100+ zile distanță → nu intră în fereastra 90 zile."""
    contracte = [
        _c('Iluminat public', 'CUI3', 70_000, '2025-01-01'),
        _c('Iluminat public', 'CUI3', 70_000, '2025-05-01'),  # 120 zile distanță
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 0


def test_frag_un_singur_contract():
    """Un singur contract → nu poate fi fragmentare."""
    contracte = [_c('Contract unic', 'CUI4', 129_000, '2025-06-01')]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 0


def test_frag_titluri_diferite_nu_grupate():
    """Contracte cu titluri complet diferite (prefix diferit) → nu se grupează."""
    contracte = [
        _c('Curatenie strazi iarna', 'CUI5', 70_000, '2025-03-01'),
        _c('Reparatii bransamente electrice', 'CUI5', 70_000, '2025-03-10'),
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 0


def test_frag_schema_export_acceptata():
    """Funcția acceptă și schema export (valoare/cui/data) nu doar schema interna."""
    contracte = [
        _ce('Servicii paza obiective', 'CUI6', 150_000, '2025-02-01'),
        _ce('Servicii paza obiective', 'CUI6', 150_000, '2025-02-20'),
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    assert len(flags) == 1
    assert flags[0]['valoare'] == 300_000.0


def test_frag_rev_ignorate_la_grupare():
    """Rev.2 din titlu e ignorat la grupare — Contract A + Contract A (Rev.2) → acelasi grup."""
    contracte = [
        _c('Salubrizare (Rev.2)', 'CUI7', 140_000, '2025-03-01'),
        _c('Salubrizare', 'CUI7', 140_000, '2025-03-10'),
    ]
    flags = detect_fragmentare_temporara(contracte, CFG)
    # Ambele au titlu_canonic prefix "salubrizare" → grupate → suma 280k > 270.120
    assert len(flags) == 1


# ===========================================================================
# §2.2  detect_concentrare_furnizor
# ===========================================================================

def test_conc_critic_cand_top3_peste_80():
    """Top 3 cu ~95% → CRITIC (C1=850k, C2=100k, C4=100k, C3=50k; total=1.1M, top3=1.05M)."""
    contracte = [
        _c('Contract A', 'C1', 850_000, '2025-01-01'),
        _c('Contract B', 'C2', 100_000, '2025-01-01'),
        _c('Contract C', 'C3',  50_000, '2025-01-01'),
        _c('Contract D', 'C4', 100_000, '2025-01-01'),
    ]
    # total=1_100_000; top3 = C1(850k)+C2(100k)+C4(100k) = 1_050_000 (95.4%) → CRITIC
    flags = detect_concentrare_furnizor(contracte, CFG)
    assert len(flags) == 1, f'Asteptat 1 flag, got {len(flags)}'
    f = flags[0]
    assert f['tip'] == 'CONCENTRARE_FURNIZOR'
    assert f['severitate'] == 'CRITIC'
    assert len(f['top3_furnizori']) == 3
    top3_pct = sum(x['pct'] for x in f['top3_furnizori'])
    assert top3_pct > 80, f'Asteptat pct > 80, got {top3_pct}'


def test_conc_major_cand_top3_intre_60_80():
    """Top 3 cu 70% → MAJOR."""
    contracte = [
        _c('X', 'F1', 350_000),
        _c('X', 'F2', 200_000),
        _c('X', 'F3', 150_000),
        _c('X', 'F4', 100_000),
        _c('X', 'F5', 100_000),
        _c('X', 'F6', 100_000),
    ]
    flags = detect_concentrare_furnizor(contracte, CFG)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'MAJOR'


def test_conc_niciun_flag_cand_sub_60():
    """Distribuție echilibrată (<60% top-3) → niciun flag."""
    contracte = [_c('X', f'F{i}', 100_000) for i in range(6)]
    flags = detect_concentrare_furnizor(contracte, CFG)
    assert len(flags) == 0


def test_conc_niciun_flag_mai_putin_de_3_furnizori():
    """Dacă sunt <3 furnizori unici, nu se calculează concentrare."""
    contracte = [
        _c('X', 'F1', 200_000),
        _c('Y', 'F1', 200_000),
        _c('Z', 'F2', 100_000),
    ]
    flags = detect_concentrare_furnizor(contracte, CFG)
    assert len(flags) == 0


# ===========================================================================
# §2.6  detect_sedinte_extraordinare
# ===========================================================================

def test_extra_major_la_26_procente():
    """26% ședințe extraordinare → MAJOR."""
    stats = {'total_hcl': 50, 'extraordinare': 13, 'pct_extraordinare': 26}
    flags = detect_sedinte_extraordinare(stats)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'MAJOR'
    assert flags[0]['tip'] == 'SEDINTE_EXTRAORDINARE_EXCESIVE'


def test_extra_critic_la_40_procente():
    """40% ședințe extraordinare → CRITIC."""
    stats = {'total_hcl': 30, 'extraordinare': 12, 'pct_extraordinare': 40}
    flags = detect_sedinte_extraordinare(stats)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'CRITIC'


def test_extra_niciun_flag_la_25_procente():
    """Exact 25% → sub prag, niciun flag."""
    stats = {'total_hcl': 40, 'extraordinare': 10, 'pct_extraordinare': 25}
    flags = detect_sedinte_extraordinare(stats)
    assert len(flags) == 0


def test_extra_niciun_flag_total_mic():
    """<3 ședințe totale → insuficient pentru a trage concluzii."""
    stats = {'total_hcl': 2, 'extraordinare': 2, 'pct_extraordinare': 100}
    flags = detect_sedinte_extraordinare(stats)
    assert len(flags) == 0


# ===========================================================================
# §2.7  detect_publicare_intarziata
# ===========================================================================

def _cp(titlu, cui, valoare, data_attr, data_pub):
    """Contract cu data_atribuire pentru teste §2.7."""
    return {
        'id': f'pub-{cui}',
        'numar': f'P-{cui}',
        'titlu': titlu,
        'valoare_ron': float(valoare),
        'data_atribuire': data_attr,
        'data_publicare': data_pub,
        'castigator': f'FIRMA_{cui}',
        'castigator_cui': cui,
        'tip_procedura': 'Achizitie directa',
    }


def test_pub_mediu_la_15_zile():
    """15 zile lucrătoare întârziere (fără sărbători) → MEDIU."""
    contracte = [_cp('Servicii IT', 'CUI10', 50_000, '2025-06-02', '2025-06-23')]
    # 2025-06-02 (luni) → 2025-06-23 (luni) = 3 săptămâni = 15 zile lucrătoare
    flags = detect_publicare_intarziata(contracte, zile_prag=11)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'MEDIU'
    assert flags[0]['zile_lucratoare_intarziere'] >= 12


def test_pub_critic_la_35_zile():
    """35+ zile lucrătoare întârziere → CRITIC."""
    contracte = [_cp('Lucrari', 'CUI11', 100_000, '2025-01-02', '2025-02-24')]
    # ~36-37 zile lucrătoare (depinzând de sărbători)
    flags = detect_publicare_intarziata(contracte, zile_prag=11)
    assert len(flags) == 1, f'Asteptat 1 flag, got {len(flags)}'
    assert flags[0]['severitate'] == 'CRITIC'
    assert flags[0]['zile_lucratoare_intarziere'] > 30


def test_pub_niciun_flag_in_termen():
    """Publicare la 5 zile lucrătoare → în termen legal."""
    contracte = [_cp('Contract OK', 'CUI12', 50_000, '2025-03-03', '2025-03-10')]
    flags = detect_publicare_intarziata(contracte, zile_prag=11)
    assert len(flags) == 0


def test_pub_niciun_flag_fara_data_atribuire():
    """Contracte fără data_atribuire sunt ignorate (graceful no-op)."""
    contracte = [{'id': 'x', 'titlu': 'X', 'valoare_ron': 50_000,
                  'data_publicare': '2025-05-01', 'castigator': 'F', 'castigator_cui': 'C'}]
    flags = detect_publicare_intarziata(contracte)
    assert len(flags) == 0


def test_pub_niciun_flag_valoare_mica():
    """Contracte < 10.000 RON nu sunt flagate chiar dacă publicate târziu."""
    contracte = [_cp('Contract mic', 'CUI13', 5_000, '2025-01-02', '2025-06-01')]
    flags = detect_publicare_intarziata(contracte)
    assert len(flags) == 0


# ---------------------------------------------------------------------------
# Runner standalone (fara pytest)
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    tests = [
        # §2.1
        test_frag_detecteaza_3_contracte_sub_prag,
        test_frag_niciun_flag_sub_suma,
        test_frag_niciun_flag_interval_mare,
        test_frag_un_singur_contract,
        test_frag_titluri_diferite_nu_grupate,
        test_frag_schema_export_acceptata,
        test_frag_rev_ignorate_la_grupare,
        # §2.2
        test_conc_critic_cand_top3_peste_80,
        test_conc_major_cand_top3_intre_60_80,
        test_conc_niciun_flag_cand_sub_60,
        test_conc_niciun_flag_mai_putin_de_3_furnizori,
        # §2.6
        test_extra_major_la_26_procente,
        test_extra_critic_la_40_procente,
        test_extra_niciun_flag_la_25_procente,
        test_extra_niciun_flag_total_mic,
        # §2.7
        test_pub_mediu_la_15_zile,
        test_pub_critic_la_35_zile,
        test_pub_niciun_flag_in_termen,
        test_pub_niciun_flag_fara_data_atribuire,
        test_pub_niciun_flag_valoare_mica,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {t.__name__}: {e}')
            failed += 1
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
