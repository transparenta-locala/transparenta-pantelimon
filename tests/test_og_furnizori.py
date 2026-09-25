"""
tests/test_og_furnizori.py
PR #41 — teste unitare pentru:
  - genereaza_og_image()  (§5.7 — og-image.png 1200×630)
  - genereaza_index_furnizori()  (index A-Z furnizori)
Zero network, zero scraping.
"""
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from monitor_pantelimon import genereaza_og_image, genereaza_index_furnizori

# Detectam daca Pillow e instalat (CI il are, local poate lipseste)
try:
    from PIL import Image
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False


# ===========================================================================
# Fixtures
# ===========================================================================

INDEX_SAMPLE = [
    {
        "nume": "MIDAS ROAD SRL",
        "slug": "midas-road-srl",
        "valoare": 4320000.0,
        "count": 7,
        "flags_critic": 3,
        "flags_major": 2,
        "flags_mediu": 1,
    },
    {
        "nume": "ALA EXPERT SRL",
        "slug": "ala-expert-srl",
        "valoare": 500000.0,
        "count": 3,
        "flags_critic": 0,
        "flags_major": 1,
        "flags_mediu": 2,
    },
    {
        "nume": "CLEAN SERV SRL",
        "slug": "clean-serv-srl",
        "valoare": 120000.0,
        "count": 4,
        "flags_critic": 0,
        "flags_major": 0,
        "flags_mediu": 1,
    },
]


# ===========================================================================
# TestGenereazaOgImage
# ===========================================================================

class TestGenereazaOgImage:

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_returneaza_true_si_creeaza_fisier(self, tmp_path):
        """genereaza_og_image returneaza True si creeaza fisierul PNG."""
        out = str(tmp_path / "og-test.png")
        result = genereaza_og_image(47, 12, 313.7, scor=55, output=out)
        assert result is True
        assert os.path.exists(out)

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_dimensiuni_corecte(self, tmp_path):
        """Imaginea generata are dimensiunile 1200x630."""
        out = str(tmp_path / "og-dim.png")
        genereaza_og_image(10, 3, 50.0, scor=70, output=out)
        img = Image.open(out)
        assert img.size == (1200, 630)

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_mod_rgb(self, tmp_path):
        """Imaginea este in modul RGB (nu RGBA sau paleta)."""
        out = str(tmp_path / "og-mode.png")
        genereaza_og_image(100, 50, 999.9, output=out)
        img = Image.open(out)
        assert img.mode == "RGB"

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_fara_scor(self, tmp_path):
        """scor=None nu crapa — imaginea este generata fara panoul de scor."""
        out = str(tmp_path / "og-noscor.png")
        result = genereaza_og_image(47, 12, 313.7, scor=None, output=out)
        assert result is True
        assert os.path.exists(out)
        img = Image.open(out)
        assert img.size == (1200, 630)

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_scor_zero(self, tmp_path):
        """scor=0 este o valoare valida."""
        out = str(tmp_path / "og-scor0.png")
        result = genereaza_og_image(200, 100, 1000.0, scor=0, output=out)
        assert result is True

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_valori_extreme(self, tmp_path):
        """Valori extreme (0 flag-uri, 0 critice, 0 mil RON) nu crapa."""
        out = str(tmp_path / "og-zero.png")
        result = genereaza_og_image(0, 0, 0.0, scor=100, output=out)
        assert result is True

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_fisier_png_valid(self, tmp_path):
        """Fisierul generat este un PNG valid (header magic bytes)."""
        out = str(tmp_path / "og-valid.png")
        genereaza_og_image(50, 20, 250.0, output=out)
        with open(out, "rb") as f:
            header = f.read(8)
        # PNG magic bytes: \x89PNG\r\n\x1a\n
        assert header[:4] == b'\x89PNG'

    def test_returneaza_false_fara_pillow(self, monkeypatch):
        """Fara Pillow, functia returneaza False fara exceptie."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError(f"Mocked missing: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = genereaza_og_image(47, 12, 313.7)
        assert result is False

    @pytest.mark.skipif(not PILLOW_OK, reason="Pillow nu este instalat")
    def test_cale_invalida_returneaza_false(self, tmp_path):
        """Cale de output invalida → False fara exceptie fatala."""
        out = str(tmp_path / "subdir_inexistent" / "og.png")
        result = genereaza_og_image(47, 12, 313.7, output=out)
        assert result is False


# ===========================================================================
# TestGenereazaIndexFurnizori
# ===========================================================================

class TestGenereazaIndexFurnizori:

    def test_returneaza_string(self):
        """genereaza_index_furnizori returneaza un string non-gol."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_html_valid(self):
        """Rezultatul este HTML cu DOCTYPE."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert "<!DOCTYPE html>" in result

    def test_lista_goala_html_valid(self):
        """Lista goala produce HTML valid cu tabel gol."""
        result = genereaza_index_furnizori([])
        assert "<!DOCTYPE html>" in result
        assert "<table" in result

    def test_sortare_az(self):
        """Furnizorii sunt sortati alfabetic A-Z."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        pos_ala = result.find("ALA EXPERT")
        pos_clean = result.find("CLEAN SERV")
        pos_midas = result.find("MIDAS ROAD")
        assert pos_ala < pos_clean < pos_midas

    def test_linkuri_slug_html(self):
        """Fiecare furnizor are link spre {slug}.html."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert 'href="midas-road-srl.html"' in result
        assert 'href="ala-expert-srl.html"' in result
        assert 'href="clean-serv-srl.html"' in result

    def test_toate_numele_prezente(self):
        """Numele tuturor furnizorilor apar in HTML."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert "MIDAS ROAD SRL" in result
        assert "ALA EXPERT SRL" in result
        assert "CLEAN SERV SRL" in result

    def test_flags_critic_colorat(self):
        """Furnizorii cu flags CRITIC au culoare rosie in HTML."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        # Firma cu flags_critic=3 trebuie sa aiba culoarea rosie
        assert "#C0392B" in result

    def test_flags_zero_culoare_gri(self):
        """Furnizor fara nicio neregula are culoare gri."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert "#888" in result

    def test_canonical_url(self):
        """Pagina contine canonical URL spre transparenta-pantelimon.eu."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert "transparenta-pantelimon.eu/furnizori/" in result

    def test_enhance_js_inclus(self):
        """Sursa actualizată enhance.js este inclusă în pagină."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert 'src="../enhance.js"' in result

    def test_back_link_la_raport(self):
        """Pagina contine link de inapoi la raportul principal."""
        result = genereaza_index_furnizori(INDEX_SAMPLE)
        assert "raport_transparenta.html" in result
