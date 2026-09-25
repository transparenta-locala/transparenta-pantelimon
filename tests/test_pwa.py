"""
tests/test_pwa.py
§4.3 Service Worker / PWA — teste validare fișiere

Verifică:
- manifest.webmanifest: JSON valid, câmpuri PWA obligatorii
- sw.js: fișier prezent, conține strategiile de cache
- enhance.js: conține înregistrarea SW
- icon-192.png / icon-512.png: fișiere prezente
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestManifest:

    def test_manifest_exista(self):
        """manifest.webmanifest este prezent în repo."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        assert os.path.exists(path), "manifest.webmanifest lipsește"

    def test_manifest_json_valid(self):
        """manifest.webmanifest este JSON valid."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_manifest_name(self):
        """Câmpul name este prezent și non-vid."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert data.get('name'), "Câmpul 'name' lipsește sau e gol"

    def test_manifest_start_url(self):
        """start_url este prezent."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert 'start_url' in data

    def test_manifest_display(self):
        """display este unul din valorile PWA valide."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        valid = {'standalone', 'fullscreen', 'minimal-ui', 'browser'}
        assert data.get('display') in valid

    def test_manifest_icons(self):
        """Secțiunea icons conține cel puțin 2 intrări."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        icons = data.get('icons', [])
        assert len(icons) >= 2, "Trebuie cel puțin 2 iconuri (192 și 512)"

    def test_manifest_icons_sizes(self):
        """Iconurile includ 192x192 și 512x512."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        sizes = {icon.get('sizes') for icon in data.get('icons', [])}
        assert '192x192' in sizes, "Icon 192x192 lipsește"
        assert '512x512' in sizes, "Icon 512x512 lipsește"

    def test_manifest_theme_color(self):
        """theme_color este prezent."""
        path = os.path.join(REPO_ROOT, 'manifest.webmanifest')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert 'theme_color' in data


class TestServiceWorker:

    def test_sw_exista(self):
        """sw.js este prezent în repo."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        assert os.path.exists(path), "sw.js lipsește"

    def test_sw_contine_install_event(self):
        """sw.js conține listener pentru 'install'."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert "addEventListener('install'" in content or 'addEventListener("install"' in content

    def test_sw_contine_fetch_event(self):
        """sw.js conține listener pentru 'fetch'."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert "addEventListener('fetch'" in content or 'addEventListener("fetch"' in content

    def test_sw_contine_activate_event(self):
        """sw.js conține listener pentru 'activate'."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert "addEventListener('activate'" in content or 'addEventListener("activate"' in content

    def test_sw_contine_core_urls(self):
        """sw.js are o listă de URL-uri core de pre-cached."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'index.html' in content
        assert 'enhance.min.js' in content

    def test_sw_data_urls_contine_csv(self):
        """/contracte.csv este inclus în DATA_URLS din sw.js."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert '/contracte.csv' in content

    def test_sw_cache_version_bumped(self):
        """Versiunea cache CACHE_STATIC este tp-static-v7 (bump: fix normalizare cautare in enhance.min.js)."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'tp-static-v7' in content

    def test_sw_network_first_csv(self):
        """sw.js contine functia networkFirstCsv pentru fallback CSV offline."""
        path = os.path.join(REPO_ROOT, 'sw.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'networkFirstCsv' in content
        assert 'text/csv' in content


class TestPWAIcons:

    def test_icon_192_exista(self):
        """icon-192.png este prezent."""
        path = os.path.join(REPO_ROOT, 'icon-192.png')
        assert os.path.exists(path), "icon-192.png lipsește"

    def test_icon_512_exista(self):
        """icon-512.png este prezent."""
        path = os.path.join(REPO_ROOT, 'icon-512.png')
        assert os.path.exists(path), "icon-512.png lipsește"

    def test_icon_192_dimensiune(self):
        """icon-192.png are cel puțin 100 bytes (nu e gol)."""
        path = os.path.join(REPO_ROOT, 'icon-192.png')
        assert os.path.getsize(path) > 100, "icon-192.png pare corupt sau gol"

    def test_icon_512_dimensiune(self):
        """icon-512.png are cel puțin 100 bytes (nu e gol)."""
        path = os.path.join(REPO_ROOT, 'icon-512.png')
        assert os.path.getsize(path) > 100, "icon-512.png pare corupt sau gol"


class TestEnhanceJSPWA:

    def test_enhance_inregistreaza_sw(self):
        """enhance.js conține înregistrarea Service Worker."""
        path = os.path.join(REPO_ROOT, 'enhance.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'serviceWorker' in content
        assert "register('/sw.js'" in content or 'register("/sw.js"' in content

    def test_enhance_injecteaza_manifest(self):
        """enhance.js injectează link manifest dacă lipsește."""
        path = os.path.join(REPO_ROOT, 'enhance.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'manifest.webmanifest' in content

    def test_enhance_injecteaza_theme_color(self):
        """enhance.js injectează meta theme-color."""
        path = os.path.join(REPO_ROOT, 'enhance.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        assert 'theme-color' in content
