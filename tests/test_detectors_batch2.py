"""
Teste unitare pentru detectori Batch 2 (AUDIT.md §2.1, §2.2, §2.7):
  - detect_valori_identice_aceeasi_zi   (§2.1-audit)
  - detect_burst_contracte              (§2.2-audit)
  - detect_semnare_zile_nelucratoare    (§2.7-audit)

Rulare: py -m pytest tests/test_detectors_batch2.py -v
Sau:    py tests/test_detectors_batch2.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_pantelimon import (
    detect_valori_identice_aceeasi_zi,
    detect_burst_contracte,
    detect_semnare_zile_nelucratoare,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(titlu, cui, valoare, data='2025-03-01'):
    """Contract schema internă."""
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
    """Contract schema export."""
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
# §2.1-audit  detect_valori_identice_aceeasi_zi
# ===========================================================================

def test_ident_3_firme_aceeasi_zi_aceeasi_valoare():
    """3 firme, aceeași valoare, aceeași zi → 1 semnal MEDIU, valoarea NU se înmulțește.

    Regresie reală (2025-07-29, școli gimnaziale): un contract atribuit unei asocieri
    de 3 firme era raportat ca „88,5 mil." și „împărțire artificială a unui lot"."""
    contracte = [
        _c('Contract A', 'CUI1', 29_508_940, '2025-07-29'),
        _c('Contract B', 'CUI2', 29_508_940, '2025-07-29'),
        _c('Contract C', 'CUI3', 29_508_940, '2025-07-29'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 1, f'Asteptat 1 flag, got {len(flags)}'
    f = flags[0]
    assert f['tip'] == 'VALORI_IDENTICE_ACEEASI_ZI'
    assert f['severitate'] == 'MEDIU'
    assert f['nr_firme'] == 3
    assert f['nr_contracte'] == 3
    assert abs(f['valoare'] - 29_508_940) < 1
    assert 'artificial' not in f['descriere']
    assert 'nu se adună' in f['descriere']


def test_ident_2_firme_aceeasi_zi():
    """2 firme, aceeași valoare, aceeași zi (≥ min_firme=2) → 1 flag."""
    contracte = [
        _c('X', 'F1', 150_000, '2025-05-10'),
        _c('Y', 'F2', 150_000, '2025-05-10'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 1
    assert flags[0]['nr_firme'] == 2


def test_ident_aceeasi_firma_nu_e_flag():
    """Aceeași firmă cu 2 contracte de aceeași valoare → nu e problemă."""
    contracte = [
        _c('X', 'F1', 150_000, '2025-05-10'),
        _c('Y', 'F1', 150_000, '2025-05-10'),  # same CUI
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 0


def test_ident_valori_diferite_aceeasi_zi():
    """Firme diferite, valori diferite → niciun flag."""
    contracte = [
        _c('A', 'F1', 100_000, '2025-06-01'),
        _c('B', 'F2', 200_000, '2025-06-01'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 0


def test_ident_aceeasi_valoare_zile_diferite():
    """Aceeași valoare, firme diferite, dar zile diferite → nu e problemă."""
    contracte = [
        _c('X', 'F1', 150_000, '2025-03-01'),
        _c('Y', 'F2', 150_000, '2025-03-15'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 0


def test_ident_sub_prag_minim():
    """Valoare sub min_valoare_ron (100k) → ignorată."""
    contracte = [
        _c('A', 'F1', 50_000, '2025-04-01'),
        _c('B', 'F2', 50_000, '2025-04-01'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 0


def test_ident_schema_export_acceptata():
    """Funcția acceptă și schema export (valoare/cui/data)."""
    contracte = [
        _ce('A', 'C1', 200_000, '2025-08-15'),
        _ce('B', 'C2', 200_000, '2025-08-15'),
    ]
    flags = detect_valori_identice_aceeasi_zi(contracte)
    assert len(flags) == 1
    assert flags[0]['nr_firme'] == 2


# ===========================================================================
# §2.2-audit  detect_burst_contracte
# ===========================================================================

def test_burst_5_contracte_intr_o_zi():
    """5 contracte în aceeași zi (≥ prag_nr=5) → MEDIU."""
    contracte = [_c(f'C{i}', f'F{i}', 60_000, '2025-09-05') for i in range(5)]
    flags = detect_burst_contracte(contracte)
    assert len(flags) == 1
    f = flags[0]
    assert f['tip'] == 'BURST_CONTRACTE'
    assert f['severitate'] == 'MEDIU'
    assert f['nr_contracte'] == 5


def test_burst_10_contracte_critic():
    """10+ contracte în aceeași zi → MAJOR."""
    contracte = [_c(f'C{i}', f'F{i}', 60_000, '2025-09-10') for i in range(11)]
    flags = detect_burst_contracte(contracte)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'MAJOR'
    assert flags[0]['nr_contracte'] == 11


def test_burst_sub_prag_niciun_flag():
    """4 contracte (sub prag_nr=5) → niciun flag dacă nu e weekend."""
    contracte = [_c(f'C{i}', f'F{i}', 60_000, '2025-09-08') for i in range(4)]  # luni
    flags = detect_burst_contracte(contracte)
    assert len(flags) == 0


def test_burst_weekend_valoare_mare():
    """2 contracte în weekend, valoare totală > 200k → flag MEDIU (chiar sub prag_nr)."""
    # 2025-07-05 = Sâmbătă
    contracte = [
        _c('A', 'F1', 150_000, '2025-07-05'),
        _c('B', 'F2', 100_000, '2025-07-05'),
    ]
    flags = detect_burst_contracte(contracte)
    assert len(flags) == 1
    assert flags[0]['weekend'] is True
    assert flags[0]['tip'] == 'BURST_CONTRACTE'


def test_burst_zile_diferite_nu_grup():
    """Contracte distribuite pe zile diferite → nu se grupează în burst."""
    contracte = [_c(f'C{i}', f'F{i}', 60_000, f'2025-06-{i+1:02d}') for i in range(5)]
    flags = detect_burst_contracte(contracte)
    assert len(flags) == 0


# ===========================================================================
# §2.7-audit  detect_semnare_zile_nelucratoare
# ===========================================================================

def test_semnare_weekend_sabata():
    """Contract > 50k semnat sâmbătă → MEDIU."""
    # 2025-07-05 = Sâmbătă
    contracte = [_c('IT', 'F1', 100_000, '2025-07-05')]
    flags = detect_semnare_zile_nelucratoare(contracte)
    assert len(flags) == 1
    f = flags[0]
    assert f['tip'] == 'SEMNARE_ZI_NELUCRATOARE'
    assert f['severitate'] == 'MEDIU'
    assert f['weekend'] is True


def test_semnare_zi_lucratoare_niciun_flag():
    """Contract semnat luni → niciun flag."""
    # 2025-06-02 = Luni
    contracte = [_c('X', 'F1', 100_000, '2025-06-02')]
    flags = detect_semnare_zile_nelucratoare(contracte)
    assert len(flags) == 0


def test_semnare_sub_prag_ignorata():
    """Contract < 50k în weekend → sub prag, ignorat."""
    # 2025-07-06 = Duminică
    contracte = [_c('Y', 'F1', 30_000, '2025-07-06')]
    flags = detect_semnare_zile_nelucratoare(contracte)
    assert len(flags) == 0


def test_semnare_sarbatoare_1_decembrie():
    """Contract semnat de 1 Decembrie (Ziua Națională) → MEDIU."""
    contracte = [_c('Z', 'F1', 200_000, '2025-12-01')]
    flags = detect_semnare_zile_nelucratoare(contracte)
    assert len(flags) == 1
    assert flags[0]['sarbatoare'] is True


def test_semnare_schema_export_acceptata():
    """Schema export (valoare/data) — semnat sâmbătă → flag."""
    # 2025-07-12 = Sâmbătă
    contracte = [_ce('A', 'C1', 80_000, '2025-07-12')]
    flags = detect_semnare_zile_nelucratoare(contracte)
    assert len(flags) == 1
    assert flags[0]['weekend'] is True


# ---------------------------------------------------------------------------
# Runner standalone
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    tests = [
        # §2.1-audit
        test_ident_3_firme_aceeasi_zi_aceeasi_valoare,
        test_ident_2_firme_aceeasi_zi,
        test_ident_aceeasi_firma_nu_e_flag,
        test_ident_valori_diferite_aceeasi_zi,
        test_ident_aceeasi_valoare_zile_diferite,
        test_ident_sub_prag_minim,
        test_ident_schema_export_acceptata,
        # §2.2-audit
        test_burst_5_contracte_intr_o_zi,
        test_burst_10_contracte_critic,
        test_burst_sub_prag_niciun_flag,
        test_burst_weekend_valoare_mare,
        test_burst_zile_diferite_nu_grup,
        # §2.7-audit
        test_semnare_weekend_sabata,
        test_semnare_zi_lucratoare_niciun_flag,
        test_semnare_sub_prag_ignorata,
        test_semnare_sarbatoare_1_decembrie,
        test_semnare_schema_export_acceptata,
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
