"""Modelele Word descărcabile există, sunt .docx valide și nu mai există linkuri spre /contact/ (404)."""
import os, re, zipfile, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_fiecare_link_catre_modele_exista():
    lipsa = []
    for pagina in glob.glob(os.path.join(ROOT, "*.html")):
        html = open(pagina, encoding="utf-8").read()
        for href in re.findall(r'href="(modele/[^"]+)"', html):
            if not os.path.exists(os.path.join(ROOT, href)):
                lipsa.append((os.path.basename(pagina), href))
    assert not lipsa, lipsa


def test_modelele_sunt_docx_valide_si_fara_praguri_vechi():
    fisiere = glob.glob(os.path.join(ROOT, "modele", "*.docx"))
    assert len(fisiere) >= 7
    for f in fisiere:
        with zipfile.ZipFile(f) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert "130.000" not in xml and "130K" not in xml, f


def test_fara_link_la_pagina_de_contact_inexistenta():
    for pagina in glob.glob(os.path.join(ROOT, "*.html")):
        assert "primariapantelimon.ro/contact" not in open(pagina, encoding="utf-8").read(), pagina
