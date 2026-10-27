"""
tests/test_contoare_analiza.py
==============================
Teste pentru actualizeaza_contoare_analiza(): contoarele tp-nr-* / tp-an-* din
transparenta_pantelimon.html trebuie actualizate indiferent de tag-ul inline
(tp-nr-contracte e <strong>, restul <span>) — altfel rămân blocate la valoarea veche.
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_pantelimon import actualizeaza_contoare_analiza

RADACINA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ID_NR = ('tp-nr-contracte', 'tp-nr-analiza', 'tp-nr-top10',
         'tp-nr-directe', 'tp-nr-stat-card')
ID_AN = ('tp-an-analiza', 'tp-an-top10', 'tp-an-stat-card')

HTML_MINIMAL = """<html><body>
<p>Vezi toate cele <strong id="tp-nr-contracte">506</strong> contracte</p>
<p><span id="tp-nr-analiza">743</span> contracte · <span id="tp-an-analiza">2020</span></p>
<p><b id="tp-nr-top10">1</b> · <b id="tp-an-top10">2019</b></p>
<p><span class="val" id="tp-nr-stat-card">743</span> <span id="tp-an-stat-card">2021</span></p>
</body></html>
"""


def _contracte(n):
    return [{'id': f'C{i}', 'titlu': f'Contract {i}', 'valoare': 1000} for i in range(n)]


def _ruleaza(tmp_path, html, n):
    pagina = tmp_path / 'transparenta_pantelimon.html'
    pagina.write_text(html, encoding='utf-8')
    actualizeaza_contoare_analiza(_contracte(n), tp_path=str(pagina))
    return pagina.read_text(encoding='utf-8')


def test_strong_actualizat(tmp_path):
    out = _ruleaza(tmp_path, HTML_MINIMAL, 812)
    assert '<strong id="tp-nr-contracte">812</strong>' in out
    assert '506' not in out


def test_span_si_b_actualizate(tmp_path):
    an = datetime.now().year
    out = _ruleaza(tmp_path, HTML_MINIMAL, 812)
    assert '<span id="tp-nr-analiza">812</span>' in out
    assert '<b id="tp-nr-top10">812</b>' in out
    assert '<span class="val" id="tp-nr-stat-card">812</span>' in out
    for elem_id in ('tp-an-analiza', 'tp-an-stat-card'):
        assert f'id="{elem_id}">{an}</span>' in out
    assert f'<b id="tp-an-top10">{an}</b>' in out


def test_tag_nepereche_neatins(tmp_path):
    # Închiderea trebuie să fie același tag: <strong>…</span> nu e un contor valid.
    html = '<strong id="tp-nr-contracte">506</span>'
    assert _ruleaza(tmp_path, html, 812) == html


def test_toate_id_urile_din_pagina_reala_sunt_tintite():
    """Fiecare id din listă există în pagină într-o formă pe care regex-ul o prinde."""
    with open(os.path.join(RADACINA, 'transparenta_pantelimon.html'), encoding='utf-8') as f:
        pagina = f.read()
    for elem_id in ID_NR:
        assert re.search(rf'<(span|strong|b)\b[^>]*id="{elem_id}"[^>]*>\d+</\1>', pagina), elem_id
    for elem_id in ID_AN:
        assert re.search(rf'<(span|strong|b)\b[^>]*id="{elem_id}"[^>]*>\d{{4}}</\1>', pagina), elem_id
