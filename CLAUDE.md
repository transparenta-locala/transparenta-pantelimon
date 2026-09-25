# Monitor Transparență Bugetară — Pantelimon
## Context proiect (pentru Claude Code)

Acest proiect este o **inițiativă civică independentă de autorități**, inițiată de un membru USR Pantelimon; nu este un proiect oficial al partidului.
Monitorizează automat contractele și achizițiile publice ale Primăriei Pantelimon (CUI 4420759) și publică un raport HTML pe GitHub Pages.

---

## Structura fișierelor

```
github-repo/
├── monitor_pantelimon.py       # Scriptul principal — trage date SEAP, detectează red flags, generează HTML
├── raport_transparenta.html    # Raportul generat (output-ul monitorului) — publicat pe GitHub Pages
├── transparenta_pantelimon.html # Site static de prezentare (pagina principală)
├── stare_anterioara.json       # State persistence — pentru a detecta flags NOI față de rularea anterioară
├── contracte.json              # Export contracte (folosit de JS în HTML pentru "toate contractele firmei")
├── requirements.txt            # Dependențe Python
├── fix_si_push.bat             # RULEAZĂ MONITORUL + commit + push (scriptul principal de folosit pe Windows)
├── push_acum.bat               # Doar push (fără a rula monitorul)
├── ruleaza_monitor.bat         # Doar rulează monitorul, fără git
├── CLAUDE.md                   # Acest fișier
└── .github/workflows/          # GitHub Actions pentru rulare automată
```

**URL live (custom domain):** `https://transparenta-pantelimon.eu/`
**Raport live:** `https://transparenta-pantelimon.eu/raport_transparenta.html`
**GitHub Pages (redirect):** `https://transparenta-locala.github.io/transparenta-pantelimon/`

---

## Cum se rulează

### Normal (recomandat pe Windows):
```
Double-click fix_si_push.bat
```
Sau din terminal:
```bash
py monitor_pantelimon.py
git add raport_transparenta.html stare_anterioara.json contracte.json monitor_pantelimon.py transparenta_pantelimon.html
git commit -m "Raport actualizat $(date +%d.%m.%Y)"
git push origin main
```

### Atenție Python versiune:
- Scriptul folosește f-string syntax compatibil cu **Python 3.10+**
- Pe Windows rulează cu `py` (nu `python3`)
- Nu rula din sandbox Linux — face request-uri de rețea care expiră

---

## Ce face monitor_pantelimon.py

1. **Fetch date buget** din transparenta.eu (ANAF/MF) pentru CUI 4420759
2. **Fetch contracte** din data.gov.ro (export oficial SEAP trimestrial, fișiere .xlsx)
3. **Analizează HCL-uri** (Hotărâri Consiliu Local) de pe site-ul primăriei
4. **Detectează red flags** — algoritmi de detectare a neregulilor:
  - Algoritm 1: Achiziții directe aproape de pragul categoriei (>97%)
  - Algoritm 1b: Achiziție directă individuală peste pragul categoriei → flag CRITIC
   - Algoritm 2: Furnizor monopol (singur ofertant repetat)
   - Algoritm 3: Fragmentare artificială (același furnizor, contracte similare, sumă combinată > prag)
   - Algoritm 4: Contracte fără licitație (achiziție directă pentru valori mari)
   - Algoritmi HCL: ședințe extraordinare excesive, hotărâri fără transparență
5. **Generează raport HTML** cu:
   - Statistici generale (nr. flags, nr. contracte, valoare totală)
   - Lista flags sortată după severitate (CRITIC → MAJOR → MEDIU)
   - Tabel contracte (primele 20)
   - Grafice Chart.js (buget pe categorii, evoluție, distribuție proceduri)
   - **Buton PDF/Print** (🖨️ Salvează ca PDF / Tipărește) — deschide toate detaliile și apelează window.print()
   - **Buton SEAP** per flag — link direct la contractul specific în e-licitatie.ro

---

## Modificări recente importante (sesiunile anterioare)

### Pipeline date financiare ANAF (sesiunile recente 2026-05)

**Fișiere noi adăugate:**
- `import_financiar_datagov.py` — descarcă streaming din data.gov.ro fișierele ANAF situații financiare:
  - WEB_BL_BS_SL_AN2024.txt (~8MB, entități mari/medii/mici)
  - WEB_UU_AN2024.txt (~73MB, entități mici/micro)
  - WEB_ONG_AN2024.txt (~7MB, NGO-uri) — pentru ASOCIATII
  - WEB_IP_IEME2024.txt (instituții publice)
  - Opțiuni CLI: `--an 2024`, `--an 2024-uu`, `--an 2024-ong`, `--merge`
- `enricheaza_firme.py` — enrichment HTML raport cu date financiare:
  - Pas 2a: Normalizează CUI-uri malformate ('ro 27019056' → '27019056')
  - Pas 2b: Cross-reference CUI din `firme_geocoded.json`
  - Pas 2b.5: Cross-reference CUI din `contracte.json` (+31 CUI-uri)
  - Pas 2c: Merge `firme_financiar.json` → flaguri financiare în HTML
  - Funcție helper `_norm_cui()`: strip prefix RO case-insensitive
- `firme_financiar.json` — output import, comis în repo:
  - 83 firme cu date ANAF 2024 (CA netă, nr. mediu salariați)
  - Cheile = CUI string, valorile = {an, cifra_afaceri, nr_salariati}
- `AUDIT_PRIVAT.md` — analiză privată top-risk (gitignored via AUDIT_PRIVAT*.md)

**Stare curentă date financiare (2026-05-29):**
- CUI populate: 90/93 firme (3 lipsă: Consiliul Local, Multiple, AUTO MARCU'S)
- Date financiare ANAF: 83/90 firme
- Chip zero-sal (≤2 angajați): 24 firme
- Chip zero-ca (CA << contract): 2 firme  
- Chip ca-sub (CA sub 50%): 4 firme
- Chip any-risk: 93 firme

**Workflow actualizare anuală (după publicare ANAF ~mai/iulie):**
```bash
python import_financiar_datagov.py --an 2025
python import_financiar_datagov.py --an 2025-uu --merge
python import_financiar_datagov.py --an 2025-ong --merge
python enricheaza_firme.py --no-mfinante
git add firme_financiar.json raport_transparenta.html enricheaza_firme.py
git commit -m "Date financiare ANAF 2025 integrate"
```

**mfinante.gov.ro**: URL-ul static căzut în mai 2026 (SPA, blochează bots). 
Înlocuit cu pipeline data.gov.ro. `--no-mfinante` este standard acum.

**CI auto-refresh** (`update-report.yml`): dacă `firme_financiar.json` e mai vechi de 180 zile
(verificat via `git log`), CI re-descarcă WEB_BL + WEB_UU automat.

### Flag nou: ACHIZITIE_DIRECTA_PESTE_PRAG
- Adăugat **Algoritm 1b** care detectează când un singur contract depășește pragul aplicabil categoriei: 270.120 RON fără TVA pentru produse/servicii sau 900.400 RON fără TVA pentru lucrări
- Anterior existau doar flags pentru valoare combinată (fragmentare) — acum și pentru contract individual
- Locație în cod: funcția `analizeaza_red_flags()`, imediat înainte de Algoritm 2

### Fix buton SEAP
- Anterior linkul ducea la pagina generică de list (`/list/0/0`) — apărea blank
- Acum extrage ID-ul numeric din `contract_id` (ex: `achizitie-directa-2025-489392` → `489392`)
- Construiește URL direct: `https://e-licitatie.ro/pub/notices/da-direct-acquisition/view/489392`
- Funcție helper: `_seap_url(contract_id)` — definită înainte de `_fmt_ron`

### Fix grafice Chart.js (transparenta_pantelimon.html)
- Canvas-urile nu aveau înălțime explicită → Chart.js 4.x nu randiza nimic
- Fix: `min-height: 280px` pe canvas, `maintainAspectRatio: false` în opțiunile chart-ului
- Înălțimi explicite pe fiecare canvas: `style="height:320px"` etc.

### Export PDF
- Adăugat buton galben în header-ul raportului: "🖨️ Salvează ca PDF / Tipărește"
- CSS `@media print` ascunde elementele interactive (`.no-print`) și afișează toate detaliile flag-urilor
- Funcție JS `printRaport()` — deschide toate `.flag-detail`, ascunde `.flag-arrow`, apelează `window.print()`
- Pentru a salva ca PDF: din dialogul de print alege "Salvare ca PDF" / "Save as PDF"

### risc_firma.py — modul detector shell companies (PR #20, #21, #22)

**PR #20** — `risc_firma.py` + `tests/test_risc_firma.py` (20 teste unitare, 0 rețea)

- `fetch_firma_anaf(cif)` — scrape mfinante.gov.ro, User-Agent bot, rate limit 1.2s, cache SQLite TTL 30 zile
- `evaluate_shell_risk(firma_data, contract_date, contract_value)` → indicatori factuali:
  - `CIFRA_AFACERI_ZERO` / CRITIC — CA = 0 RON în anul anterior contractului
  - `CIFRA_AFACERI_MULT_SUB_CONTRACT` / MAJOR — CA < 10% din valoarea contractului
  - `CIFRA_AFACERI_SUB_CONTRACT` / MEDIU — CA < 50% din valoarea contractului
  - `ZERO_ANGAJATI` / MAJOR — 0 angajați declarați la ANAF
  - `FOARTE_PUTINI_ANGAJATI` / MEDIU — 1-2 angajați
- `get_risk_panel_html(cif, firma_data, contract_date, contract_value)` → bloc HTML

**PR #21** — Integrare în `monitor_pantelimon.py`

- Import opțional cu try/except — monitor funcționează și fără risc_firma
- Pre-fetch pentru toți furnizorii unici înainte de loop (evită request-uri inutile)
- Panel HTML injectat în secțiunea `flag-detail` a fiecărui card de nereguă
- Atribut `data-supplier-cif` adăugat pe `.tp-flag` pentru enhance.js

**PR #22** — Faza 5-J: filtre shell company în `enhance.js`

- Rând nou de chips în toolbar (afișat doar dacă raportul conține panele): `👥 0 angajați` | `📉 CA = 0 RON` | `⚠️ Orice risc`
- `state.shellFilter` exclusiv; degradare graceful fără panele
- items[] îmbogățiți cu `riskCount` + `riskText` din `.supplier-risk-panel`

### PR #24 — Sitemap dinamic + mențiuni presă pe paginile furnizori

**`genereaza_sitemap(index_furnizori)`** — funcție nouă în `monitor_pantelimon.py`:
- Scrie `sitemap.xml` la fiecare rulare a monitorului
- 6 URL-uri statice (homepage, raport, transparenta, despre, presa, furnizori/index) + toate `furnizori/{slug}.html`
- Fiecare `<url>` conține `<lastmod>` (data rulării), `<changefreq>`, `<priority>` (0.5 pentru furnizori)
- Furnizori sortați A-Z după slug

**`genereaza_pagina_furnizor(..., mentiuni=None)`** — param nou:
- Citit din `mentiuni_media.json` (cheile non-`_`, curatoriale, adăugate MANUAL)
- Secțiunea `📰 Mențiuni în presă (N)` apare pe pagina firmei dacă există intrări
- Fiecare mențiune: link titlu, 🗞️ outlet, 📅 dată, rezumat (XSS escape corect)
- `mentiuni=None` sau `mentiuni=[]` → nicio secțiune (graceful)

**`main()`**:
- Încarcă `mentiuni_media.json` la start (FileNotFoundError silențios, alte erori → WARN)
- Pasează `_mentiuni_media.get(firma, [])` la `genereaza_pagina_furnizor()`
- Apelează `genereaza_sitemap(index_furnizori)` + scrie `sitemap.xml` după generarea paginilor

**`tests/test_sitemap_mentiuni.py`** — 20 teste unitare noi (10 sitemap + 10 mentiuni), 0 network

---

### Faza 3 — Detectori batch 1 (PR #13, commit 40fee9e)

4 funcții pure de detecție adăugate înainte de `analizeaza_red_flags()`:

- **`detect_fragmentare_temporara(contracte, config)`** — §2.1: grupare (CUI, prefix 4 cuvinte), fereastră 90 zile, normalizare Rev.X; CRITIC dacă suma sub-prag > prag; acceptă schema internă și export
- **`detect_concentrare_furnizor(contracte, config)`** — §2.2: top-3 furnizori; MAJOR >60%, CRITIC >80%; minim 3 furnizori distincți
- **`detect_sedinte_extraordinare(statistici_hcl)`** — §2.6: funcție pură (refactorizat din `analizeaza_hcl()`); MAJOR >25%, CRITIC ≥40%; minim 3 ședințe
- **`detect_publicare_intarziata(contracte, zile_prag=11)`** — §2.7: zile lucrătoare cu `holidays.Romania()`; MEDIU 12-20, MAJOR 21-30, CRITIC >30; graceful no-op fără `data_atribuire`

Hooks integrate în `analizeaza_red_flags()` și `analizeaza_hcl()`.
20/20 teste în `tests/test_detectors.py`. `requirements.txt`: adăugat `holidays>=0.46`.

### Fix Python 3.10 compatibility
- Înlocuit nested f-strings (`f"""..."""` în alt `f"""..."""`) cu variabila `btn_firma` pre-computată
- Fișierul avea CRLF endings (Windows) — compatibil, nu schimba

---

## Praguri legale folosite (Legea 98/2016)

```python
  "prag_servicii_furnizare": 270_120,   # RON fără TVA — produse/servicii
  "prag_lucrari": 900_400,              # RON fără TVA — lucrări
"marja_fragmentare_pct": 0.97,        # dacă valoarea > 97% din prag = suspect
```

---

### PR #25 — OG image · GDPR · Petiție · Accesibilitate (§5.7 + §5.8 + §5.5 + §4.4)

**`genereaza_og_image(n_flags, n_critic, valoare_mil, scor, output)`** — funcție nouă în `monitor_pantelimon.py`:
- Generează `og-image.png` (1200×630) cu Pillow la fiecare rulare a monitorului
- Afișează: număr nereguli, critice, valoare totală mil. RON, scor transparență
- Font fallback Windows + Linux (calibri/arial → DejaVu/Liberation)
- `try/except ImportError` — monitor continuă și fără Pillow instalat
- `og-image.png` static (placeholder 47 flags) inclus în repo pentru preview imediat

**og:image meta tags** adăugate pe toate paginile: `transparenta_pantelimon.html`, `despre.html`, `presa.html`, `gdpr.html`, `petitie.html`; și în template-urile HTML din `monitor_pantelimon.py` (raport + furnizori).

**`gdpr.html`** — pagină completă de politică de confidențialitate:
- Tabel surse date (SEAP/ANAF/primărie/ONRC/mfinante) cu baza legală
- GDPR: interes legitim / informare (art. 6(1)(f)), libertatea de exprimare și informare, Legea 190/2018 și minimizarea datelor; vezi `gdpr.html`
- Declarație ne-colectare, hosting GitHub Pages, drepturi GDPR, contact ANSPDCP

**`petitie.html`** — pagină petiție cetățenească (§5.5):
- 4 revendicări concrete (motivații achiziții, registru contracte, declarații avere, dezbatere publică)
- Formular cu Formspree (endpoint configurat în `action=`): nume, email, localitate, mesaj, GDPR consent
- Contor semnături + progress bar față de obiectiv 500
- Honeypot anti-spam, mesaj de mulțumire la `?multumim=1`
- Baza legală: Art. 51-52 Constituție + Legea 233/2002

**Accesibilitate §4.4** în `enhance.js`:
- Skip-link `.tp-skip-link` (CSS + inject) — "Salt la conținut" vizibil la focus, transparent altfel
- `aria-hidden="true"` pe toate emoji-urile decorative din nav (nav brand, link-uri, dark toggle)
- `--tp-muted: #6b7280` → `#4b5563` (contrast WCAG AA: ~4.6:1 pe fond alb)
- `injectMainId()` — adaugă `id="main-content"` pe `.page-wrap` / `<main>` / primul sibling non-nav

**`genereaza_sitemap()`** extins: adăugate `gdpr.html`, `petitie.html`, `harta.html` → total 9 pagini statice.

### §2.5 Anomalie geografică (PR #23)

Detector nou `detect_geographic_anomaly(contracte, firme_openapi)`:
- Flag `GEOGRAFIE_ANORMALA` / MEDIU când servicii locale (curățenie, pază, salubrizare, deszăpezire etc.) sunt atribuite firmelor cu sediu în afara Ilfovului + județe limitrofe
- `_JUDETE_ADIACENTE_ILFOV = {IF, B, GR, CL, IL, PH, DB}` — 13 keywords locale
- Hooked în `analizeaza_red_flags()` — graceful (skip dacă firme_openapi e gol)
- `_get_actionariat_openapi()` extins cu câmpurile `judet` + `adresa`
- 16 teste unitare în `tests/test_geographic.py` — 16/16 pass

---

## Status git (la data generării acestui fișier)

- **Ultimul push reușit:** commit direct pe main — "fix(sw): bump cache la tp-v3 + test_pwa actualizat"
- **Branch main:** la zi după merge PR #20–46 + hotfix SW v3
- **Suite de teste:** 359 teste, 18 fișiere, 0 erori
- **De făcut:** run `fix_si_push.bat` pentru a regenera `raport_transparenta.html` cu toți detectori activi
- **Date financiare ANAF**: integrate (83/90 firme, `firme_financiar.json` comis în repo)
- **mfinante.gov.ro**: căzut din mai 2026 — înlocuit cu pipeline data.gov.ro

## Stare roadmap IMPROVEMENTS.md + AUDIT.md (la zi)

### ✅ Complet

| Faza | Item | PR/Status |
|---|---|---|
| Faza 1-G | SEO + OG tags + robots.txt + sitemap.xml | done |
| Faza 1-H | RSS/Atom feed.xml | generat de monitor |
| Faza 1-I | Banner „ce e nou" (delta.json + enhance.js) | done |
| Faza 2-A | Markup semantic `.tp-flag[data-severity]` | PR #18 |
| Faza 2-B | JSON embedded `<script id="tp-data">` + raport.json | done |
| Faza 3-D | Pagini per furnizor (47 pagini `furnizori/`) | done |
| Faza 3-E | Scor transparență + widget | done |
| §2.1 | Valori identice aceeași zi | PR #13 |
| §2.2 | Burst detection + concentrare furnizor | PR #13 |
| §2.3 | Shell company detector (`risc_firma.py`) | PR #20–22 |
| §2.5 | Anomalie geografică | PR #23 |
| §2.6 | Valori rotunde suspecte | Algoritm 8 |
| §2.7 | Publicare întârziată + semnare zile nelucrătoare | PR #13 |
| §2.8 | CA sub valoarea contractului | risc_firma.py |
| §4.1 | Widget reconciliere ANAF ↔ SEAP | done |
| §4.2 | Dark mode toggle | enhance.js |
| §5.1 | Pagină jurnaliști (presa.html + API.md) | PR #19 |
| Faza 5-J | Filtre shell company în toolbar | PR #22 |
| Sitemap dinamic | sitemap.xml regenerat la fiecare rulare cu furnizori | PR #24 |
| Mențiuni presă | `mentiuni_media.json` → secțiune 📰 pe paginile furnizori | PR #24 |
| §5.7 OG image | `genereaza_og_image()` → og-image.png 1200×630 cu Pillow | PR #25 |
| §5.8 GDPR | `gdpr.html` — politică de confidențialitate completă | PR #25 |
| §5.5 Petiție | `petitie.html` — formular cetățenesc cu Formspree | PR #25 |
| §4.4 Accesibilitate | skip-link, aria-hidden emojis, contrast fix, main landmark | PR #25 |
| Nav + cross-linking | petitie.html în nav; CTA petiție în index/transparenta; gdpr în footere | PR #26 |
| §4.5 Core Web Vitals | `loading="lazy"` automat pe imagini (enhance.js); og:image pe index.html | PR #27 |
| §6.5 Audit secrete | git log grep — 0 secrete hardcodate găsite în istoricul repo | PR #27 |
| §4.6 Hartă Leaflet | `harta.html` — hartă interactivă furnizori cu circle markers Leaflet.js | PR #28 |
| §3.6 Geocodare | `geocodeaza_firme()` + SQLite cache 180z + Nominatim → `firme_geocoded.json` | PR #28 |
| §3.1 Curtea de Conturi | `fetch_curtea_de_conturi()` + SQLite cache + `curtea_de_conturi.json` | PR #29 |
| §3.2 ANI declarații avere | `fetch_declaratii_avere()` + SQLite cache + `ani_declaratii.json` | PR #29 |
| §3.4 TED Europa | `search_ted_for_buyer()` + SQLite cache 7z + `ted_notices.json` | PR #30 |
| §3.5 MOL primărie | `fetch_mol_primarie()` + SQLite cache 7z + `mol_primarie.json` | PR #30 |
| §4.2 Dark mode toggle | Buton + localStorage + prefers-color-scheme (deja în enhance.js) | PR #30 |
| §5.1 Press kit auto-generat | `genereaza_press_kit()` → `press_kit.json` + `press_kit.md`; `presa.html` descărcare `.md` + `loadPressKitJson()` | PR #31 |
| Docs README | Test count 37→153, tabel 19 algoritmi, tabel surse externe, structura repo completă | PR #32 |
| Repo hygiene | `.gitignore` extins (*.bat, scripturi locale, 201.html); `AUDIT.md` + `config.json.template` adăugate | PR #33 |
| §4.3 Service Worker PWA | `sw.js` Cache-First/Network-First + `manifest.webmanifest` + icons 192/512 + `initPWA()` în enhance.js | PR #34 |
| §3.3 PNRR tracking | `fetch_pnrr_projects()` + SQLite cache + `pnrr_projects.json`; JSON API + HTML fallback | PR #34 |
| Faza 4-F CLI multi-UAT | `monitor_uat.py` wrapper CLI — orice UAT românesc cu `--judet`, `--uat-search`, `--dry-run` | PR #35 |
| CSV export + teste feed | `genereaza_contracte_csv()` → `contracte.csv`; link CSV în presa.html; 13 teste CSV + 13 teste feed Atom | PR #36 |
| API.md extins | Documentate 8 endpoint-uri noi: contracte.csv, press_kit.json, pnrr_projects.json, ani_declaratii.json, curtea_de_conturi.json, ted_notices.json, mol_primarie.json, firme_geocoded.json | PR #37 |
| README.md la zi | 153→216 teste, 10→14 fisiere test, repo struct cu monitor_uat.py/sw.js/csv, PNRR in surse | PR #38 |
| sw.js CSV cache | `/contracte.csv` în DATA_URLS; `networkFirstCsv()` cu fallback CSV; CACHE_STATIC bump v2; 3 teste noi | PR #39 |
| Teste state/analytics | 46 teste noi: `incarca_stare_anterioara`, `salveaza_stare`, `detecteaza_flags_noi`, `calculeaza_analiza_per_tip`, `_slugify`, `_detect_flag_simple`, `render_contracte_tbody_rows` | PR #40 |
| Teste og_image + index furnizori | 20 teste noi: `genereaza_og_image` (PNG 1200×630, Pillow mock, cale invalida) + `genereaza_index_furnizori` (sortare A-Z, linkuri, flags, canonical) | PR #41 |
| Teste funcții utilitare | 45 teste noi: `_seap_url`, `_fmt_ron`, `_format_kpi`, `_similaritate_titlu`, `_termene_url`, `_incarca_cache_firme`, `_salveaza_cache_firme`, `_fmt_actionariat`, `_fmt_reprezentanti` | PR #42 |
| Teste scor transparență | 29 teste noi: `calculeaza_scor_transparenta` — structură, interval 0-100, toate subscorurile (achizitii, ofertant, sedinte, fragmentare), valori hardcodate, ponderi | PR #43 |
| README la zi | 216→359 teste, 14→18 fișiere, 4 fisiere noi adaugate la lista | PR #44 |
| CI coverage | `pytest-cov` în CI; branch triggers extinse (docs/**, chore/**, fix/**); coverage report ca artifact | PR #45 |
| Fix JS toggleFlag | Șters `}` orfan din `<script>` inline → SyntaxError bloca `toggleFlag`, `openFirmaPanel`, `_getContracte` etc. Fix în template + fișier generat | PR #46 |
| Fix shell filter chips | BUG-6: `enhance.js` citea `.supplier-risk-panel` (neexistent) → `#tp-shell-row` ascuns, `any-risk` returna 0/299. Fix: citește `scor` din `#risc-firma-data` JSON | PR #47 |
| Fix harta Leaflet SRI | BUG-7: SRI hash greșit pentru `leaflet.js` → browserul refuza execuția → hartă goală pentru toți userii. Fix: hash actualizat | direct main |
| Geocodare 181 firme | firme_geocoded.json era `[]` — geocodat via ANAF v9 (gratuit) + Nominatim. Harta arată acum 181 markere, 506 contracte, 313.68M RON | commit c3d83bf |
| Fix ANAF URL v8→v9 | `webservicesp.anaf.ro/PlatitorTvaRest/api/v8/ws/tva` returnează 404. URL nou: `/api/PlatitorTvaRest/v9/tva`. CUI e în `date_generale.cui` (nu top-level) | commit c3d83bf |

### ❌ Nu e posibil / Nu ataca fără discuție

| Item | Motiv |
|---|---|
| §2.4 Repeat-loser pattern | Necesită date toți ofertanți — SEAP exportă doar câștigător |
| §2.9 / Faza 5-K Network analysis | ~2-4 săptămâni, scraping termene.ro + NetworkX + Cytoscape |
| §6.1 Refactor modular | ~2-4 zile, major undertaking |
| §5.6 Newsletter | Necesită cont extern (Substack/Mailchimp) — nu automatizabil |
| §6.4 Branch protection | Necesită 2FA activat — nu se poate face programatic |

---

## Monitoring uptime

Verificare că site-ul funcționează non-stop. Setup manual cu UptimeRobot (gratuit, fără cod):

**Pași:**
1. Creează cont la [uptimerobot.com](https://uptimerobot.com) (plan Free — 50 monitoare, interval 5 min)
2. Add Monitor → **HTTPS Keyword** pe `https://transparenta-pantelimon.eu` — keyword: `Raport Transparență`
   - Detectează și că pagina conține datele reale (nu doar că serverul răspunde)
3. Add Monitor → **HTTPS** pe `https://transparenta-pantelimon.eu/raport_transparenta.html` — check HTTP status 200
4. Configurează alertă email la adresa ta privată (nu cea publică)
5. Opțional: Add Monitor → **HTTPS** pe `https://transparenta-pantelimon.eu/feed.xml` (RSS functional)

**Badge status** (adaugă în README.md după ce ai URL-ul public al monitorului):
```markdown
[![Uptime](https://img.shields.io/uptimerobot/ratio/mXXXXXXXXX)](https://stats.uptimerobot.com/XXXXX)
```
Înlocuiește `mXXXXXXXXX` cu monitor ID-ul din dashboard UptimeRobot.

---

## Instituții la care pot fi depuse sesizări (context civic)

Neregulile detectate de monitor pot fi sesizate la:
- **Curtea de Conturi** — control financiar, achiziții publice (curteadeconturi.ro)
- **ANAP** — Agenția Națională Achiziții Publice (anap.gov.ro) — specific achiziții
- **ANI** — Agenția Națională de Integritate — conflict de interese
- **DNA** — pentru fapte penale (corupție, frauda fonduri publice)
- **Prefectura Ilfov** — control legalitate acte administrative locale
- **Consiliul Județean Ilfov** — tutela administrativă

---

## Cache TTL policy

Toate duratele de valabilitate (TTL) ale cache-urilor sunt centralizate în
**`config.py`** (nu magic numbers împrăștiate în fiecare script). Valorile au
fost ajustate pe baza cadenței reale de publicare a fiecărei surse:

| Sursă | Constantă | TTL | Justificare |
|---|---|---|---|
| mfinante.gov.ro (`risc_firma.py`) | `TTL_MFINANTE_DAYS` | 30 zile | Situații financiare anuale — neschimbat |
| SEAP contracte (`fetch_contracts_seap`) | `TTL_SEAP_CONTRACTE_DAYS` | 7 zile | Export trimestrial data.gov.ro (fișiere XLSX 10-50MB) — nu are rost re-descărcat la fiecare rulare zilnică |
| HCL primărie (`fetch_hcl_metadata`) | `TTL_HCL_DAYS` | 7 zile | Pagina de hotărâri se actualizează la fiecare ședință CL, nu zilnic |
| Curtea de Conturi (`fetch_curtea_de_conturi`) | `TTL_CURTEA_CONTURI_DAYS` | 90 zile | Rapoartele de audit apar de regulă anual |
| ANI declarații avere (`fetch_declaratii_avere`) | `TTL_ANI_DAYS` | 30 zile | Declarații actualizate anual/la depunere — neschimbat |
| TED Europa (`search_ted_for_buyer`) | `TTL_TED_DAYS` | 7 zile | Anunțuri publicate zilnic — neschimbat |
| MOL primărie (`fetch_mol_primarie`) | `TTL_MOL_DAYS` | 14 zile | Rectificări bugetare/HCL publicate la fiecare ședință CL (cadență ~bilunară) |
| PNRR (`fetch_pnrr_projects`) | `TTL_PNRR_DAYS` | 7 zile | Proiecte actualizate ocazional — neschimbat |
| ONRC reprezentanți legali (`_get_reprezentanti_onrc`) | `TTL_ONRC_DAYS` | 30 zile | Administratori/reprezentanți se schimbă rar — neschimbat |
| Nominatim / OSM (geocodare) | `TTL_NOMINATIM_DAYS` | 365 zile | Sediile fiscale se mută foarte rar |
| ANAF v9 (înregistrare TVA) | `TTL_ANAF_V9_DAYS` | 365 zile | Starea de înregistrare TVA se schimbă rar (radiere/suspendare) — API gratuit, nu trebuie suprasolicitat |
| data.gov.ro CSV (`import_financiar_datagov.py`, situații financiare) | `TTL_FIRME_FINANCIAR_REFRESH_DAYS` | 365 zile | Situații financiare ANAF publicate anual (mai-iulie); prag citit din `config.py` de `.github/workflows/update-report.yml` |
| Google News + Context.ro (`monitorizare_presa.py`) | `TTL_PRESA_DAYS` | 7 zile | Mențiuni presă, conținut dinamic — neschimbat |

Sursele fără cache anterior (SEAP contracte, HCL, ANAF v9) au primit acum
cache SQLite/JSON dedicat, pentru a evita re-descărcarea acelorași date la
fiecare rulare a cron-ului lunar (`update-report.yml`).

---

## Dependențe Python

```
requests
beautifulsoup4
openpyxl
PyMuPDF (fitz)     # OCR PDF-uri digitale
pytesseract        # OCR PDF-uri scanate
Pillow
```

Instalare: `pip install -r requirements.txt`
