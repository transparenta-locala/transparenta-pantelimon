"""Valorile de rezervă din index.html urmează raport.json (fără rețea)."""
from monitor_pantelimon import actualizeaza_semnale_index

HTML = ('<span id="idx-banner-nereguli">251</span> x <span id="idx-banner-critic">40</span>'
        ' <span class="v" id="idx-nereguli">251</span>')


def test_actualizeaza_toate_cele_trei_valori(tmp_path):
    f = tmp_path / "index.html"
    f.write_text(HTML, encoding="utf-8")
    assert actualizeaza_semnale_index(231, 20, str(f)) is True
    out = f.read_text(encoding="utf-8")
    assert 'id="idx-banner-nereguli">231<' in out
    assert 'id="idx-banner-critic">20<' in out
    assert 'id="idx-nereguli">231<' in out


def test_fara_schimbare_nu_rescrie(tmp_path):
    f = tmp_path / "index.html"
    f.write_text(HTML.replace("251", "231").replace(">40<", ">20<"), encoding="utf-8")
    assert actualizeaza_semnale_index(231, 20, str(f)) is False


def test_fisier_lipsa(tmp_path):
    assert actualizeaza_semnale_index(1, 1, str(tmp_path / "nu_exista.html")) is False
