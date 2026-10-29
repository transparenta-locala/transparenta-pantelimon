"""Logo-ul site-ului (logo_tp.py): meniul, iconițele și imaginile de distribuire."""
import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from logo_tp import CULORI_OG, deseneaza_simbol, lipeste_simbol, logo_svg, simbol_svg  # noqa: E402
from site_shell import header_html, head_html  # noqa: E402


def test_meniul_are_simbolul_cu_dimensiuni_fixe():
    """Fără width/height în HTML, meniul s-ar muta la încărcarea CSS-ului (CLS)."""
    h = header_html("furnizori/x.html", "X", {})
    brand = re.search(r'<a href="\.\./index\.html" class="tp-nav-brand">(.*?)</a>', h).group(1)
    assert brand.startswith('<svg class="tp-logo" width="44" height="44" viewBox="0 0 48 48"')
    assert 'aria-hidden="true"' in brand
    assert '<span class="tp-nav-name">Transparența Pantelimon<small>Inițiativă civică</small></span>' in brand


def test_simbolul_din_meniu_ia_culorile_din_css():
    """Culorile vin din variabile (.tp-logo în tp.css), ca să se schimbe cu tema întunecată."""
    s = simbol_svg()
    assert "var(--tp-logo-bg" in s and "var(--tp-logo-fg" in s and "var(--tp-logo-hi" in s
    css = open(os.path.join(REPO_ROOT, "assets", "tp.css"), encoding="utf-8").read()
    assert re.search(r'html\[data-tp-theme="dark"\] \.tp-logo \{[^}]*--tp-logo-bg', css)


def test_logo_svg_fix_e_identic_cu_fisierul():
    with open(os.path.join(REPO_ROOT, "assets", "logo.svg"), encoding="utf-8") as fh:
        assert fh.read() == logo_svg(), "rulează: python logo_tp.py"


def test_head_anunta_iconita_svg():
    h = head_html("index.html")
    assert '<link rel="icon" href="assets/logo.svg" type="image/svg+xml">' in h


@pytest.mark.parametrize("nume,marime", [
    ("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512),
    ("apple-touch-icon.png", 180),
])
def test_iconite_au_marimea_corecta(nume, marime):
    from PIL import Image
    with Image.open(os.path.join(REPO_ROOT, nume)) as im:
        assert im.size == (marime, marime)


def test_apple_touch_icon_fara_transparenta():
    """iOS umple transparența cu negru."""
    from PIL import Image
    with Image.open(os.path.join(REPO_ROOT, "apple-touch-icon.png")) as im:
        assert im.mode == "RGB"


def test_favicon_are_16_32_48():
    from PIL import Image
    with Image.open(os.path.join(REPO_ROOT, "favicon.ico")) as im:
        assert {(16, 16), (32, 32), (48, 48)} <= set(im.info["sizes"])


def test_manifest_are_iconita_maskable_separata():
    with open(os.path.join(REPO_ROOT, "manifest.webmanifest"), encoding="utf-8") as fh:
        icons = json.load(fh)["icons"]
    mask = [i for i in icons if i.get("purpose") == "maskable"]
    assert mask and all(i["src"] == "/icon-maskable-512.png" for i in mask)
    for i in icons:
        assert os.path.exists(os.path.join(REPO_ROOT, i["src"].lstrip("/")))


def test_simbolul_desenat_cu_pillow():
    img = deseneaza_simbol(64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0          # colțul rotunjit e transparent
    assert img.getpixel((32, 4))[3] == 255       # fundalul e plin
    plin = deseneaza_simbol(64, plin=True)
    assert plin.getpixel((0, 0))[3] == 255


def test_lipeste_simbol_pe_imagine():
    from PIL import Image
    img = Image.new("RGB", (200, 100), "#14263D")
    lipeste_simbol(img, 10, 10, 52)
    r, g, b = img.getpixel((10 + 26, 10 + 3))
    assert (r, g, b) != (0x14, 0x26, 0x3D)
    assert img.getpixel((150, 50)) == (0x14, 0x26, 0x3D)
    assert CULORI_OG["bg"] == "#4D86C2"
