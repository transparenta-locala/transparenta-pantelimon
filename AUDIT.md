# Audit tehnic — transparenta-pantelimon

**Site:** https://transparenta-pantelimon.eu
**Repo:** https://github.com/transparenta-locala/transparenta-pantelimon
**Data:** 22 mai 2026
**Scop:** observații tehnice și propuneri de cod pentru îmbunătățirea instrumentului de monitorizare. Document complementar la `IMPROVEMENTS.md` (roadmap existent).

---

## 0. Sumar

**Starea actuală — ce e bine făcut:**

- `enhance.js` are arhitectură matură: progressive enhancement, fallback strategies, accessibility (`aria-pressed`, skip-links potențiale), print CSS, debounced filters, permalinks per card. Codul ăsta e mai matur decât 90% din site-urile civice românești.
- Conținut civic complet: ghidul „Ce poți face ca cetățean" cu 9 căi de sesizare (ANAP, Curte de Conturi, DNA, ANI, Avocatul Poporului, contencios) e impecabil ca pedagogie civică.
- Roadmap `IMPROVEMENTS.md` bine structurat pe 5 faze cu commit-uri sugerate și criterii de verificare.

**Probleme imediate (a se rezolva în prima săptămână):**

1. Bug vizibil pe live: tabelul de pe `transparenta_pantelimon.html` arată permanent „⏳ Se încarcă datele din SEAP..." (vezi §1.1).
2. Discrepanță numerică între pagini: index zice 147M RON cheltuieli / 506 contracte, tab „Achiziții" zice 4.2M RON contracte (vezi §1.2 — calcul de reconciliere automată).
3. Canonical URLs trimit la `bise88.github.io`, nu la `transparenta-pantelimon.eu` — Google indexează URL-ul vechi (vezi §1.3).
4. Lipsește `README.md` în repo (vezi §6.3).

**Propuneri cu cel mai mare impact tehnic:**

1. Detector automat pentru pattern-ul „valori identice pe firme diferite în aceeași zi" — §2.1
2. Widget de reconciliere ANAF↔SEAP — §1.2 + §4.1
3. Shell-company detector prin scraping `mfinante.gov.ro` (gratuit) — §2.3
4. Refactor modular al `monitor_pantelimon.py` (87KB într-un fișier) — §6.1
5. Comparator multi-UAT folosind aceeași bază de cod — §5.4

---

## 1. Bug-uri & inconsistențe

### 1.1 Tabelul SEAP nu se încarcă

**Unde:** `transparenta_pantelimon.html`, tab „Achiziții Publice", secțiunea „Contracte semnificative 2024–2025".

**Ce arată:**
```
| Obiect contract                 | Valoare | Tip procedură | Nr. ofertanți | ...
| ⏳ Se încarcă datele din SEAP... | | | | | |
```

**Diagnoză:** placeholder persistă — fie JS-ul de fetch lipsește, fie endpoint-ul a fost mutat. Restul tabelelor au date hard-coded sau renderate din JSON, doar acesta e gol.

**Fix minimal — generare statică în Python:**

```python
def render_top_contracts_table(contracts, top_n=20):
    sorted_ctr = sorted(contracts, key=lambda c: c.get('valoare', 0), reverse=True)[:top_n]
    rows = []
    for c in sorted_ctr:
        sev_icon = "🚩" if c.get('red_flags') else "✅"
        sev_class = "tp-row-flag" if c.get('red_flags') else ""
        rows.append(f"""
        <tr class="{sev_class}" data-flags="{len(c.get('red_flags', []))}">
          <td>{html.escape(c.get('obiect', '-')[:80])}</td>
          <td class="num">{c.get('valoare', 0):,.0f}</td>
          <td>{html.escape(c.get('procedura', '-'))}</td>
          <td class="num">{c.get('nr_ofertanti', '-')}</td>
          <td>{sev_icon} {len(c.get('red_flags', []))}</td>
          <td><a href="{c.get('seap_url', '#')}" target="_blank" rel="noopener">SEAP ↗</a></td>
        </tr>""")
    return f"""
    <table class="tp-contracts-table" data-total="{len(sorted_ctr)}">
      <thead><tr>
        <th>Obiect contract</th><th class="num">Valoare (RON)</th>
        <th>Tip procedură</th><th class="num">Nr. ofertanți</th>
        <th>Severitate</th><th>Sursă</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""
```

**Fix dinamic (mai bun):** mută datele într-un `<script type="application/json" id="contracts-data">…</script>` (vezi Faza 2-B din `IMPROVEMENTS.md`) și render în JS din `enhance.js`.

### 1.2 Discrepanța 147M vs 4.2M — necesită reconciliere automată

**Context:**

- Index: „147M RON Cheltuieli 2025" (sursa: ANAF/transparenta.eu)
- Pagina buget: „4,2M RON Valoare contracte atribuite 2025" (sursa: SEAP)
- „Tendințe": „136,9M RON Contracte suspecte într-o singură zi" (5 contracte pe 29.07 + 05.09.2025)

**Întrebarea calculabilă:** ce procent din cheltuielile primăriei e vizibil în SEAP? Și ce diferență rămâne neexplicată?

**Cod propus — secțiune nouă în `monitor_pantelimon.py`:**

```python
def reconciliere_buget_seap(buget_anaf, contracte_seap, an=2025):
    """
    Reconciliază cheltuielile ANAF cu contractele SEAP vizibile.
    Returnează dict cu sume + procent vizibilitate.
    """
    total_anaf = buget_anaf.get('cheltuieli_total', 0)
    total_seap = sum(c.get('valoare', 0) for c in contracte_seap
                     if str(an) in c.get('data', ''))

    # Estimare categorii non-SEAP (din execuția bugetară pe capitole)
    salarii_estimate = buget_anaf.get('cap_salarii', total_anaf * 0.45)  # ~45% tipic UAT
    transferuri = buget_anaf.get('cap_transferuri', total_anaf * 0.15)
    investitii = buget_anaf.get('cap_investitii', 0)

    gap = total_anaf - salarii_estimate - transferuri - total_seap
    procent_vizibil = (total_seap / total_anaf * 100) if total_anaf else 0

    return {
        'total_anaf_ron': total_anaf,
        'total_seap_ron': total_seap,
        'salarii_estimate_ron': salarii_estimate,
        'transferuri_ron': transferuri,
        'gap_neexplicat_ron': gap,
        'procent_vizibil_in_seap': round(procent_vizibil, 1),
        'an': an,
    }
```

**UI propus pe `index.html`:**

```html
<section class="tp-reconciliation">
  <h3>📊 Reconciliere ANAF ↔ SEAP</h3>
  <div class="tp-reco-grid">
    <div class="tp-reco-cell"><span>147M RON</span><small>Cheltuieli totale ANAF 2025</small></div>
    <div class="tp-reco-cell tp-reco-known"><span>~66M</span><small>Salarii estimate (~45%)</small></div>
    <div class="tp-reco-cell tp-reco-known"><span>~22M</span><small>Transferuri/subvenții (~15%)</small></div>
    <div class="tp-reco-cell tp-reco-visible"><span>4,2M</span><small>Vizibil în SEAP (2,9%)</small></div>
    <div class="tp-reco-cell tp-reco-gap"><span>~55M</span><small>GAP neexplicat (37%)</small></div>
  </div>
  <p class="tp-reco-note">
    Doar <strong>2,9%</strong> din cheltuielile primăriei sunt vizibile public în SEAP.
    Procentul rămas nu se regăsește nici în salarii, nici în transferuri,
    nici în contracte SEAP — un calcul derivat din date publice oficiale.
  </p>
</section>
```

CSS aferent:

```css
.tp-reco-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: .75rem;
  margin: 1rem 0;
}
.tp-reco-cell {
  padding: 1rem;
  border-radius: 8px;
  background: var(--tp-card-bg);
  border: 1px solid var(--tp-border);
  text-align: center;
}
.tp-reco-cell span { display: block; font-size: 1.6rem; font-weight: 700; color: var(--tp-fg); }
.tp-reco-cell small { color: var(--tp-muted); font-size: .78rem; }
.tp-reco-known { background: #f0fdf4; border-color: #bbf7d0; }
.tp-reco-visible { background: #dbeafe; border-color: #93c5fd; }
.tp-reco-gap { background: #fee2e2; border-color: #fca5a5; }
.tp-reco-gap span { color: #dc2626; }
.tp-reco-note { font-size: .9rem; padding: .75rem; background: #fef2f2; border-left: 3px solid #dc2626; }
```

### 1.3 Canonical URLs incorecte

**Ce văd crawlers acum:**
```html
<link rel="canonical" href="https://bise88.github.io/transparenta-pantelimon/">
<meta property="og:url" content="https://bise88.github.io/transparenta-pantelimon/">
```

**Ce trebuie:**
```html
<link rel="canonical" href="https://transparenta-pantelimon.eu/">
<meta property="og:url" content="https://transparenta-pantelimon.eu/">
```

**Impact:** Google poate considera `transparenta-pantelimon.eu` ca duplicat secundar. Share-urile pe rețele sociale afișează URL-ul vechi.

**Fix:**
```bash
git grep -l "bise88.github.io" | xargs sed -i 's|bise88.github.io/transparenta-pantelimon|transparenta-pantelimon.eu|g'
```

Verifică și `enhance.js` — în funcția `injectNav()` linkul GitHub e hard-coded la `bise88/transparenta-pantelimon` în loc de `transparenta-locala/transparenta-pantelimon`.

### 1.4 Curățenie repo

| Problemă | Recomandare |
|---|---|
| `update-report.yml` la rădăcina repo (nu în `.github/workflows/`) | Verifică dacă e duplicat al workflow-ului din `.github/workflows/`. Dacă da, șterge. GitHub Actions nu execută workflows din rădăcină. |
| Folder `github-repo/` la rădăcină | Pare commit accidental. `git log --all -- github-repo` să verifici, apoi șterge dacă nu e folosit. |
| Lipsește `README.md` | Critic — vezi §6.3. |
| `requirements.txt` mixează pinning strict (`==`) cu lax (`>=`) | Standardizează cu `pip-compile` (pip-tools) sau migrare la `pyproject.toml`. |

---

## 2. Algoritmi noi de detectare

9 detectoare noi care extind cele 13 existente. Tonul în `descriere` e neutru-factual (descriu fapte, nu trag concluzii).

### 2.1 Detector valori identice pe firme diferite în aceeași zi

Pattern observat manual: 29.07.2025 — 3 firme × 29.508.940 RON. 05.09.2025 — 2 firme × 24.184.504 RON. Pattern reproductibil care merită automatizat.

```python
from collections import defaultdict
from datetime import datetime

def detect_identical_value_same_day(contracts, min_firms=2, min_value_ron=100_000):
    """
    Detectează contracte cu valoare EXACT identică atribuite la firme DIFERITE
    în aceeași zi. Indicator clasic de împărțire artificială a unui contract.
    """
    groups = defaultdict(list)
    for c in contracts:
        try:
            date = datetime.strptime(c.get('data', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        val = c.get('valoare', 0)
        cif = c.get('cif_furnizor', '')
        if val < min_value_ron or not cif:
            continue
        groups[(date, val)].append(c)

    flags = []
    for (date, val), ctrs in groups.items():
        unique_firms = {c['cif_furnizor'] for c in ctrs}
        if len(unique_firms) < min_firms:
            continue
        flags.append({
            'tip': 'VALORI_IDENTICE_ACEEASI_ZI',
            'severitate': 'CRITIC',
            'titlu': f'{len(ctrs)} contracte identice de {val:,.0f} RON în aceeași zi',
            'descriere': (
                f'În data de {date.strftime("%d.%m.%Y")}, {len(unique_firms)} firme '
                f'diferite au primit contracte cu valoare EXACT identică '
                f'({val:,.0f} RON fiecare). Total: {val * len(ctrs):,.0f} RON.'
            ),
            'data': date.isoformat(),
            'valoare_per_contract': val,
            'valoare_totala': val * len(ctrs),
            'numar_firme': len(unique_firms),
            'firme': sorted({c['furnizor'] for c in ctrs}),
            'cif_firme': sorted(unique_firms),
            'contracte': [c.get('cod_contract', '') for c in ctrs],
            'legi': ['L98/2016 art.11 (interdicție fragmentare)'],
        })
    return sorted(flags, key=lambda f: f['valoare_totala'], reverse=True)
```

### 2.2 Burst detection — peste N contracte într-o zi

```python
def detect_burst_days(contracts, threshold=5, value_threshold_ron=50_000):
    """Detectează zile cu volum anormal de contracte."""
    by_day = defaultdict(list)
    for c in contracts:
        d = c.get('data', '')[:10]
        if d:
            by_day[d].append(c)

    flags = []
    for date, ctrs in by_day.items():
        if len(ctrs) < threshold:
            continue
        valoare = sum(c.get('valoare', 0) for c in ctrs)
        if valoare < value_threshold_ron:
            continue
        weekday = datetime.fromisoformat(date).strftime('%A')
        is_weekend = weekday in ('Saturday', 'Sunday')

        flags.append({
            'tip': 'BURST_CONTRACTE',
            'severitate': 'MAJOR' if len(ctrs) > 10 else 'MEDIU',
            'titlu': f'{len(ctrs)} contracte semnate într-o singură zi ({date})',
            'descriere': (
                f'În {date} ({weekday}) s-au semnat {len(ctrs)} contracte '
                f'cu valoare totală {valoare:,.0f} RON.'
                + (' Atribuire în weekend.' if is_weekend else '')
            ),
            'data': date,
            'numar_contracte': len(ctrs),
            'valoare_totala': valoare,
            'weekend': is_weekend,
        })
    return flags
```

### 2.3 Shell company detector — fără API plătit

Sursa: `mfinante.gov.ro/static/10/Anaf/Informatii_R/situatii_financiare.html` — date publice oficiale (cifră afaceri, profit, număr angajați).

```python
import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import json
from datetime import datetime, timedelta

CACHE_DB = 'firme_cache.db'
TTL_DAYS = 30

def _init_cache():
    conn = sqlite3.connect(CACHE_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS firme (
        cif TEXT PRIMARY KEY,
        data_extragere TEXT,
        date_json TEXT
    )''')
    conn.commit()
    return conn

def _cache_get(cif):
    conn = _init_cache()
    row = conn.execute(
        'SELECT data_extragere, date_json FROM firme WHERE cif=?', (cif,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    extragere = datetime.fromisoformat(row[0])
    if datetime.now() - extragere > timedelta(days=TTL_DAYS):
        return None
    return json.loads(row[1])

def _cache_set(cif, data):
    conn = _init_cache()
    conn.execute('INSERT OR REPLACE INTO firme VALUES (?, ?, ?)',
                 (cif, datetime.now().isoformat(),
                  json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()

def fetch_firma_anaf(cif, contact_email):
    """
    Extrage cifră afaceri, profit, număr salariați din mfinante.gov.ro.
    Date publice sub L. 544/2001.
    """
    cached = _cache_get(cif)
    if cached:
        return cached

    cif_clean = str(cif).replace('RO', '').strip()
    url = ('https://mfinante.gov.ro/static/10/Anaf/'
           f'Informatii_R/situatii_financiare.html?cui={cif_clean}')
    headers = {
        'User-Agent': f'transparenta-pantelimon-bot (contact: {contact_email})',
    }
    try:
        time.sleep(1.2)  # rate limit strict
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        return {'cif': cif, 'error': str(e)}

    soup = BeautifulSoup(r.text, 'html.parser')
    data = {'cif': cif, 'extras_la': datetime.now().isoformat(), 'ani': {}}

    # Parsing tabele - ajustează după inspecție live
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
            if not cells or len(cells) < 2:
                continue
            label = cells[0].lower()
            for i, year in enumerate(['2024', '2023', '2022'], start=1):
                if i >= len(cells):
                    break
                val_str = cells[i].replace('.', '').replace(',', '.').replace(' ', '')
                try:
                    val = float(val_str)
                except ValueError:
                    continue
                if 'cifra de afaceri' in label:
                    data['ani'].setdefault(year, {})['cifra_afaceri'] = val
                elif 'profit' in label and 'pierdere' not in label:
                    data['ani'].setdefault(year, {})['profit'] = val
                elif 'salariati' in label or 'angajati' in label:
                    data['ani'].setdefault(year, {})['salariati'] = int(val) if val == int(val) else val

    _cache_set(cif, data)
    return data

def evaluate_shell_risk(firma_data, contract_date, contract_value):
    """Returnează listă de flag-uri factuale."""
    flags = []
    if not firma_data or 'error' in firma_data:
        return flags

    year_contract = contract_date[:4]
    year_prev = str(int(year_contract) - 1)
    ani = firma_data.get('ani', {})

    if year_prev in ani:
        ca = ani[year_prev].get('cifra_afaceri')
        sal = ani[year_prev].get('salariati')

        if ca == 0 or (ca is not None and ca < contract_value * 0.1):
            flags.append({
                'cod': 'CIFRA_AFACERI_FOARTE_MICA',
                'severitate': 'CRITIC' if ca == 0 else 'MAJOR',
                'descriere': (
                    f'Cifră de afaceri în {year_prev} = {ca:,.0f} RON, '
                    f'contract {year_contract} = {contract_value:,.0f} RON.'
                ),
            })

        if sal == 0:
            flags.append({
                'cod': 'ZERO_ANGAJATI',
                'severitate': 'MAJOR',
                'descriere': f'0 angajați declarați la ANAF pentru {year_prev}.',
            })
        elif sal is not None and sal <= 2:
            flags.append({
                'cod': 'FOARTE_PUTINI_ANGAJATI',
                'severitate': 'MEDIU',
                'descriere': f'{sal} angajați declarați.',
            })

    return flags
```

**Disclaimer obligatoriu pe UI** (pentru context juridic):

> *Datele afișate sunt fapte publice publicate de Ministerul Finanțelor sub L. 544/2001. Pentru actualizări sau rectificări, contactați-ne. Datele pot fi învechite cu 6-12 luni față de momentul publicării.*

### 2.4 Repeat-loser pattern — ofertanți care pierd sistematic

Necesită date despre toți ofertanții, nu doar câștigătorul. Indicator pentru carteluri implicite.

```python
def detect_repeat_loser_pattern(procurari, min_apparitions=3):
    from collections import Counter
    losers = Counter()
    winners = Counter()
    pairs = defaultdict(int)

    for p in procurari:
        winner = p.get('cif_castigator')
        all_offerers = p.get('cifs_ofertanti', [])
        if not winner or len(all_offerers) < 2:
            continue
        winners[winner] += 1
        for o in all_offerers:
            if o != winner:
                losers[o] += 1
                pairs[(o, winner)] += 1

    flags = []
    for cif_loser, n_lost in losers.items():
        if n_lost < min_apparitions or winners.get(cif_loser, 0) > 0:
            continue
        top_winners = sorted(
            [(w, c) for (l, w), c in pairs.items() if l == cif_loser],
            key=lambda x: -x[1]
        )[:3]
        flags.append({
            'tip': 'REPEAT_LOSER',
            'severitate': 'MAJOR',
            'titlu': 'Ofertant frecvent care nu câștigă niciodată',
            'descriere': (
                f'CIF {cif_loser} a participat la {n_lost} proceduri SEAP, '
                f'fără să câștige nici una. Top firme împotriva cărora pierde: '
                + ', '.join(f'CIF {w} ({c} apariții)' for w, c in top_winners)
            ),
            'cif_loser': cif_loser,
            'n_apparitions': n_lost,
            'top_winners': top_winners,
            'legi': ['L21/1996 (Concurența) art.5(1)(c)'],
        })
    return flags
```

### 2.5 Geographic anomaly

Furnizor cu sediu departe de Pantelimon pentru servicii care în mod normal se contractează local.

```python
JUDETE_ADIACENTE_ILFOV = {'IF', 'B', 'GR', 'CL', 'IL', 'PH', 'DB'}

def detect_geographic_anomaly(contract, firma_data):
    obiect = contract.get('obiect', '').lower()
    keywords_local = ['curatenie', 'paza', 'mentenanta', 'salubrizare',
                      'deszapezire', 'iluminat strazi', 'spatii verzi']
    if not any(k in obiect for k in keywords_local):
        return None

    judet_firma = firma_data.get('judet', '').upper()
    if judet_firma and judet_firma not in JUDETE_ADIACENTE_ILFOV:
        return {
            'tip': 'GEOGRAFIE_ANORMALA',
            'severitate': 'MEDIU',
            'titlu': f'Servicii locale de la furnizor din {judet_firma}',
            'descriere': (
                f'Contract pentru "{obiect[:60]}…" atribuit firmei cu sediul în '
                f'{judet_firma}. Servicii de acest tip se contractează de obicei local.'
            ),
        }
    return None
```

### 2.6 Round-number bidding

Sume „rotunde" sau exact sub pragul legal.

```python
def detect_round_number_bids(contracts):
    PRAGURI = {'servicii': 130_000, 'lucrari': 500_000}
    flags = []
    for c in contracts:
        val = c.get('valoare', 0)
        if not val:
            continue
        obiect = c.get('obiect', '').lower()
        tip = 'lucrari' if 'lucrari' in obiect or 'constructi' in obiect else 'servicii'
        prag = PRAGURI[tip]

        if 0.97 <= val/prag < 1.0:
            flags.append({
                'tip': 'VALOARE_LA_PRAG',
                'severitate': 'MAJOR',
                'titlu': f'Contract la {val/prag*100:.1f}% din pragul legal',
                'descriere': (
                    f'Valoare {val:,.0f} RON, prag legal {tip} = {prag:,.0f} RON.'
                ),
            })
        elif val >= 50_000 and val % 10_000 == 0:
            flags.append({
                'tip': 'VALOARE_ROTUNDA',
                'severitate': 'MEDIU',
                'titlu': f'Valoare contractuală suspect de rotundă ({val:,.0f} RON)',
                'descriere': (
                    f'Sume exact divizibile cu 10.000 RON sunt rare în devizele '
                    f'reale (care includ TVA și calcule precise).'
                ),
            })
    return flags
```

### 2.7 Holiday/weekend signing

```python
import holidays  # pip install holidays

def detect_off_hours_signing(contracts):
    """Contracte semnate în weekend sau sărbătoare legală."""
    ro_holidays = holidays.Romania()
    flags = []
    for c in contracts:
        try:
            d = datetime.strptime(c.get('data', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        is_weekend = d.weekday() >= 5
        is_holiday = d in ro_holidays
        if not (is_weekend or is_holiday):
            continue
        val = c.get('valoare', 0)
        if val < 50_000:
            continue
        flags.append({
            'tip': 'SEMNARE_NELUCRATOARE',
            'severitate': 'MEDIU',
            'titlu': f'Contract semnat în {"weekend" if is_weekend else "sărbătoare"}',
            'descriere': (
                f'Contract de {val:,.0f} RON semnat în {d.strftime("%A %d.%m.%Y")}.'
            ),
            'data': d.isoformat(),
            'valoare': val,
        })
    return flags
```

### 2.8 Cifră afaceri sub valoarea contractului

Caz particular al §2.3 — pentru firme unde cifra de afaceri din anul precedent contractului e mult mai mică decât valoarea contractului.

### 2.9 Network analysis — firme legate prin admin/acționariat

Folosește `networkx`:

```python
import networkx as nx

def build_company_network(suppliers_with_admins):
    """
    suppliers_with_admins = [
        {
            'cif': '12345',
            'name': 'X',
            'admins': ['Ion Popescu'],
            'shareholders': [{'name': 'Y SRL', 'cif': '67890', 'pct': 100}]
        },
        ...
    ]
    """
    G = nx.Graph()
    for s in suppliers_with_admins:
        G.add_node(s['cif'], type='firma', name=s['name'])
        for admin in s.get('admins', []):
            person_id = f"person:{admin.lower().strip().replace(' ', '-')}"
            G.add_node(person_id, type='persoana', name=admin)
            G.add_edge(person_id, s['cif'], role='admin')
        for sh in s.get('shareholders', []):
            G.add_node(sh['cif'], type='firma', name=sh['name'])
            G.add_edge(sh['cif'], s['cif'], role='actionar', pct=sh.get('pct', 0))
    return G

def find_suspicious_clusters(G, min_size=2):
    clusters = []
    for component in nx.connected_components(G):
        firme_in_comp = [n for n in component if G.nodes[n].get('type') == 'firma']
        if len(firme_in_comp) >= min_size:
            clusters.append({
                'firme_cifs': firme_in_comp,
                'firme_names': [G.nodes[n]['name'] for n in firme_in_comp],
                'persoane_legatura': [G.nodes[n]['name'] for n in component
                                      if G.nodes[n].get('type') == 'persoana'],
                'size': len(firme_in_comp),
            })
    return sorted(clusters, key=lambda c: -c['size'])
```

Vizualizare cu **Cytoscape.js** (recomandat peste vis.js / d3-force pentru 50-200 noduri):

```html
<!-- retea.html -->
<div id="cy" style="width:100%;height:80vh"></div>
<script src="https://unpkg.com/cytoscape@3.28/dist/cytoscape.min.js"></script>
<script>
fetch('retea.json').then(r => r.json()).then(data => {
  const elements = [
    ...data.nodes.map(n => ({data: {id: n.id, label: n.name, type: n.type}})),
    ...data.edges.map(e => ({data: {source: e.source, target: e.target, label: e.role}})),
  ];
  cytoscape({
    container: document.getElementById('cy'),
    elements,
    style: [
      { selector: 'node[type="firma"]',
        style: {'background-color': '#dc2626', 'label': 'data(label)',
                'color': '#fff', 'font-size': 10}},
      { selector: 'node[type="persoana"]',
        style: {'background-color': '#3b82f6', 'shape': 'diamond',
                'label': 'data(label)'}},
      { selector: 'edge',
        style: {'line-color': '#94a3b8', 'label': 'data(label)', 'font-size': 8}},
    ],
    layout: { name: 'cose', animate: false },
  });
});
</script>
```

**Disclaimer obligatoriu** pe pagina rețelei (risc juridic):

> *Conexiunile afișate sunt bazate pe potriviri de nume în datele publice ONRC. Numele identice nu garantează aceeași persoană. Această vizualizare e punct de pornire pentru investigație, nu concluzie.*

---

## 3. Surse noi de date

### 3.1 Curtea de Conturi

Rapoarte de audit anuale pentru UAT, publicate pe `curteadeconturi.ro`. Conțin neregularități găsite oficial — dovadă, nu suspiciune.

```python
def fetch_curtea_de_conturi(uat_nume='Pantelimon'):
    """Caută rapoartele de audit CC pentru UAT.
    Strategia: site search + scraping PDF + OCR la nevoie.
    Implementare detaliată într-un modul separat."""
    pass
```

Implementare ca proiect separat (1-2 zile cu `pdfplumber` + revizuire manuală).

### 3.2 ANI — declarații avere aleși locali

`https://www.integritate.eu/Search?cuvinte=Pantelimon`

```python
def fetch_declaratii_avere(uat='Pantelimon'):
    """Scraping declarații de avere pentru aleșii UAT."""
    url = f'https://www.integritate.eu/Search?cuvinte={uat}'
    r = requests.get(url, headers={'User-Agent': 'transparenta-pantelimon-bot'},
                     timeout=20)
    soup = BeautifulSoup(r.text, 'html.parser')
    # Extract: nume, funcție, an, link PDF
    # OCR PDF pentru extragere rude + venituri suspecte
    return []
```

**Notă GDPR:** afișează doar funcții publice + nume; NU CNP / adresă personală.

### 3.3 proiecte.pnrr.gov.ro

```python
def fetch_pnrr_projects(beneficiary_cif='4420759'):
    url = f'https://proiecte.pnrr.gov.ro/api/projects?beneficiary={beneficiary_cif}'
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        return r.json()
    return []  # fallback: scraping HTML
```

### 3.4 TED Europa

Pentru contracte > 500.000 EUR. Dacă apar contracte mari în SEAP care NU apar și în TED, e încălcare directă a Directivei UE 2014/24.

```python
def search_ted_for_buyer(cif_buyer, year):
    """API public TED."""
    url = 'https://ted.europa.eu/api/v3.0/notices/search'
    params = {
        'q': f'BUYER-NATIONALID="{cif_buyer}"',
        'fields': 'BT-150,BT-720,publication-date',
        'scope': 3,
    }
    return requests.get(url, params=params, timeout=30).json()
```

### 3.5 Monitorul Oficial Local

`primariapantelimon.ro/mol/` (dacă există) — scraping pentru:
- Rectificări bugetare (cu sume concrete: „rectificare HCL 47/2025 a mutat 2,3M RON de la Investiții la Cheltuieli curente")
- Ședințe extraordinare cu motivare lipsă

### 3.6 OpenStreetMap Nominatim — geocoding sedii firme

Pentru detectarea pattern-ului „sediu la cabinet contabil cu 47 firme" (din §2.5). Rate-limited gratuit, cache local.

### 3.7 Tabel sintetic surse

| Sursă | Tip | Cost | Frecvență | Prioritate |
|---|---|---|---|---|
| Curtea de Conturi | Rapoarte audit | gratis | anual | înaltă |
| ANI declarații avere | Date aleși | gratis | anual + ad-hoc | înaltă |
| proiecte.pnrr.gov.ro | Proiecte PNRR | gratis | săptămânal | înaltă |
| TED Europa | Anunțuri UE | gratis | zilnic | medie |
| MOL primărie | HCL-uri | gratis | lunar | medie |
| mfinante.gov.ro | Cifră afaceri firme | gratis | anual | medie |
| Consiliul Concurenței | Decizii anti-cartel | gratis | ad-hoc | medie |
| termene.ro | Profil firmă | gratis (scraping) | săptămânal | medie |
| Nominatim OSM | Geocoding | gratis (rate-lim) | la cerere | scăzută |
| openapi.ro | ONRC firme | freemium (în uz) | la cerere | ✓ |

---

## 4. UX, performanță și accesibilitate

### 4.1 Widget reconciliere (vezi §1.2)

Cod în §1.2.

### 4.2 Dark mode toggle

`enhance.js` are deja CSS pentru `[data-tp-theme="dark"]`. Lipsește butonul:

```javascript
// Adaugă în injectNav() lângă brand:
const themeBtn = document.createElement('button');
themeBtn.className = 'tp-theme-toggle';
themeBtn.innerHTML = '🌓';
themeBtn.title = 'Comută temă';
themeBtn.setAttribute('aria-label', 'Comută între temă luminoasă și întunecată');
themeBtn.addEventListener('click', () => {
  const cur = document.documentElement.dataset.tpTheme || 'light';
  const next = cur === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.tpTheme = next;
  try { localStorage.setItem('tp-theme', next); } catch (e) {}
});

// La boot, înainte de injectNav:
const saved = localStorage.getItem('tp-theme');
if (saved) document.documentElement.dataset.tpTheme = saved;
else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
  document.documentElement.dataset.tpTheme = 'dark';
}
```

### 4.3 Service Worker / PWA

Pentru consultare offline (cetățean care vrea să trimită sesizare ANAP fără conexiune).

```javascript
// sw.js la rădăcina repo
const CACHE = 'tp-v1';
const CORE = ['/', '/index.html', '/raport_transparenta.html',
              '/transparenta_pantelimon.html', '/enhance.js', '/styles.css',
              '/raport.json', '/delta.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then(cached => cached ||
      fetch(e.request).then(resp => {
        if (resp.ok && new URL(e.request.url).origin === location.origin) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match('/index.html'))
    )
  );
});
```

Înregistrare în `enhance.js`:
```javascript
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
```

`manifest.webmanifest`:
```json
{
  "name": "Transparența Pantelimon",
  "short_name": "TransparPantelimon",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#dc2626",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

### 4.4 Accesibilitate (WCAG 2.1 AA)

| Issue | Severitate | Fix |
|---|---|---|
| Iconuri emoji decorative fără `aria-hidden="true"` | Medium | `<span aria-hidden="true">🚩</span>` |
| Contrast `--tp-muted: #6b7280` pe alb = ratio 4.3:1 (limit) | Low | `#4b5563` (ratio 7.3:1) |
| Lipsă `<main>` semantic | Low | Înfășurați conținutul principal în `<main id="main-content">` |
| Lipsă skip-link tastatură | Medium | `<a href="#main-content" class="skip-link">Sări la conținut</a>` + CSS care îl ascunde până la `:focus` |

### 4.5 Core Web Vitals

- `enhance.js` cu `defer` (deja făcut)
- Imagini cu `loading="lazy"` + `width`/`height` explicit (CLS)
- CSS critical inline, restul async
- Rulează `npx lighthouse https://transparenta-pantelimon.eu` și fixează ce iese roșu

### 4.6 Map view — Leaflet

Pagină nouă `harta.html` cu sediile firmelor geocodate.

```html
<div id="map" style="height:600px"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9/dist/leaflet.js"></script>
<script>
fetch('firme_geocoded.json').then(r => r.json()).then(firme => {
  const map = L.map('map').setView([44.45, 26.20], 9);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap'
  }).addTo(map);
  firme.forEach(f => {
    if (!f.lat) return;
    const color = f.valoare > 10_000_000 ? '#dc2626'
                : f.valoare > 1_000_000 ? '#f59e0b' : '#3b82f6';
    L.circleMarker([f.lat, f.lng], {
      radius: 6 + Math.log10(f.valoare) / 2,
      color, fillOpacity: .7
    })
    .bindPopup(`<strong>${f.name}</strong><br>${f.valoare.toLocaleString()} RON`)
    .addTo(map);
  });
});
</script>
```

Geocoding cu Nominatim, cache în `firme_geocoded.json`.

---

## 5. Conținut & narativă pentru utilizatori

### 5.1 Pagină dedicată pentru jurnaliști

`presa.html` cu:
- Top 10 cele mai mari nereguli (auto-generat lunar)
- Top 10 firme după valoare contracte
- Press kit downloadable
- Metodologie completă
- Contact + lista contactelor utile

```python
def genereaza_press_kit(nereguli, contracte, scor, contact_email):
    """Generează press-kit-ul ca markdown + PDF."""
    template = """
# Press kit — Transparența Pantelimon ({data})

## Statistici la zi
- Total nereguli detectate: {n_nereguli}
- Critice: {n_critic}, Majore: {n_major}
- Valoare totală contracte analizate: {val_total} RON
- Procent vizibilitate cheltuieli în SEAP: {procent_vizibil}%
- Scor transparență: {scor}/100

## Top 5 cele mai mari nereguli
{top_5_table}

## Date deschise
- API JSON: https://transparenta-pantelimon.eu/raport.json
- CSV: https://transparenta-pantelimon.eu/contracte.csv
- RSS: https://transparenta-pantelimon.eu/feed.xml

## Contact
{contact_email}

## Metodologie completă
https://transparenta-pantelimon.eu/metodologie.html

## Disclaimer
Toate datele sunt fapte publice. Concluziile sunt la latitudinea cititorului.
"""
    return template.format(...)
```

### 5.2 Email template-uri pre-completate pe carduri

Buton pe fiecare neregulă „📧 Sesizare ANAP cu un click":

```javascript
function generateAnapEmail(card) {
  const subject = encodeURIComponent(
    `Sesizare achiziții publice - Primăria Pantelimon - ${card.contract}`
  );
  const body = encodeURIComponent(`
Subsemnatul/a [NUMELE TĂU], domiciliat în [ADRESA], CNP [CNP],
în calitate de cetățean, sesizez următoarea posibilă neregulă:

OBIECT: ${card.title}

DETALII:
- Autoritate: Primăria Pantelimon (CIF 4420759)
- Cod contract: ${card.contract}
- Valoare: ${card.sum} RON
- Furnizor: ${card.supplier} (CIF: ${card.supplierCif})
- Data atribuirii: ${card.date}
- Procedură: ${card.procedure}
- Lege posibil încălcată: ${card.lawRef}

DESCRIERE:
${card.explanation}

VERIFICARE:
- Anunț SEAP: ${card.seapUrl}
- Analiză detaliată: ${location.origin}${location.pathname}#nereguli-${card.idx + 1}

Solicit verificarea acestei achiziții și informarea în legătură cu rezultatele.

Data: ${new Date().toLocaleDateString('ro-RO')}
Semnătura: [SEMNĂTURĂ]
  `.trim());
  return `mailto:contact@anap.gov.ro?subject=${subject}&body=${body}`;
}
```

Câmpurile între paranteze pătrate rămân de completat manual de cetățean — TOATE detaliile contractuale sunt deja umplute. Coboară bariera de la „nu știu cum se face" la „semnez și trimit".

### 5.3 Pagină „Despre"

Necesară pentru:
- Cine e autorul (transparență)
- Metodologie (cum se aplică algoritmii)
- Conflict de interese (declarat explicit, oricare ar fi)
- Cum poate ajuta cineva (PR-uri, traduceri, fork pentru altă localitate)

### 5.4 Comparator multi-UAT

Codul curent funcționează pentru orice CIF — refactorizați în modul + script `monitor_uat.py CIF JUDET`:

```bash
python monitor_uat.py 4420759 Ilfov  # Pantelimon
python monitor_uat.py 4364643 Ilfov  # Voluntari
python monitor_uat.py 4364660 Ilfov  # Popești-Leordeni
```

Generează `comparator.html` cu tabel side-by-side:

| Indicator | Pantelimon | Voluntari | Popești-Leordeni | Mediană Ilfov |
|---|---|---|---|---|
| % cumpărări directe | 100% | 67% | 78% | 72% |
| % ofertant unic | 67% | 38% | 45% | 42% |
| Scor transparență | D+ (47/100) | C+ (62/100) | C (58/100) | C (60) |
| Cheltuieli/locuitor | 4.460 RON | 6.180 RON | 5.210 RON | 5.300 RON |

### 5.5 Petiție online

Pagină `petitie.html` cu formular pentru semnături cetățenești. Backend: Formspree gratuit (50 răspunsuri/lună) sau Google Forms.

### 5.6 Newsletter

Substack gratuit. Cron la fiecare update Python care preia `delta.json` și trimite email cu „N nereguli noi în luna X" + link spre raport.

### 5.7 OG image generator

`og:image` lipsește (verifică `<meta og:image>` curent). Generare automată:

```python
from PIL import Image, ImageDraw, ImageFont

def generate_og_image(stats, output='og-image.png'):
    img = Image.new('RGB', (1200, 630), '#0a0a0a')
    d = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype(
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 100)
        font_med = ImageFont.truetype(
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 44)
        font_sm = ImageFont.truetype(
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
    except (OSError, IOError):
        font_big = font_med = font_sm = ImageFont.load_default()

    d.text((60, 60), 'Transparența Pantelimon', fill='#fff', font=font_med)
    d.text((60, 160), f'{stats["n_flags"]} nereguli', fill='#dc2626', font=font_big)
    d.text((60, 290),
           f'{stats["n_critic"]} CRITICE · {stats["valoare_mil"]:.0f} mil. RON',
           fill='#f59e0b', font=font_med)
    d.rectangle((60, 410, 1140, 470), fill='#1f1f1f')
    d.text((80, 420), f'Scor transparență: {stats["scor"]}/100',
           fill='#fff', font=font_med)
    d.text((60, 540), 'transparenta-pantelimon.eu', fill='#6b7280', font=font_sm)
    img.save(output, 'PNG', optimize=True)
```

### 5.8 GDPR & disclaimer

Pagină `gdpr.html` cu:
- Datele afișate provin din surse publice (SEAP, ANAF, ONRC, MF)
- Bază legală: Art. 6(1)(e) GDPR + Legea 363/2018 (interes public)
- Mecanism rectificare: email contact + procedură de revizuire în max. 30 zile
- Politica cookie-uri (verifică ce folosești cu `localStorage` — declară explicit)

---

## 6. Workflow & repo hygiene

### 6.1 Refactor `monitor_pantelimon.py` în module

87KB într-un fișier. Structură propusă:

```
src/
  __init__.py
  config.py            # constante, CUI primărie, praguri legale
  sources/
    seap.py            # fetch + parse contracte SEAP
    anaf.py            # buget execuție
    onrc.py            # date firme (openapi.ro)
    mfinante.py        # cifră afaceri firme (§2.3)
    pnrr.py            # proiecte UE (§3.3)
  detectors/
    base.py            # interface Detector
    single_offerer.py
    direct_over_threshold.py
    fragmentation.py
    identical_values.py    # NOU (§2.1)
    burst.py               # NOU (§2.2)
    shell_company.py       # NOU (§2.3)
    repeat_loser.py        # NOU (§2.4)
    geographic.py          # NOU (§2.5)
    round_numbers.py       # NOU (§2.6)
    off_hours.py           # NOU (§2.7)
  network/
    builder.py
    cluster.py
  output/
    html.py
    json_export.py
    feed.py
    og_image.py
    press_kit.py
  cli.py               # entrypoint
tests/
  ...
monitor_uat.py         # CLI wrapper care apelează src/cli.py
```

Cu Detector interface:

```python
from abc import ABC, abstractmethod

class Detector(ABC):
    @abstractmethod
    def run(self, contracts, suppliers, budget) -> list[dict]:
        """Returnează listă de flag-uri."""

DETECTORS = [
    SingleOffererDetector(),
    DirectOverThresholdDetector(),
    IdenticalValuesDetector(),
    BurstDetector(),
    ShellCompanyDetector(),
    # ...
]

def run_all(data):
    flags = []
    for d in DETECTORS:
        flags.extend(d.run(**data))
    return flags
```

### 6.2 Teste pytest

Începe cu fixture-uri pentru contractele cunoscute:

```python
# tests/test_identical_values.py
def test_detects_identical_value_same_day():
    contracts = [
        {'cif_furnizor': '30056330', 'furnizor': 'ALA EXPERT',
         'data': '2025-07-29', 'valoare': 29508940},
        {'cif_furnizor': '27702350', 'furnizor': 'SANTIA',
         'data': '2025-07-29', 'valoare': 29508940},
        {'cif_furnizor': '28250562', 'furnizor': 'YARDMAN',
         'data': '2025-07-29', 'valoare': 29508940},
    ]
    flags = detect_identical_value_same_day(contracts)
    assert len(flags) == 1
    assert flags[0]['severitate'] == 'CRITIC'
    assert flags[0]['numar_firme'] == 3
    assert flags[0]['valoare_totala'] == 88526820
```

Workflow CI:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt pytest
      - run: pytest
```

### 6.3 README.md (lipsește în repo)

```markdown
# Transparența Pantelimon

Monitorizare cetățenească automată a achizițiilor publice ale Primăriei Pantelimon.
Site live: [transparenta-pantelimon.eu](https://transparenta-pantelimon.eu)

## Ce face

- Trage lunar contractele din SEAP (e-licitatie.ro) și bugetul de la ANAF
- Aplică algoritmi de detecție pentru pattern-uri de risc
- Generează raport HTML + JSON + RSS + press-kit
- Publică automat pe GitHub Pages

## Replicare pentru altă localitate

```bash
git clone https://github.com/transparenta-locala/transparenta-pantelimon
cd transparenta-pantelimon
cp config.example.py config.py  # editează cu CIF + nume UAT
pip install -r requirements.txt
python monitor_uat.py
```

## Contribuie

- Issues: bug-uri sau idei noi
- PR-uri: cod nou (vezi `IMPROVEMENTS.md`)
- Pentru fork la altă localitate: contactați-ne

## Licență

Cod: MIT. Date generate: CC-BY 4.0.

## Disclaimer

Toate datele sunt fapte publice (SEAP, ANAF, ONRC). Site-ul nu face afirmații
despre intenții sau vinovăție — doar afișează statistici și legi posibil încălcate.
Concluziile sunt la latitudinea cititorului.

## Contact

[email contact]
```

### 6.4 Branch protection + PR review

GitHub: Settings → Branches → Add rule pentru `main`:
- Require pull request reviews
- Require status checks (după ce ai CI)
- Include administrators

### 6.5 Audit secrete

```bash
git log -p | grep -iE 'api[_-]?key|password|token|secret' | head -50
```

Dacă există secrete hardcoded în istorie, regenerează-le + cleanup cu `git filter-repo`.

---

## 7. Roadmap propus

### Săptămâna 1 (urgență — bug-uri pe live)

1. Fix tabel SEAP „Se încarcă..." (§1.1)
2. Fix canonical URLs (§1.3)
3. Adaugă README.md (§6.3)
4. Cleanup folder `github-repo/` + `update-report.yml` duplicat (§1.4)
5. Widget reconciliere ANAF↔SEAP (§1.2 + §4.1)

### Săptămâna 2-3 (impact mare, efort mic)

6. Detectoare §2.1 + §2.2 + §2.6 + §2.7 (toate funcții Python pure)
7. Email template-uri pe carduri (§5.2)
8. Dark mode toggle (§4.2)
9. Pagină „Despre" (§5.3)
10. OG image generator (§5.7)

### Luna 1 (efort mediu, impact mare)

11. Shell company detector + cache sqlite (§2.3)
12. Refactor modular `monitor_pantelimon.py` (§6.1)
13. Teste pytest (§6.2)
14. Service Worker / PWA (§4.3)
15. Pagini per furnizor (Faza 3-D din `IMPROVEMENTS.md`)
16. Press kit auto-generat (§5.1)

### Luna 2-3 (proiecte mari)

17. Network analysis cu Cytoscape (§2.9)
18. Curtea de Conturi scraper (§3.1)
19. ANI declarații avere (§3.2)
20. Map view cu Leaflet (§4.6)
21. Comparator multi-UAT (§5.4)
22. Newsletter (§5.6)
23. Petiție online (§5.5)

### Strategic (Q3-Q4 2026)

24. Multi-localitate completă (Faza 4-F din `IMPROVEMENTS.md`)
25. TED Europa cross-reference (§3.4)
26. PNRR tracking + audit (Faza 5-L)
27. Translation EN

---

## 8. Concluzii tehnice

Trei lucruri pe care le evaluez ca punct forte al arhitecturii actuale:

**Codul e generic și replicabil.** Scriptul Python funcționează pentru orice CIF de primărie. Investiția cea mai mare e refactorul modular din §6.1 — restul (Voluntari, Popești-Leordeni, etc.) vine ușor după.

**Conținutul civic e bine făcut.** Pagina „Ce poți face ca cetățean" cu 9 căi de sesizare e completă. Combinată cu §5.2 (email-uri gata pre-completate) devine instrument funcțional, nu doar informativ.

**Tonul metodologic e corect.** „Nu constituie dovezi juridice, dar justifică sesizări" e formulare prudentă și juridic defensivă. Aceeași abordare se aplică și algoritmilor noi din §2 — toate folosesc descrieri factuale.

---

*Audit tehnic — versiune publică. Toate sugestiile sunt orientative. Pentru întrebări sau follow-up, deschideți un issue în repo.*
