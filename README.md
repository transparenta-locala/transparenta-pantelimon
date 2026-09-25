# Transparenta Pantelimon

Monitorizare cetateasca automata a achizitiilor publice ale Primariei Pantelimon.

**Site live:** [transparenta-pantelimon.eu](https://transparenta-pantelimon.eu)  
**Raport semnale de risc:** [transparenta-pantelimon.eu/raport_transparenta.html](https://transparenta-pantelimon.eu/raport_transparenta.html)
**Retele firme:** [transparenta-pantelimon.eu/retele.html](https://transparenta-pantelimon.eu/retele.html)

> **Stare curentă:** valorile live (semnale, contracte unice afectate, severități și data generării) sunt publicate în `raport.json`; nu se mențin manual în README.

---

## Ce face

- Trage lunar contractele din SEAP (e-licitatie.ro) si bugetul de la ANAF
- Aplica **19 algoritmi** de detectie pentru pattern-uri de risc (fragmentare artificiala, monopol furnizor, achizitii directe peste prag, shell companies, geocodare furnizori, date financiare ANAF)
- Detecteaza **mentiuni de risc in presa** automat (Google News + Context.ro RSS)
- Analizeaza **retele de firme** cu adresa fiscala comuna (Cytoscape.js)
- Genereaza raport HTML + JSON + RSS + press-kit + harta + retele interactiva furnizori
- Publica automat pe GitHub Pages prin GitHub Actions (cron lunar, în ziua 1 la 06:00 UTC)
- Surse externe: Curtea de Conturi, ANI declaratii avere, TED Europa, MOL primarie, data.gov.ro ANAF

## Structura repo

```
monitor_pantelimon.py          # Scriptul principal (~6000 linii)
monitor_uat.py                 # CLI wrapper multi-UAT (orice CIF de primarie)
monitorizare_presa.py          # Monitorizare presă automată (Google News + Context.ro)
analizeaza_retele.py           # Detectare retele firme cu adresa comuna
import_financiar_datagov.py    # Import situatii financiare ANAF din data.gov.ro
enricheaza_firme.py            # Enrichment CUI + flaguri financiare
transparenta_pantelimon.html   # Pagina principala (site static)
raport_transparenta.html       # Raport generat (output monitor, network-first SW)
harta.html                     # Harta interactiva furnizori (Leaflet.js)
retele.html                    # Graf retele firme (Cytoscape.js)
presa.html                     # Pagina jurnalisti + press kit
petitie.html                   # Petitie cetateneasca (Formspree)
despre.html                    # Metodologie + institutii sesizare
gdpr.html                      # Politica de confidentialitate
sw.js                          # Service Worker PWA v5 (Cache-First/Network-First)
manifest.webmanifest           # PWA manifest (instalabil pe telefon)
icon-192.png / icon-512.png    # Icoane PWA
contracte.json                 # Export contracte SEAP (JSON)
contracte.csv                  # Export contracte SEAP (CSV — Excel/Sheets)
    raport.json                    # Export semnale automate (format JSON public)
    feed.xml                       # RSS/Atom feed semnale noi
press_kit.json                 # Press kit date structurate (generat automat)
firme_geocoded.json            # Sedii firme geocodate cu Nominatim OSM
firme_financiar.json           # Situatii financiare ANAF 2024 (83 firme)
retele_firme.json              # Graf retele firme (noduri + edges)
mentiuni_presa_auto.json       # Mentiuni presa detectate automat (generat automat)
furnizori/                     # Pagini per furnizor (generate automat)
risc_firma.py                  # Modul detector shell companies + date financiare
    .github/workflows/             # GitHub Actions (rulare automata lunara)
tests/                         # 380+ teste unitare (toate offline, mock urllib)
API.md                         # Documentatie API JSON/CSV public
AUDIT.md                       # Audit tehnic public
```

## Replicare pentru alta localitate

```bash
git clone https://github.com/transparenta-locala/transparenta-pantelimon
cd transparenta-pantelimon
pip install -r requirements.txt

# Foloseste CLI-ul multi-UAT:
py monitor_uat.py 4420759                                            # Pantelimon (default)
py monitor_uat.py 4364643 --judet Ilfov --uat-search Voluntari      # Voluntari
py monitor_uat.py 4364660 --judet Ilfov --uat-search Popesti-Leordeni
py monitor_uat.py 4420759 --dry-run                                  # Preview CONFIG fara scraping
```

## Algoritmi de detectie (red flags)

| Algoritm | Tip flag | Severitate | Ce detecteaza |
|----------|----------|-----------|---------------|
| 1a | `OFERTANT_UNIC` | MAJOR | Setul de date indică un singur ofertant; necesită verificare |
| 1b | `ACHIZITIE_DIRECTA_PESTE_PRAG` | CRITIC | Contract individual peste pragul categoriei aplicabile |
| 2 | `PROCEDURI_NON_COMPETITIVE` | MAJOR | Exces proceduri non-competitive (>40%) |
| 3 | `FRAGMENTARE` | CRITIC | Fragmentare artificiala (acelasi furnizor, titluri similare, interval <60 zile) |
| 4 | `FURNIZOR_DOMINANT` | MEDIU | Furnizor cu >35% din totalul contractelor |
| 5 | `CONCENTRARE_FURNIZOR` | MAJOR/CRITIC | Top-3 furnizori >60% / >80% din valoarea totala |
| 6 | `FRAGMENTARE_TEMPORARA` | CRITIC | Ferestra 90 zile, suma sub-prag > prag |
| 7 | `CRESTERE_BRUSCA_VALOARE` | MAJOR/CRITIC | Revizie contract cu crestere >50% de valoare |
| 8 | `VALOARE_ROTUNDA_SUSPECTA` | MEDIU | Valori rotunde (multiplu de 10k) — posibil fara studiu de piata |
| 9 | `VALORI_IDENTICE_ACEEASI_ZI` | CRITIC | Valoare exact identica la firme diferite in aceeasi zi |
| 10 | `BURST_CONTRACTE` | MEDIU/MAJOR | Volum anormal de contracte intr-o singura zi |
| 11 | `SEMNARE_ZI_NELUCRATOARE` | MEDIU | Contract semnat in weekend sau sarbatoare legala |
| 12 | `FIRMA_INACTIVA` | CRITIC | Contract cu firma inactiva/radiata la ANAF/ORC |
| 13 | `FIRMA_NOU_CREATA` | MAJOR/CRITIC | Firma cu <24 luni vechime la data contractului |
| 14 | `RISC_SISTEMIC_FIRMA` | CRITIC | Furnizor apărut în >=3 categorii diferite de indicatori |
| 15 | `PUBLICARE_INTARZIATA` | MEDIU/CRITIC | Intarziere publicare contract (>11 zile lucratoare) |
| 16 | `SEDINTE_EXTRAORDINARE_EXCESIVE` | MAJOR/CRITIC | Rata ridicata sedinte extraordinare (>25% / >=40%) |
| 17 | `GEOGRAFIE_ANORMALA` | MEDIU | Servicii locale (curatenie/paza/salubrizare) de la firma din afara Ilfov+limitrofe |
| 18 | `CIFRA_AFACERI_ZERO` | CRITIC | CA = 0 RON in anul anterior contractului (risc_firma.py) |
| 19 | `ZERO_ANGAJATI` | MAJOR | 0 angajati declarati la ANAF (risc_firma.py) |

Praguri fără TVA: Legea 98/2016 art. 7 alin. (5) — **270.120 RON** (produse/servicii), **900.400 RON** (lucrări). Valorile sunt centralizate în `config.py`.

## Surse externe integrate

| Sursa | Functie | Cache |
|---|---|---|
| SEAP / data.gov.ro | Contracte achiziții publice | 30 zile |
| ANAF / transparenta.eu | Buget executie | 30 zile |
| openapi.ro (ONRC) | Date firme (CUI, adresa, actionariat) | 30 zile |
| mfinante.gov.ro | Cifra afaceri, nr. angajati (shell detector) | 30 zile |
| data.gov.ro ANAF | Situatii financiare anuale (WEB_BL + WEB_UU + WEB_ONG) | 180 zile |
| Google News RSS | Mentiuni presa cu cuvinte-cheie de risc | 7 zile |
| Context.ro RSS | Mentiuni investigatii locale | 7 zile |
| Curtea de Conturi | Rapoarte audit UAT | 30 zile |
| ANI integritate.eu | Declaratii avere alesi locali | 30 zile |
| TED Europa | Anunțuri europene asociate cumpărătorului | 7 zile |
| MOL primarie | HCL-uri / rectificari buget | 7 zile |
| Nominatim OSM | Geocodare sedii firme | 180 zile |
| proiecte.pnrr.gov.ro | Proiecte PNRR beneficiar CIF | 7 zile |

## Teste automate

```bash
py -m pytest tests/ -v
```

**380+ teste unitare in 21+ fisiere** — toate ruleaza fara conexiune la retea (mock urllib/requests).

```
tests/test_detectors.py          # detectori batch 1 (fragmentare, concentrare, sedinte, publicare)
tests/test_detectors_batch2.py   # detectori batch 2 (valori identice, burst, semnare nelucratoare)
tests/test_geographic.py         # detector anomalie geografica
tests/test_risc_firma.py         # modul shell company (risc_firma.py)
tests/test_reconciliere.py       # widget reconciliere ANAF vs SEAP
tests/test_sitemap_mentiuni.py   # sitemap dinamic + mentiuni presa furnizori
tests/test_geocoding.py          # geocodare Nominatim + cache SQLite
tests/test_cc_ani.py             # Curtea de Conturi + ANI declaratii avere
tests/test_ted_mol.py            # TED Europa + MOL primarie
tests/test_press_kit.py          # press kit JSON + Markdown
tests/test_pwa.py                # Service Worker + manifest PWA + icoane
tests/test_pnrr.py               # PNRR tracker (cache SQLite + JSON/HTML fallback)
tests/test_monitor_uat.py        # CLI multi-UAT (argparse + build_config_overrides)
tests/test_csv_feed.py           # CSV export + feed Atom (XSS, sortare, max 20)
tests/test_state_analytics.py    # state persistence + analytics (incarca/salveaza/detecteaza)
tests/test_og_furnizori.py       # og-image 1200x630 (Pillow) + index furnizori A-Z
tests/test_utils.py              # functii utilitare (_seap_url, _fmt_ron, _termene_url, etc.)
tests/test_scor_transparenta.py  # calculeaza_scor_transparenta (subscoruri, ponderi, interval)
tests/test_kpi_breakdown.py      # _categorizeaza_contracte_breakdown (lucrari/servicii, dedup Rev.X)
tests/test_monitorizare_presa.py # monitorizare_presa.py (keyword match, false-positive, cache)
tests/test_retele_firme.py       # analizeaza_retele.py (norm adresa, clustering, gaseste_legate)
```

## Contribuie

- **Issues:** bug-uri, false-positive-uri sau idei noi
- **PR-uri:** cod nou (vezi `IMPROVEMENTS.md` si `AUDIT.md` pentru roadmap detaliat)
- **Fork la alta localitate:** deschide un issue, te ajutam cu configurarea

## Licenta

**Cod:** MIT
**Date generate (rapoarte, JSON, feed):** [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/)
Atribuire: *Transparenta Pantelimon — transparenta-pantelimon.eu*

## Disclaimer

Toate datele sunt fapte publice (SEAP, ANAF, ONRC). Site-ul nu face afirmatii
despre intentii sau vinovatie — doar afiseaza statistici si legi posibil incalcate.
Concluziile sunt la latitudinea cititorului.

## Contact

Inițiativă civică independentă de autorități. Inițiatorul este membru USR Pantelimon; proiectul nu este un proiect oficial al partidului.
Intrebari si sesizari: [deschide un Issue](https://github.com/transparenta-locala/transparenta-pantelimon/issues)

---

*Generat automat cu [GitHub Actions](https://github.com/transparenta-locala/transparenta-pantelimon/actions) — date publice SEAP + ANAF*
