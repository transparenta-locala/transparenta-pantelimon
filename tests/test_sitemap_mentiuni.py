"""
Teste unitare pentru genereaza_sitemap + integrarea mentiuni_media.json
în genereaza_pagina_furnizor.

Rulare: py tests/test_sitemap_mentiuni.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitor_pantelimon import genereaza_sitemap, genereaza_pagina_furnizor


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _idx(slug='firma-test', valoare=100_000):
    return {'slug': slug, 'nume': 'FIRMA TEST SRL', 'count': 5,
            'valoare': valoare, 'flags_critic': 0, 'flags_major': 1, 'flags_mediu': 0}


def _contract(titlu='Servicii curatenie', valoare=50_000, data='2025-03-01', cui='12345678'):
    return {
        'titlu': titlu, 'castigator': 'FIRMA TEST SRL',
        'castigator_cui': cui, 'valoare_ron': valoare,
        'data_publicare': data, 'tip_procedura': 'achizitie-directa',
        'contract_id': f'test-{cui}',
    }


def _mentiune(titlu='Investigație', url='https://rise.ro/test', data='2026-01-01',
              outlet='rise.ro', rezumat='Firma a apărut în articol.'):
    return {'titlu': titlu, 'url': url, 'data': data, 'outlet': outlet, 'rezumat': rezumat}


CONFIG_TEST = {'cui': '4420759', 'nume_entitate': 'Test', '_scor': {}}


# ──────────────────────────────────────────────────────────────────────────────
# genereaza_sitemap — teste
# ──────────────────────────────────────────────────────────────────────────────

def test_sitemap_contine_paginile_statice():
    """Sitemap-ul conține cele 9 URL-uri statice (incl. gdpr, petitie, harta)."""
    xml = genereaza_sitemap([])
    assert 'raport_transparenta.html' in xml
    assert 'transparenta_pantelimon.html' in xml
    assert 'presa.html' in xml
    assert 'gdpr.html' in xml
    assert 'petitie.html' in xml
    assert 'harta.html' in xml
    assert 'furnizori/index.html' in xml
    assert 'transparenta-pantelimon.eu' in xml


def test_sitemap_structura_xml_valida():
    """Sitemap-ul are header XML și tag urlset corect."""
    xml = genereaza_sitemap([])
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in xml
    assert '</urlset>' in xml


def test_sitemap_fara_furnizori_contine_9_url():
    """Fără furnizori, sitemap-ul are exact 10 URL-uri statice (incl. gdpr + petitie + harta + modele)."""
    xml = genereaza_sitemap([])
    assert xml.count('<url>') == 10  # + modele.html


def test_sitemap_cu_furnizori_creste_numaratoarea():
    """Cu 3 furnizori, sitemap-ul are 9 + 3 = 12 URL-uri."""
    index = [_idx(f'firma-{i}') for i in range(3)]
    xml = genereaza_sitemap(index)
    assert xml.count('<url>') == 13  # + modele.html


def test_sitemap_contine_slug_furnizor():
    """URL-ul paginii furnizorului apare în sitemap."""
    index = [_idx('midas-road-srl')]
    xml = genereaza_sitemap(index)
    assert '/furnizori/midas-road-srl.html' in xml


def test_sitemap_furnizori_au_priority_05():
    """Paginile furnizorilor au prioritate 0.5."""
    index = [_idx('firma-test')]
    xml = genereaza_sitemap(index)
    # Numărăm că există cel puțin un <priority>0.5</priority>
    assert '<priority>0.5</priority>' in xml


def test_sitemap_contine_lastmod():
    """Fiecare URL conține un <lastmod> cu dată."""
    xml = genereaza_sitemap([_idx()])
    assert '<lastmod>' in xml


def test_sitemap_raport_are_priority_09():
    """raport_transparenta.html are priority 0.9."""
    xml = genereaza_sitemap([])
    assert '<priority>0.9</priority>' in xml


def test_sitemap_changefreq_daily_pe_raport():
    """Raportul are changefreq daily (se actualizează frecvent)."""
    xml = genereaza_sitemap([])
    assert '<changefreq>daily</changefreq>' in xml


def test_sitemap_furnizori_sortati_alfabetic():
    """URL-urile furnizorilor apar în ordine slug-alfabetică."""
    index = [_idx('zz-firma'), _idx('aa-firma'), _idx('mm-firma')]
    xml = genereaza_sitemap(index)
    pos_aa = xml.index('aa-firma')
    pos_mm = xml.index('mm-firma')
    pos_zz = xml.index('zz-firma')
    assert pos_aa < pos_mm < pos_zz


# ──────────────────────────────────────────────────────────────────────────────
# genereaza_pagina_furnizor — mentiuni
# ──────────────────────────────────────────────────────────────────────────────

def test_pagina_fara_mentiuni_nu_afiseaza_sectiune():
    """Fără mențiuni, secțiunea 📰 nu apare în pagina HTML."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST
    )
    assert '📰' not in html


def test_pagina_cu_mentiuni_afiseaza_sectiune():
    """Cu o mențiune, secțiunea 📰 Mențiuni în presă apare."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune()]
    )
    assert '📰' in html
    assert 'Mențiuni în presă' in html


def test_pagina_mentiune_contine_titlul_articolului():
    """Titlul articolului apare în pagina firmei."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(titlu='Ancheta Rise Project')]
    )
    assert 'Ancheta Rise Project' in html


def test_pagina_mentiune_contine_link():
    """URL-ul articolului apare ca link în pagina firmei."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(url='https://rise.ro/investigatie-test')]
    )
    assert 'https://rise.ro/investigatie-test' in html


def test_pagina_mentiune_contine_outlet():
    """Outlet-ul (sursa) articolului apare în pagina firmei."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(outlet='g4media.ro')]
    )
    assert 'g4media.ro' in html


def test_pagina_mentiune_contine_rezumat():
    """Rezumatul mențiunii apare în pagina firmei."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(rezumat='Firma apare în legătură cu contracte suspecte.')]
    )
    assert 'Firma apare în legătură cu contracte suspecte.' in html


def test_pagina_mentiuni_multiple_numaratoare():
    """Numărul mențiunilor apare corect (2 mențiuni)."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(), _mentiune(titlu='Al doilea articol')]
    )
    assert '(2)' in html


def test_pagina_mentiuni_xss_escape():
    """Titlul cu caractere HTML este escapeat corect."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(titlu='<script>alert(1)</script>')]
    )
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_pagina_mentiune_fara_rezumat_nu_afiseaza_rand_gol():
    """Mențiune fără rezumat nu lasă un div gol."""
    html = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[_mentiune(rezumat='')]
    )
    # Secțiunea trebuie să existe, fără div-uri goale pentru rezumat
    assert '📰' in html


def test_pagina_mentiuni_none_echivalent_cu_gol():
    """mentiuni=None (default) și mentiuni=[] produc același comportament: fără secțiune."""
    html_none = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=None
    )
    html_gol = genereaza_pagina_furnizor(
        'FIRMA TEST SRL', 'firma-test-srl', [], [_contract()], CONFIG_TEST,
        mentiuni=[]
    )
    assert '📰' not in html_none
    assert '📰' not in html_gol


# ──────────────────────────────────────────────────────────────────────────────
# Runner standalone
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    tests = [
        test_sitemap_contine_paginile_statice,
        test_sitemap_structura_xml_valida,
        test_sitemap_fara_furnizori_contine_9_url,
        test_sitemap_cu_furnizori_creste_numaratoarea,
        test_sitemap_contine_slug_furnizor,
        test_sitemap_furnizori_au_priority_05,
        test_sitemap_contine_lastmod,
        test_sitemap_raport_are_priority_09,
        test_sitemap_changefreq_daily_pe_raport,
        test_sitemap_furnizori_sortati_alfabetic,
        test_pagina_fara_mentiuni_nu_afiseaza_sectiune,
        test_pagina_cu_mentiuni_afiseaza_sectiune,
        test_pagina_mentiune_contine_titlul_articolului,
        test_pagina_mentiune_contine_link,
        test_pagina_mentiune_contine_outlet,
        test_pagina_mentiune_contine_rezumat,
        test_pagina_mentiuni_multiple_numaratoare,
        test_pagina_mentiuni_xss_escape,
        test_pagina_mentiune_fara_rezumat_nu_afiseaza_rand_gol,
        test_pagina_mentiuni_none_echivalent_cu_gol,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {t.__name__}: {e}')
            import traceback; traceback.print_exc()
            failed += 1
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
