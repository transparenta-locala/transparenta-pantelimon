# Bug-uri cunoscute (descoperite in Faza 2)

Documentate pe 25 mai 2026. BUG-1, BUG-2, BUG-3 rezolvate in Faza 2.5.  
BUG-5, BUG-6, BUG-7 rezolvate în PR-urile #46/#47.  
BUG-8..BUG-13 descoperite pe 03 iun 2026 (audit `AUDIT_BUGS_03iun.md`), rezolvate în PR `fix/bug-major-kpi-dynamic` (BUG-8/9/11) și PR `fix/bug-minor-polish` (BUG-10/12/13).

---

## ~~BUG-1: 4,2M RON hardcodat in `transparenta_pantelimon.html` (3 locatii)~~ ✅ REZOLVAT in Faza 2.5

**Rezolvat prin:** functia `actualizeaza_kpi_seap()` in `monitor_pantelimon.py`  
**Mecanism:** regex replace pe cele 3 locatii; injecteaza `data-an` si `data-total-ron` ca sursa unica de adevar  
**Commit:** `fix(kpi): BUG-1 + BUG-2 — KPI consistent cu widget reconciliere`

### Descriere originala

KPI-ul "Valoare totala contracte 2025" era hardcodat static ca `4.200.000 RON` in trei locatii:

```html
<!-- BUG-1a: fallback static KPI (acum: data-total-ron + _format_kpi) -->
<span class="val" id="kpi-val-total">4,2M RON</span>

<!-- BUG-1b: text hardcodat in tabel comparativ (acum: an curent + suma dedupata) -->
<strong>💰 Valoare totala contracte 2025 — 4.200.000 RON</strong>

<!-- BUG-1c: rand in tabelul de reconciliere manual (acum: an curent + suma dedupata) -->
<tr><td>Valoare totala contracte 2025</td><td>4.200.000 RON</td>...</tr>
```

---

## ~~BUG-2: `_renderKpi(data)` sumeaza toate contractele fara filtru de an~~ ✅ REZOLVAT in Faza 2.5

**Rezolvat prin:** `_renderKpi()` citeste `data-total-ron` din elementul `#kpi-val-total`  
**Fallback:** filtru pe `data-an` daca atributul lipseste  
**Commit:** `fix(kpi): BUG-1 + BUG-2 — KPI consistent cu widget reconciliere`

### Descriere originala

```javascript
// Vechi: sumeaza TOATE contractele din contracte.json, indiferent de an
const total = data.reduce(function(s,c){ return s+c.valoare; }, 0);
```

`contracte.json` contine contracte din mai multi ani. Suma rezultata era
~313M RON (toti anii) in loc de valoarea anului curent (dupa dedup).

---

## ~~BUG-3: Inconsistenta NoJS vs JS — utilizatorul vede cifre diferite~~ ✅ REZOLVAT in Faza 2.5

**Rezolvat prin:** BUG-1 + BUG-2 rezolvate → sursa unica de adevar `data-total-ron`  
**Commit:** `fix(kpi): BUG-1 + BUG-2 — KPI consistent cu widget reconciliere`

### Descriere originala

Starea fara JS: KPI = `4,2M RON` (hardcodat, BUG-1)  
Starea cu JS incarcat: KPI = `313M RON` (suma multi-anuala, BUG-2)  
Widget reconciliere (raport): `257M RON` (2025, dedupat)

Trei cifre diferite pe doua pagini pentru acelasi concept.

---

## ~~BUG-5: `toggleFlag` / `openFirmaPanel` nedefinite — SyntaxError JS~~ ✅ REZOLVAT în PR #46

**Rezolvat prin:** șters `}}` orfan din template-ul Python (`monitor_pantelimon.py` linia ~4318) și `}` din `raport_transparenta.html`  
**Commit:** `fix(js): inlatura } orfan care bloca toggleFlag si openFirmaPanel`

### Descriere originală

Un `}` extra la finalul blocului `<script>` inline în `raport_transparenta.html` cauza un **SyntaxError JavaScript** la parsare. Întreg scriptul (13 688 chars) nu executa deloc — funcțiile nu erau definite în global scope:

- `toggleFlag()` — clic pe „▼ detalii" nu producea niciun efect vizibil
- `openFirmaPanel()` — badge RISC (ex: „⚠️ RISC 46") nu deschidea panoul firmei
- `_getContracte()`, `_getRisc()`, `closeFirmaPanel()`, `showFirmaContracts()` — toate nedefinite

`printRaport` funcționa *aparent* corect deoarece `enhance.js` îl exporta explicit via `window.printRaport = printRaport` — mascând simptomele.

**Cauza:** `}}` orfan în template Python, reziduu dintr-un refactoring care a eliminat un IIFE wrapper (`(function() { ... })()`) dar a lăsat `}}` de închidere în urmă.

---

## BUG-4: Rev.2 dubleaza valoarea contractelor in SEAP (problema upstream)

**Severitate:** INFO — sursa: SEAP, nu codul nostru  
**Impact:** Inflatie artificiala a sumei brute din `contracte.json`  
**Status:** Partial mitigat prin `_suma_seap_dedupata()` in Faza 2. Nu se poate rezolva complet
fara acces la schema completa SEAP (data_start/data_sfarsit).

### Descriere

SEAP republica valoarea INTREAGA a unui contract la fiecare modificare (act aditional = Rev.X).
Din 417 contracte 2025 in `contracte.json`:
- 381 au `Rev.2` in titlu (91%) → suma bruta: 269M RON
- 36 nu au Rev.X → suma: 185K RON

Dupa deduplicare canonica (`_suma_seap_dedupata`): 242 contracte unice, 257M RON.

Ramane o discrepanta (257M > 146M ANAF) probabila din cauza contractelor multi-anuale.

---

## ~~BUG-7: Harta furnizori complet nefuncțională — SRI hash greșit pentru leaflet.js~~ ✅ REZOLVAT direct în main

**Rezolvat prin:** actualizat `integrity` hash în `harta.html`  
**Commit:** `fix(harta): BUG-7 — SRI hash incorect pentru leaflet.js`

### Descriere

Hash-ul SRI al `leaflet@1.9.4/dist/leaflet.js` de pe `unpkg.com` nu mai corespundea cu fișierul actual (CDN actualizat upstream). Browserul refuza să execute scriptul → `window.L` undefined → `L.map()` aruncă `ReferenceError` → harta goală pentru toți utilizatorii.

- Hash greșit: `sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV/**XN/WLs**=`
- Hash corect: `sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV**1lvTlZBo**=`
- CSS integrity era corect (nemodificat)

---

## ~~BUG-6: Shell filter chips (⚠️ Orice risc, 👥 0 angajați, 📉 CA=0) — rând ascuns, riskCount=0 pentru toți~~ ✅ REZOLVAT în PR #47

**Rezolvat prin:** enhance.js citește acum `#risc-firma-data` JSON pentru `riskCount` (câmpul `scor`) în loc de `.supplier-risk-panel` care nu există în HTML-ul curent.  
**Commit:** `fix(filter): BUG-6 — shell chips citesc risc din #risc-firma-data`

### Descriere originală

`enhance.js` linia ~707 căuta `.supplier-risk-panel[data-risk-count]` în fiecare card. Aceste elemente **nu sunt generate** de `monitor_pantelimon.py` în versiunea curentă. Rezultat:
- `shellPanelsFound = 0` → `#tp-shell-row { display: none }` (rândul de chip-uri shell era **complet ascuns**)
- `riskCount = 0` pentru toți cei 299 itemi → filtrul `any-risk` returna 0/299

### Starea după fix

- Sursă: `#risc-firma-data` JSON (93 firme, toate cu `scor > 0`)  
- `any-risk` chip: afișează 299/299 (toți furnizorii flagați au scor risc > 0 — corect)
- `zero-sal` / `zero-ca`: afișează 0/299 — date ANAF/ONRC (angajați, cifra afaceri) **nu sunt încă populate** în `risc-firma-data.onrc`/`.openapi`; chips sunt vizibile dar fără date relevante deocamdată

---

## ~~BUG-8: Label KPI an hardcodat ("2025" deși data-an="2026")~~ ✅ REZOLVAT în `fix/bug-major-kpi-dynamic`

**Fișier:** `transparenta_pantelimon.html` linia ~1159  
**Rezolvat prin:** regex nou în `actualizeaza_kpi_seap()` pentru `Valoare contracte atribuite \d{4}`

---

## ~~BUG-9: Detail-grid KPI stale (4.2M RON 2025 ≠ 12.3M RON 2026)~~ ✅ REZOLVAT în `fix/bug-major-kpi-dynamic`

**Fișier:** `transparenta_pantelimon.html` liniile ~1191-1194  
**Rezolvat prin:** nouă funcție `_categorizeaza_contracte_breakdown()` + 4 regex în `actualizeaza_kpi_seap()`.  
**Teste:** 18 teste noi în `tests/test_kpi_breakdown.py`

---

## ~~BUG-10: "506 contracte · 2025" hardcodat în 5 locații~~ ✅ REZOLVAT în `fix/bug-minor-polish`

**Fișier:** `transparenta_pantelimon.html` (5 locații)  
**Rezolvat prin:** elemente înlocuite cu `<span id="tp-nr-*">` și `<span id="tp-an-*">`;  
funcție nouă `actualizeaza_contoare_analiza()` apelată din `main()`.

---

## ~~BUG-11: index.html "216 nereguli / 2 CRITICE" hardcodat~~ ✅ REZOLVAT în `fix/bug-major-kpi-dynamic`

**Fișier:** `index.html` liniile ~229, 241, 349  
**Rezolvat prin:** blocul JS existent extins cu `_upd()` pentru 5 elemente din `raport.json`.  
**Fallback NoJS:** actualizat la valorile curente (299 / 107 CRITIC).

---

## ~~BUG-12: despre.html "17 algoritmi" în loc de 19~~ ✅ REZOLVAT în `fix/bug-minor-polish`

**Fișier:** `despre.html` linia ~160  
**Rezolvat prin:** înlocuire manuală 17→19.

---

## ~~BUG-13: 201.html — dead code cu URL-uri bise88 stale~~ ✅ REZOLVAT în `fix/bug-minor-polish`

**Fișier:** `201.html`  
**Rezolvat prin:** fișier șters (nu era tracked de git, zero referințe în proiect).

---

## ~~BUG-14: căutarea nu găsea firme care există în date~~ ✅ REZOLVAT 04.08.2026

**Raportat de utilizator:** căutarea `DAV GARDEN&SERVICE SRL` returna 0 rezultate,
deși firma are 3 contracte și 2 red flags în raport.

**Cauză:** potrivire de subșir brută, fără normalizare. În `loadDataFromJson()`
haystack-ul se construia din `raport.json` **fără** `.replace(/\s+/g,' ')`, spre
deosebire de căile de fallback DOM. Datele SEAP conțin nume „murdare": firma apare
ca `DAV  GARDEN & SERVICE` (două spații, fără sufix juridic). Efect măsurat pe
datele reale: `dav garden` → 0 rezultate; doar `dav  garden` (două spații) mergea.

**Rezolvat prin:**
- `nzText()` / `nzCore()` în `enhance.js` — lowercase, fără diacritice, `&`→`and`,
  abrevieri punctate (`S.R.L.`→`srl`), punctuația devine spațiu, sufixe juridice ignorate
- potrivire AND pe tokenuri (ordinea cuvintelor nu mai contează)
- `normalizeaza_nume_firma()` / `nume_firma_esential()` în `monitor_pantelimon.py`
  (aceeași logică, testabilă; lista de sufixe e verificată că e identică în ambele)
- stare goală cu sugestii „ai vrut să spui" în loc de „🤷 Niciun rezultat"

**Verificare:** toți cei 94 de furnizori sunt găsibili după numele propriu ȘI după
varianta cu „SRL" adăugat (188/188). Teste: `tests/test_cautare_firme.py`.

---

## ~~BUG-15: căutarea după CUI nu returna nimic~~ ✅ REZOLVAT 04.08.2026

**Cauză:** 0 din 304 flag-uri aveau `supplier_cif` — exportul SEAP nu pune CUI-ul
pe anunț, iar `raport.json` prelua direct câmpul gol.

**Rezolvat prin:** index `_cui_by_supplier` construit din `contracte` +
`firme_geocoded.json`, propagat în `raport.json` și în `risc-firma-data`.
Acoperire: **300/304** flag-uri, 92/94 furnizori (lipsesc doar „Consiliul Local" și „Multiple").

---

## ~~BUG-16: profilul de firmă — acuzații fără justificare, cifre umflate~~ ✅ REZOLVAT 04.08.2026

Confirmat în `AUDIT_transparenta-pantelimon_01iul2026.md` (P1–P5).

| Problemă | Cauză | Fix |
|---|---|---|
| Nereguli fără explicație | `risc-firma-data` nu conținea `descriere` | câmp adăugat, randat în panou |
| Rândurile arătau ca butoane, dar nu răspundeau | erau `<div>` fără handler | `<a href="#nereguli-N">` spre neregula detaliată |
| „Valoare totală expusă" umflată (Constopograf: 16.74 mil. vs 1.89 mil. real) | se afișa suma tuturor semnalelor; un contract generează 3-4 semnale | se afișează suma contractelor distincte; suma semnalelor rămâne ca linie secundară, etichetată |
| Badge-uri desincronizate de listă | contoare calculate în paralel cu lista | contoarele se calculează DIN listă (0/94 firme desincronizate acum) |
| Buton SEAP → pagină goală | URL generic `/list/0/0` | anunț direct pe `contract_id`, altfel căutare după numele firmei |
| Valoarea firmei dublată | exporturile trimestriale repetă același contract cu id-uri diferite | deduplicare pe (firmă, dată, valoare, obiect) — afecta chiar DAV GARDEN (4.62 mil. numărați de două ori) |

---

## ~~BUG-17: filtrele de severitate aveau logică inversă~~ ✅ REZOLVAT 04.08.2026

Click pe „🔴 CRITIC" **ascundea** criticele. Acum, din starea „toate pornite",
un click **izolează** severitatea aleasă; click-urile următoare adaugă/scot;
dacă nu mai rămâne niciuna, revine la toate.

---

## ~~BUG-18: `enhanceReport()` nu era idempotent~~ ✅ REZOLVAT 04.08.2026

La o a doua inițializare se injecta un al doilea toolbar, iar filtrele se aplicau
doar pe unul. Guard adăugat: `if (document.querySelector('.tp-toolbar')) return;`

---

## ⚠️ De reținut: `enhance.min.js` e fișierul servit în producție

`raport_transparenta.html` și paginile de furnizori încarcă `enhance.min.js`, nu
`enhance.js`. Nu există pas de build în CI, deci după orice modificare în sursă:

```bash
npx terser enhance.js --compress --mangle --comments "/^!/" -o enhance.min.js
```

`tests/test_cautare_firme.py::TestEnhanceJsSincronizat` prinde omisiunea.
