/*!
 * transparenta-enhance.js  v1.0
 * Progressive enhancement pentru https://transparenta-pantelimon.eu/
 *
 * Funcționalități:
 *   - Bară de navigare unificată pe toate paginile (Acasă / Nereguli / Buget / surse)
 *   - Pe pagina raportului: search liber, filtre severitate, dropdown furnizor,
 *     sortare, contor live, export CSV/JSON, paginare "load more" 25 deodată
 *   - Widget rezumat: top 10 furnizori după valoare/număr + bară severitate
 *   - Permalink per nereguă (#nereguli-42) — click pe titlu copiază link
 *   - Stil de print optimizat pentru salvare PDF
 *   - Back-to-top, scurtături "/" (focus search) și Esc (clear)
 *
 * Instalare: <script src="enhance.js" defer></script> înainte de </head> pe toate paginile.
 *
 * Robustețe: scriptul detectează cardurile prin pattern-uri text (nu depinde de
 * clase CSS specifice ale generatorului). Dacă structura HTML se schimbă, scriptul
 * se degradă elegant și loghează un warning în consolă.
 */
(function () {
  'use strict';

  // ──────────────────────────────────────────────────────────────
  // CONFIG
  // ──────────────────────────────────────────────────────────────
  const CFG = {
    pageSize: 25,
    storageKey: 'tp-prefs-v1',
    severityOrder: { CRITIC: 0, MAJOR: 1, MEDIU: 2 },
    severityColor: {
      CRITIC: '#A23B2C',
      MAJOR:  '#8F5A1E',
      MEDIU:  '#5E6B78',
    },
    // Etichete afișate pe pastile (aceleași cu datele)
    sevLabel: {
      CRITIC: 'CRITIC',
      MAJOR:  'MAJOR',
      MEDIU:  'MEDIU',
    },
  };

  // ──────────────────────────────────────────────────────────────
  // CSS — în assets/tp.css, legat direct din <head> de site_shell.py
  // (înainte era injectat de aici, după încărcare, și pagina „sărea”)
  // ──────────────────────────────────────────────────────────────

  // ──────────────────────────────────────────────────────────────
  // UTILITARE
  // ──────────────────────────────────────────────────────────────
  const $  = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function debounce(fn, ms) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function fmtRON(n) {
    if (!Number.isFinite(n) || n === 0) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + ' mil. RON';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K RON';
    return n.toLocaleString('ro-RO') + ' RON';
  }

  // data-contracts="id:valoare|id:valoare" (generat de monitor) → suma pe contracte distincte
  function sumaContracteDistincte(items) {
    const vazute = new Map();
    let fara = 0;
    // Raportul nou pune data-contracts pe fiecare semnal legat de contracte; semnalele
    // agregate (risc sistemic, HCL) nu au contract propriu și nu adaugă nimic — suma lor
    // e chiar suma contractelor firmei, deja numărate. Raport vechi: adunăm sumele.
    const nou = items.some(it => it.contracts);
    items.forEach(it => {
      if (!it.contracts) { if (!nou) fara += it.sum || 0; return; }
      it.contracts.split('|').forEach(p => {
        const i = p.lastIndexOf(':');
        if (i > 0) vazute.set(p.slice(0, i), parseFloat(p.slice(i + 1)) || 0);
      });
    });
    let total = fara;
    vazute.forEach(v => { total += v; });
    return total;
  }

  // Rezumatul static: butoanele „filtrează” trimit la lista de semnale a firmei
  function bindSummaryFilters(wrap) {
    wrap.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-filter-supplier]');
      if (!btn) return;
      e.preventDefault();
      const sel = $('#tp-supplier');
      if (sel) {
        sel.value = btn.dataset.filterSupplier;
        sel.dispatchEvent(new Event('change'));
        sel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }

  function parseSum(text) {
    // Acoperă: "880.000 RON", "1.234.567,89 lei", "17.92 mil. RON", "13,94 milioane"
    if (!text) return 0;
    const milMatch = text.match(/([\d.,]+)\s*mil(?:\.|ioane)?/i);
    if (milMatch) {
      const v = parseFloat(milMatch[1].replace(/\./g, '').replace(',', '.'));
      return Number.isFinite(v) ? v * 1e6 : 0;
    }
    const rawMatch = text.match(/([\d.,]+)\s*(?:RON|lei)/i);
    if (!rawMatch) return 0;
    let s = rawMatch[1];
    // Format RO: punct = mii, virgulă = zecimale
    if (s.includes(',')) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
      s = s.replace(/\./g, '');
    }
    const v = parseFloat(s);
    return Number.isFinite(v) ? v : 0;
  }

  function escapeHTML(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // ──────────────────────────────────────────────────────────────
  // NORMALIZARE CĂUTARE
  // ──────────────────────────────────────────────────────────────
  // Datele SEAP conțin nume „murdare": spații duble, diacritice inconsistente,
  // „&" vs „and", sufixe juridice prezente sau nu (SRL / S.R.L. / lipsă).
  // Fără normalizare, „DAV GARDEN&SERVICE SRL" nu găsea „DAV  GARDEN & SERVICE"
  // (două spații, fără SRL) — firma exista în date, dar căutarea returna 0.
  const TP_LEGAL_TOKENS = {
    srl: 1, srlu: 1, srld: 1, sarl: 1, sa: 1, sca: 1, snc: 1, scs: 1,
    pfa: 1, ii: 1, sc: 1, societate: 1, societatea: 1, comerciala: 1,
    asociatia: 1, asociatie: 1, ong: 1
  };

  // lowercase → fără diacritice → „&" devine „and" → punctuația devine spațiu
  function nzText(s) {
    let t = String(s == null ? '' : s).toLowerCase();
    if (t.normalize) t = t.normalize('NFD').replace(/[̀-ͯ]/g, '');
    // abrevieri punctate: „s.r.l." → „srl", „i.i." → „ii"
    t = t.replace(/\b(?:[a-z]\.){2,}/g, m => m.replace(/\./g, ''));
    return t
      .replace(/[șş]/g, 's')   // ș / ş (dacă NFD nu e disponibil)
      .replace(/[țţ]/g, 't')   // ț / ţ
      .replace(/[ăâ]/g, 'a')   // ă / â
      .replace(/î/g, 'i')           // î
      .replace(/&/g, ' and ')
      .replace(/[^a-z0-9]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // ca nzText, dar aruncă sufixele juridice (SRL, SA, PFA, SC…)
  function nzCore(s) {
    const out = [];
    nzText(s).split(' ').forEach(t => { if (t && !TP_LEGAL_TOKENS[t]) out.push(t); });
    return out.join(' ');
  }

  // Pre-calculează câmpurile de căutare o singură dată, indiferent de calea
  // prin care au fost construite items (tp-data JSON sau parsing DOM).
  function indexSearchFields(items) {
    items.forEach(it => {
      it.nzHay = nzCore([
        it.haystack || '', it.supplier || '', it.title || '',
        it.contract || '', it.procedure || '', it.type || ''
      ].join(' '));
      it.nzCif = String(it.supplierCif || '').replace(/[^0-9]/g, '');
    });
  }

  // Query → listă de tokenuri normalizate. Potrivirea e AND pe tokenuri, deci
  // ordinea cuvintelor nu contează („garden dav" găsește „DAV GARDEN").
  function setQuery(state, raw) {
    state.qRaw = String(raw == null ? '' : raw).trim();
    state.q = nzCore(state.qRaw);
    state.qTokens = state.q ? state.q.split(' ').filter(Boolean) : [];
  }

  function matchesQuery(it, state) {
    const toks = state.qTokens;
    if (!toks || !toks.length) return true;
    if (it.nzHay == null) indexSearchFields([it]);
    const hay = it.nzHay, cif = it.nzCif;
    for (let i = 0; i < toks.length; i++) {
      const t = toks[i];
      if (hay.indexOf(t) === -1 && !(cif && cif.indexOf(t) !== -1)) return false;
    }
    return true;
  }

  // Sugestii „ai vrut să spui…" pentru starea goală — scor pe potrivire de tokenuri
  function suggestSuppliers(items, state, max) {
    const toks = state.qTokens || [];
    if (!toks.length) return [];
    const best = new Map();
    items.forEach(it => {
      if (!it.supplier) return;
      const n = nzCore(it.supplier);
      let score = 0;
      toks.forEach(t => {
        if (n.indexOf(t) !== -1) { score += 3; return; }
        for (let L = Math.min(t.length, 8); L >= 4; L--) {
          if (n.indexOf(t.slice(0, L)) !== -1) { score += 1; return; }
        }
      });
      if (score > 0 && score > (best.get(it.supplier) || 0)) best.set(it.supplier, score);
    });
    return Array.from(best.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, max || 5)
      .map(e => e[0]);
  }

  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(CFG.storageKey)) || {}; }
    catch (e) { return {}; }
  }
  function savePrefs(p) {
    try { localStorage.setItem(CFG.storageKey, JSON.stringify(p)); }
    catch (e) {}
  }

  // ──────────────────────────────────────────────────────────────
  // HEAD INJECTION — favicon, CSP (toate paginile, o singură dată)
  // ──────────────────────────────────────────────────────────────
  function injectHead() {
    if (!document.querySelector('link[rel="icon"]')) {
      var ico = document.createElement('link');
      ico.rel = 'icon'; ico.href = '/favicon.ico'; ico.setAttribute('sizes', 'any');
      document.head.appendChild(ico);
      var icon = document.createElement('link');
      icon.rel = 'icon'; icon.href = '/icon-192.png'; icon.type = 'image/png'; icon.setAttribute('sizes', '192x192');
      document.head.appendChild(icon);
    }
    if (!document.querySelector('link[rel="apple-touch-icon"]')) {
      var apple = document.createElement('link');
      apple.rel = 'apple-touch-icon'; apple.href = '/apple-touch-icon.png';
      document.head.appendChild(apple);
    }
  }

  // Rădăcina site-ului, și din subdirectoare (furnizori/, semnale/) — altfel
  // linkurile din nav duc la /furnizori/raport_transparenta.html (404).
  function siteBase() {
    return location.pathname.replace(/\/[^/]*$/, '/').replace(/\/(furnizori|semnale)\/$/, '/');
  }

  // ──────────────────────────────────────────────────────────────
  // NAV (toate paginile)
  // ──────────────────────────────────────────────────────────────
  // Rezervă pentru o pagină care n-a primit încă cadrul static (site_shell.py)
  function injectStyle() {
    if (document.querySelector('link[href*="assets/tp.css"]')) return;
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = siteBase() + 'assets/tp.css';
    document.head.appendChild(l);
  }

  function injectManifest() {
    if (document.querySelector('link[rel="manifest"]')) return;
    const link = document.createElement('link');
    link.rel = 'manifest'; link.href = '/manifest.webmanifest';
    document.head.appendChild(link);
    if (!document.querySelector('meta[name="theme-color"]')) {
      const meta = document.createElement('meta');
      meta.name = 'theme-color'; meta.content = '#14263D';
      document.head.appendChild(meta);
    }
  }

  function injectNav() {
    // Meniul e scris static în pagină de site_shell.py; aici doar îl „legăm”.
    const existent = $('.tp-nav');
    if (existent) { bindNav(existent); return; }
    injectManifest();

    // §4.4 Skip link — keyboard users jump past nav directly to content
    const skipLink = document.createElement('a');
    skipLink.className = 'tp-skip-link';
    skipLink.href = '#main-content';
    skipLink.textContent = 'Salt la conținut';
    document.body.insertBefore(skipLink, document.body.firstChild);

    const nav = document.createElement('nav');
    nav.className = 'tp-nav';
    nav.setAttribute('aria-label', 'Navigare principală');

    const here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
    const base = siteBase();

    // Meniu principal scurt; restul paginilor stau sub „Mai mult” (pe telefon, în listă)
    const links = [
      { href: 'index.html',                   text: 'Acasă' },
      { href: 'raport_transparenta.html',      text: 'Semnale' },
      { href: 'furnizori/index.html',          text: 'Firme' },
      { href: 'transparenta_pantelimon.html',  text: 'Buget' },
      { href: 'modele.html',                   text: 'Modele de cereri' },
      { href: 'despre.html',                   text: 'Despre' },
    ];
    const more = [
      { href: 'petitie.html', text: 'Petiție' },
      { href: 'harta.html',   text: 'Harta firmelor' },
      { href: 'retele.html',  text: 'Rețele de firme' },
      { href: 'presa.html',   text: 'Pentru presă' },
      { href: 'https://transparenta.eu/entities/4420759', text: 'Date ANAF (transparenta.eu)', ext: true },
      { href: 'https://github.com/transparenta-locala/transparenta-pantelimon', text: 'Codul sursă (GitHub)', ext: true },
    ];
    const inSub = /\/(furnizori|semnale)\//.test(location.pathname);
    const isActive = l => {
      if (l.href === 'furnizori/index.html') return /\/furnizori\//.test(location.pathname);
      if (l.href === 'raport_transparenta.html' && /\/semnale\//.test(location.pathname)) return true;
      if (inSub) return false;
      return l.href.toLowerCase() === here || (here === '' && l.href === 'index.html');
    };
    const linkHTML = l => l.ext
      ? `<a href="${l.href}" target="_blank" rel="noopener">${l.text}</a>`
      : `<a href="${base}${l.href}"${isActive(l) ? ' class="active" aria-current="page"' : ''}>${l.text}</a>`;
    const linksHTML = links.map(linkHTML).join('');

    nav.style.position = 'sticky';
    nav.innerHTML = `
      <div class="tp-nav-inner">
        <a href="${base}index.html" class="tp-nav-brand">Transparența Pantelimon<small>Inițiativă civică</small></a>
        <button class="tp-hamburger" id="tp-hamburger" aria-label="Meniu" aria-expanded="false" aria-controls="tp-nav-links">
          <span></span><span></span><span></span>
        </button>
        <div class="tp-nav-links" id="tp-nav-links">
          ${linksHTML}
          <details class="tp-more"><summary>Mai mult</summary><div class="tp-more-list">${more.map(linkHTML).join('')}</div></details>
        </div>
        <button class="tp-theme-toggle" id="tp-theme-btn" aria-label="Comută temă luminoasă/întunecată" title="Temă luminoasă / întunecată"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 2a8 8 0 0 1 0 16z" fill="currentColor"/></svg></button>
      </div>
    `;
    document.body.insertBefore(nav, skipLink.nextSibling);
    bindNav(nav);
  }

  function bindNav(nav) {
    if (nav.dataset.tpBound) return;
    nav.dataset.tpBound = '1';
    nav.style.position = 'sticky';
    // Hamburger toggle
    const hamburgerBtn = document.getElementById('tp-hamburger');
    if (hamburgerBtn) {
      hamburgerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = nav.classList.toggle('open');
        hamburgerBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        // pe telefon, „Mai mult” se arată ca listă deschisă sub meniul principal
        const moreEl = nav.querySelector('.tp-more');
        if (moreEl) moreEl.open = isOpen;
      });
      document.addEventListener('click', (e) => {
        if (!nav.contains(e.target)) { nav.classList.remove('open'); hamburgerBtn.setAttribute('aria-expanded', 'false'); }
        const moreEl = nav.querySelector('.tp-more');
        if (moreEl && moreEl.open && !moreEl.contains(e.target) && !nav.classList.contains('open')) moreEl.open = false;
      });
      nav.querySelectorAll('.tp-nav-links a').forEach(a => {
        a.addEventListener('click', () => { nav.classList.remove('open'); hamburgerBtn.setAttribute('aria-expanded', 'false'); });
      });
    }

    // Toggle dark/light mode
    const themeBtn = nav.querySelector('#tp-theme-btn');
    if (themeBtn) themeBtn.addEventListener('click', () => {
      const cur = document.documentElement.dataset.tpTheme || 'light';
      const next = cur === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.tpTheme = next;
      try { localStorage.setItem('tp-theme', next); } catch (e) {}
    });
  }

  // ──────────────────────────────────────────────────────────────
  // §4.4 MAIN LANDMARK — id="main-content" pentru skip-link
  // ──────────────────────────────────────────────────────────────
  function injectMainId() {
    // Dacă există deja un element cu id="main-content" sau un <main>, nu facem nimic
    if (document.getElementById('main-content') || document.querySelector('main[id]')) return;
    const mainEl = document.querySelector('main');
    if (mainEl) { mainEl.id = 'main-content'; return; }
    // Fallback: prima div.page-wrap sau primul child al body după nav/banner
    const wrap = document.querySelector('.page-wrap, [role="main"], article, #content, #main');
    if (wrap) { wrap.id = 'main-content'; return; }
    // Ultimul fallback: primul sibling non-nav după nav
    const nav = document.querySelector('.tp-nav');
    const sibling = nav ? nav.nextElementSibling : document.body.firstElementChild;
    if (sibling && !sibling.id) sibling.id = 'main-content';
  }

  // ──────────────────────────────────────────────────────────────
  // BACK TO TOP
  // ──────────────────────────────────────────────────────────────
  function injectBackToTop() {
    const b = document.createElement('button');
    b.className = 'tp-back-top';
    b.setAttribute('aria-label', 'Înapoi sus');
    b.title = 'Înapoi sus';
    b.textContent = '↑';
    b.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    document.body.appendChild(b);
    window.addEventListener('scroll', () => {
      b.classList.toggle('visible', window.scrollY > 600);
    }, { passive: true });
  }

  // ──────────────────────────────────────────────────────────────
  // DETECȚIE CARDURI (raport_transparenta.html)
  // ──────────────────────────────────────────────────────────────
  function detectCards() {
    // Strategie 0 (NOUĂ, prioritară): clasa semantică explicită .tp-flag
    let cards = $$('.tp-flag[data-severity]');
    if (cards.length >= 5) return cards;

    // Strategie 1: <details> care conțin severitate
    cards = $$('details').filter(d => /CRITIC|MAJOR|MEDIU/.test(d.textContent));
    if (cards.length >= 5) return cards;

    // Strategie 2: orice element cu clasă conținând "card"/"nereg"/"issue"/"flag"
    cards = $$('[class*="card"], [class*="nereg"], [class*="issue"], [class*="flag"]')
      .filter(el => /CRITIC|MAJOR|MEDIU/.test(el.textContent) && el.children.length > 1);
    if (cards.length >= 5) return cards;

    // Strategie 3: căutăm părinții comuni ai textelor "**[CRITIC]**" etc.
    const markers = $$('strong, b').filter(el => /^(CRITIC|MAJOR|MEDIU)$/.test(el.textContent.trim()));
    if (markers.length >= 5) {
      // urcăm până găsim un container care nu mai conține alți markeri
      const seen = new Set();
      markers.forEach(m => {
        let p = m.parentElement;
        while (p && p !== document.body) {
          const inside = p.querySelectorAll('strong, b');
          let count = 0;
          inside.forEach(s => { if (/^(CRITIC|MAJOR|MEDIU)$/.test(s.textContent.trim())) count++; });
          if (count === 1) { seen.add(p); break; }
          p = p.parentElement;
        }
      });
      cards = Array.from(seen);
      if (cards.length >= 5) return cards;
    }

    return [];
  }

  function parseCard(el, idx) {
    // Cale rapidă: data attributes semantice (generate de monitor_pantelimon.py)
    if (el.dataset.severity) {
      const sumRaw = parseFloat(el.dataset.sumRon || '0') || 0;
      return {
        idx,
        el,
        severity: el.dataset.severity,
        title: (el.querySelector('[class*="flag-title"]') || el.querySelector('strong, b')
               )?.textContent.trim() || el.textContent.trim().slice(0, 80),
        supplier: el.dataset.supplier || '',
        supplierCif: el.dataset.supplierCif || '',
        sum: sumRaw,
        date: el.dataset.date || '',
        contract: el.dataset.contractId || '',
        procedure: el.dataset.procedure || '',
        type: el.dataset.type || '',
        isNew: el.dataset.new === '1',
        contracts: el.dataset.contracts || '',
        institutie: el.dataset.entity === 'institutie',
        haystack: el.textContent.toLowerCase().replace(/\s+/g, ' ').slice(0, 4000),
      };
    }

    // Cale veche (fallback regex) — pentru HTML generat fără data attributes
    const txt = el.textContent;
    let sev = 'MEDIU';
    if (/\bCRITIC\b/.test(txt))      sev = 'CRITIC';
    else if (/\bMAJOR\b/.test(txt))  sev = 'MAJOR';
    else if (/\bMEDIU\b/.test(txt))  sev = 'MEDIU';

    // Titlu: prima propoziție bold după marcajul de severitate (sau primul <strong>)
    let title = '';
    const strongs = el.querySelectorAll('strong, b');
    for (const s of strongs) {
      const t = s.textContent.trim();
      if (/^(CRITIC|MAJOR|MEDIU)$/.test(t)) continue;
      title = t; break;
    }
    if (!title) {
      const m = txt.match(/(?:CRITIC|MAJOR|MEDIU)\s*[\s\S]{0,3}([A-ZĂÎÂȘȚ][^\n.]{10,180})/);
      title = m ? m[1].trim() : '(fără titlu)';
    }

    // Suma — luăm cea mai mare valoare RON găsită
    const sumMatches = txt.match(/[\d.,]+\s*(?:mil(?:\.|ioane)?\s*)?(?:RON|lei)/gi) || [];
    let sum = 0;
    sumMatches.forEach(m => { const v = parseSum(m); if (v > sum) sum = v; });

    // Furnizor — după 🏢 sau "Firmă:"
    let supplier = '';
    const supMatch = txt.match(/(?:🏢|Firm[ăa]\s*:)\s*([^📅⚙️🔍🌐📊\n|]+)/);
    if (supMatch) {
      supplier = supMatch[1].trim()
        .replace(/^[:\-]\s*/, '')
        .replace(/\s+\|.*$/, '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    // Dată — pattern dd.mm.yyyy / yyyy-mm-dd / dd/mm/yyyy
    const dateMatch = txt.match(/(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}|\d{4}-\d{2}-\d{2})/);
    const date = dateMatch ? dateMatch[1] : '';

    // Cod contract — după 📋
    let contract = '';
    const cMatch = txt.match(/📋\s*([^💰🏢📅⚙️\n]+)/);
    if (cMatch) contract = cMatch[1].trim().replace(/\s+\|.*$/, '').replace(/\s+/g, ' ');

    return {
      idx,
      el,
      severity: sev,
      title,
      supplier,
      sum,
      date,
      contract,
      // tot textul minuscul, pentru search liber
      haystack: txt.toLowerCase().replace(/\s+/g, ' ').slice(0, 4000),
    };
  }

  // ──────────────────────────────────────────────────────────────
  // CITIRE DATE DIN <script id="tp-data"> (Faza 2-B)
  // ──────────────────────────────────────────────────────────────
  function loadDataFromJson() {
    const tag = document.getElementById('tp-data');
    if (!tag) return null;
    try {
      const data = JSON.parse(tag.textContent);
      if (!data.flags || !data.flags.length) return null;
      return data.flags.map((f, i) => ({
        idx: i,
        el: document.getElementById(f.anchor) || null,
        severity: f.severity || 'MEDIU',
        title: f.title || '',
        supplier: f.supplier || '',
        supplierCif: f.supplier_cif || '',
        sum: f.sum_ron || 0,
        date: f.date || '',
        contract: f.contract_id || '',
        procedure: f.procedure || '',
        type: f.type || '',
        haystack: ((f.title || '') + ' ' + (f.supplier || '') + ' ' +
                   (f.explanation || '') + ' ' + (f.contract_id || '')).toLowerCase(),
      })).filter(it => it.el).map(it => Object.assign(it, {
        isNew: it.el.dataset.new === '1',
        contracts: it.el.dataset.contracts || '',
        institutie: it.el.dataset.entity === 'institutie',
      }));
    } catch (e) {
      console.warn('[tp-enhance] tp-data invalid JSON, fallback la DOM parsing:', e);
      return null;
    }
  }

  // ──────────────────────────────────────────────────────────────
  // PAGINA RAPORT
  // ──────────────────────────────────────────────────────────────
  function enhanceReport() {
    // Idempotent: dacă toolbar-ul există deja, nu îl mai injectăm o dată
    // (altfel apar două bare de căutare și două seturi de chips, iar filtrele
    // se aplică doar pe unul dintre ele).
    if (document.querySelector('.tp-toolbar')) return;
    const cardEls = detectCards();
    if (!cardEls.length) {
    console.warn('[tp-enhance] Nu am detectat carduri de semnale. Toolbar-ul nu va fi inserat.');
      return;
    }

    // Indexare — preferă tp-data JSON (Faza 2-B), fallback la DOM parsing
    const jsonItems = loadDataFromJson();
    const items = jsonItems && jsonItems.length >= cardEls.length * 0.8
      ? jsonItems
      : cardEls.map((el, i) => parseCard(el, i));

    // Index de căutare normalizat (nume firme „murdare" din SEAP)
    indexSearchFields(items);

    // Butoane sesizare ANAP pe fiecare card
    injectAnapButtons(items);

    // Ancore + permalink
    items.forEach(item => {
      const id = 'nereguli-' + (item.idx + 1);
      item.el.id = id;
      // adăugăm un mic link "#" lângă titlul cardului
      const heading = item.el.querySelector('summary, strong, h3, h2');
      if (heading && !heading.querySelector('.tp-card-anchor')) {
        const a = document.createElement('a');
        a.className = 'tp-card-anchor';
        a.href = '#' + id;
        a.textContent = '#';
        a.title = 'Copiază link direct';
        a.addEventListener('click', (ev) => {
          ev.preventDefault();
          const url = location.origin + location.pathname + '#' + id;
          history.replaceState(null, '', '#' + id);
          if (navigator.clipboard) {
            navigator.clipboard.writeText(url).catch(() => {});
          }
          item.el.classList.add('tp-card-flash');
          setTimeout(() => item.el.classList.remove('tp-card-flash'), 1500);
        });
        heading.appendChild(a);
      }
    });

    // Listă unică de furnizori
    const supplierCounts = new Map();
    items.forEach(it => {
      // „Consiliul Local” (semnalele HCL) nu e o firmă — nu intră în lista de firme
      if (!it.supplier || it.institutie) return;
      const cur = supplierCounts.get(it.supplier) || { count: 0, sum: 0 };
      cur.count++; cur.sum += it.sum;
      supplierCounts.set(it.supplier, cur);
    });
    const suppliers = Array.from(supplierCounts.entries())
      .sort((a, b) => b[1].count - a[1].count);

    // State filtre
    const prefs = loadPrefs();
    const state = {
      q: '',
      qRaw: '',
      qTokens: [],
      sev: { CRITIC: true, MAJOR: true, MEDIU: true },
      supplier: '',
      sort: prefs.sort || 'idx-asc',
      shown: CFG.pageSize,
      _domReordered: false,  // true când DOM-ul a fost sortat (nu idx-asc)
      shellFilter: '',       // '' | 'zero-sal' | 'zero-ca' | 'ca-sub' | 'any-risk' | 'presa-risc'
      onlyNew: false,        // #noi — doar semnalele apărute la ultima analiză
    };

    // ─── TOOLBAR ──────────────────────────────────────────────
    const toolbar = document.createElement('div');
    toolbar.className = 'tp-toolbar';
    toolbar.setAttribute('role', 'search');
    toolbar.innerHTML = `
      <div class="tp-toolbar-inner">
        <div class="tp-toolbar-row">
          <input type="search" class="tp-search" id="tp-q"
                 placeholder="Caută o firmă, un CUI sau ce s-a cumpărat"
                 aria-label="Caută în semnalele automate">
          <div class="tp-chips-sev">
            <button class="tp-chip active" data-sev="CRITIC" aria-pressed="true">${CFG.sevLabel.CRITIC}</button>
            <button class="tp-chip active" data-sev="MAJOR"  aria-pressed="true">${CFG.sevLabel.MAJOR}</button>
            <button class="tp-chip active" data-sev="MEDIU"  aria-pressed="true">${CFG.sevLabel.MEDIU}</button>
          </div>
        </div>
        <div class="tp-toolbar-row">
          <select class="tp-select" id="tp-supplier" aria-label="Filtrează după furnizor">
            <option value="">Toate firmele cu semnale (${suppliers.length})</option>
            ${suppliers.map(([name, info]) =>
              `<option value="${escapeHTML(name)}">${escapeHTML(name)} (${info.count})</option>`
            ).join('')}
          </select>
          <select class="tp-select" id="tp-sort" aria-label="Sortare">
            <option value="idx-asc">Sortare: ordinea originală</option>
            <option value="sev-asc">Severitate (CRITIC întâi)</option>
            <option value="sum-desc">Sumă (mare → mic)</option>
            <option value="sum-asc">Sumă (mic → mare)</option>
            <option value="supplier-asc">Furnizor (A → Z)</option>
            <option value="date-desc">Dată (recent → vechi)</option>
          </select>
          <button class="tp-btn" id="tp-export-csv" title="Descarcă rezultatele filtrate ca CSV">Descarcă CSV</button>
          <button class="tp-btn" id="tp-export-json" title="Descarcă rezultatele filtrate ca JSON">JSON</button>
          <button class="tp-btn" id="tp-reset" title="Curăță toate filtrele">Resetează filtrele</button>
        </div>
        <div class="tp-toolbar-row" id="tp-shell-row">
          <span style="font-size:.85rem;color:var(--tp-muted);margin-right:.25rem">Profilul firmei:</span>
          <button class="tp-chip" data-shell="zero-sal" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are 0 angajați declarați la ANAF">0 angajați</button>
          <button class="tp-chip" data-shell="zero-ca" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are cifra de afaceri 0 RON">Cifră de afaceri 0</button>
          <button class="tp-chip" data-shell="ca-sub" aria-pressed="false"
                  title="Arată semnale unde cifra de afaceri a furnizorului e sub 50% din valoarea contractului">Cifra de afaceri sub contract</button>
          <button class="tp-chip" data-shell="any-risk" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are cel puțin un indicator de risc financiar">Orice indicator</button>
          <button class="tp-chip" data-shell="presa-risc" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are mențiuni de risc detectate automat în presă" style="display:none">În presă</button>
        </div>
        <div class="tp-toolbar-row">
          <div class="tp-stats" id="tp-stats" aria-live="polite"></div>
        </div>
      </div>
    `;

    // ─── ÎMBOGĂȚIRE ITEMS CU DATE RISC FIRMĂ ─────────────────
    // Citim scorul de risc din #risc-firma-data (generat de monitor_pantelimon.py)
    // Fallback: .supplier-risk-panel (mecanism vechi, nefolosit în generatorul curent)
    let riscFirmaLookup = {};
    try {
      const riscTag = document.getElementById('risc-firma-data');
      if (riscTag) riscFirmaLookup = JSON.parse(riscTag.textContent) || {};
    } catch(e) { /* risc-firma-data absent sau JSON invalid */ }

    items.forEach(it => {
      if (!it.el) { it.riskCount = 0; it.riskText = ''; return; }
      // Cale 1: #risc-firma-data JSON (sursă preferată)
      const rd = riscFirmaLookup[it.supplier];
      if (rd) {
        it.riskCount = rd.scor || 0;
        it.riskText  = (rd.flags || [])
          .map(f => (f.tip + ' ' + (f.titlu || '')).toUpperCase()).join(' ');
        return;
      }
      // Cale 2: .supplier-risk-panel inline (fallback legacy)
      const panel = it.el.querySelector('.supplier-risk-panel');
      if (panel) {
        it.riskCount = parseInt(panel.dataset.riskCount || '0', 10) || 0;
        it.riskText  = panel.textContent.toUpperCase();
        return;
      }
      it.riskCount = 0;
      it.riskText  = '';
    });

    // Afișăm rândul de filtre shell dacă există date de risc (any-risk funcționează)
    const hasRiscData = Object.keys(riscFirmaLookup).length > 0 ||
                        !!document.querySelector('.supplier-risk-panel');
    if (hasRiscData) {
      const shellRow = toolbar.querySelector('#tp-shell-row');
      if (shellRow) shellRow.style.display = '';

      // Calculăm câte nereguli ar match fiecare chip financiar
      // Dacă 0 → dezactivăm chip-ul și afișăm tooltip clar
      const cntZeroSal = items.filter(it =>
        it.riskText.includes('ZERO ANGAJATI') || it.riskText.includes('PUTINI ANGAJATI')
      ).length;
      const cntZeroCa = items.filter(it =>
        it.riskText.includes('CIFRA AFACERI ZERO') || it.riskText.includes('CIFRA AFACERI MULT SUB')
      ).length;
      const cntCaSub = items.filter(it =>
        it.riskText.includes('CIFRA AFACERI SUB CONTRACT') && !it.riskText.includes('MULT SUB')
      ).length;
      const cntAnyRisk = items.filter(it => it.riskCount > 0).length;

      const btnZeroSal  = toolbar.querySelector('[data-shell="zero-sal"]');
      const btnZeroCa   = toolbar.querySelector('[data-shell="zero-ca"]');
      const btnCaSub    = toolbar.querySelector('[data-shell="ca-sub"]');
      const btnAnyRisk  = toolbar.querySelector('[data-shell="any-risk"]');
      const btnPresaRisc = toolbar.querySelector('[data-shell="presa-risc"]');

      // Chip "📰 În presă"
      const cntPresaRisc = items.filter(it =>
        it.riskText.includes('MENTIUNI PRESA')
      ).length;
      if (btnPresaRisc) {
        if (cntPresaRisc === 0) {
          btnPresaRisc.style.display = 'none';
        } else {
          btnPresaRisc.style.display = '';
          btnPresaRisc.innerHTML = `📰 În presă <span class="tp-chip-cnt">(${cntPresaRisc})</span>`;
          btnPresaRisc.title = `Furnizori cu mențiuni de risc detectate automat în presă — ${cntPresaRisc} nereguli`;
        }
      }

      if (btnZeroSal) {
        if (cntZeroSal === 0) {
          btnZeroSal.disabled = true;
          btnZeroSal.style.opacity = '.4';
          btnZeroSal.style.cursor = 'not-allowed';
          btnZeroSal.title = 'Datele privind salariații nu sunt încă integrate (situații financiare ANAF).\nConform Legii 544/2001, primăria are obligația să publice date despre contractele atribuite.';
          btnZeroSal.innerHTML = '👥 0 angajați <span style="font-size:.72em;opacity:.7">(date în pregătire)</span>';
        } else {
          const hasZeroExact = items.some(it =>
            it.riskText.includes('ZERO ANGAJATI') && !it.riskText.includes('PUTINI ANGAJATI'));
          btnZeroSal.innerHTML = (hasZeroExact ? '👥 0 angajați' : '👥 ≤2 angajați')
            + ` <span class="tp-chip-cnt">(${cntZeroSal})</span>`;
          btnZeroSal.title = `Furnizori cu personal redus sau zero angajați la ANAF — ${cntZeroSal} nereguli`;
        }
      }
      if (btnZeroCa) {
        if (cntZeroCa === 0) {
          btnZeroCa.disabled = true;
          btnZeroCa.style.opacity = '.4';
          btnZeroCa.style.cursor = 'not-allowed';
          btnZeroCa.title = 'Datele privind cifra de afaceri nu sunt încă integrate (situații financiare ANAF).\nConform Legii 544/2001, primăria are obligația să publice date despre contractele atribuite.';
          btnZeroCa.innerHTML = '📉 CA = 0 RON <span style="font-size:.72em;opacity:.7">(date în pregătire)</span>';
        } else {
          const hasZeroExact = items.some(it => it.riskText.includes('CIFRA AFACERI ZERO'));
          btnZeroCa.innerHTML = (hasZeroExact ? '📉 CA = 0 RON' : '📉 CA << contract')
            + ` <span class="tp-chip-cnt">(${cntZeroCa})</span>`;
          btnZeroCa.title = `Cifra de afaceri zero sau mult sub valoarea contractului (< 10%) — ${cntZeroCa} nereguli`;
        }
      }
      if (btnCaSub) {
        if (cntCaSub === 0) {
          btnCaSub.style.display = 'none';
        } else {
          btnCaSub.innerHTML = `📊 CA sub contract <span class="tp-chip-cnt">(${cntCaSub})</span>`;
          btnCaSub.title = `Cifra de afaceri sub 50% din valoarea contractului — ${cntCaSub} nereguli`;
        }
      }
      if (btnAnyRisk) {
        if (cntAnyRisk === 0) {
          btnAnyRisk.disabled = true;
          btnAnyRisk.style.opacity = '.4';
          btnAnyRisk.style.cursor = 'not-allowed';
        } else {
          btnAnyRisk.innerHTML = `⚠️ Orice risc <span class="tp-chip-cnt">(${cntAnyRisk})</span>`;
          btnAnyRisk.title = `Orice indicator de risc financiar — ${cntAnyRisk} nereguli`;
        }
      }
    }

    // ─── MINI-BADGES FINANCIARE ──────────────────────────────────────────────
    // Injectăm un rând discret cu date angajați/CA sub header-ul fiecărui card.
    // NOTĂ: trebuie să fie DUPĂ inițializarea riscFirmaLookup (linia ~733).
    const FIN_BADGE_TIPS = ['ZERO ANGAJATI','FOARTE PUTINI ANGAJATI',
                            'CIFRA AFACERI ZERO','CIFRA AFACERI MULT SUB CONTRACT',
                            'CIFRA AFACERI SUB CONTRACT'];
    items.forEach(it => {
      if (!it.el || !it.supplier) return;
      const rd = riscFirmaLookup[it.supplier];
      if (!rd || !(rd.flags || []).length) return;
      if (it.el.querySelector('.tp-fin-badge')) return;
      const finFlags = rd.flags.filter(f => FIN_BADGE_TIPS.includes(f.tip));
      if (!finFlags.length) return;
      const parts = [];
      const salFlag = finFlags.find(f => f.tip.includes('ANGAJATI'));
      const caFlag  = finFlags.find(f => f.tip.includes('AFACERI'));
      if (salFlag) {
        if (salFlag.tip === 'ZERO ANGAJATI') {
          parts.push('👥 0 angajați ANAF');
        } else {
          const m = (salFlag.titlu || '').match(/^(\d+)/);
          const n = m ? m[1] : '≤2';
          parts.push(`👥 ${n} angajat${n === '1' ? '' : 'i'} ANAF`);
        }
      }
      if (caFlag) {
        const mCA = (caFlag.titlu || '').match(/([\d\s,.]+)\s*RON/i);
        const caStr = mCA ? mCA[1].trim() : '?';
        if (caFlag.tip === 'CIFRA AFACERI ZERO')    parts.push('📉 CA = 0 RON');
        else if (caFlag.tip.includes('MULT'))        parts.push(`📉 CA ${caStr} RON (sub 10% contract)`);
        else                                         parts.push(`📉 CA ${caStr} RON (sub 50% contract)`);
      }
      if (!parts.length) return;
      const badge = document.createElement('div');
      badge.className = 'tp-fin-badge';
      badge.setAttribute('aria-label', 'Date financiare ANAF 2024');
      badge.innerHTML = parts.map(p => `<span class="tp-fb-item">${p}</span>`).join('');
      const headerDiv = it.el.querySelector('div');
      if (headerDiv) headerDiv.insertAdjacentElement('afterend', badge);
    });

    // ─── SUMMARY WIDGET ───────────────────────────────────────
    // Rezumatul e generat static de monitor (cu linkuri spre fișele firmelor și
    // valori pe contracte distincte); îl construim aici doar pentru rapoartele vechi.
    const summaryStatic = $('.tp-summary');
    const summary = summaryStatic || buildSummaryWidget(items, suppliers);
    if (summaryStatic) bindSummaryFilters(summaryStatic);

    // Toolbar-ul ia locul rezervat în pagină (#tp-toolbar-slot) — fără „săritură”
    const firstCard = cardEls[0];
    const anchor = firstCard.parentElement;
    const slot = $('#tp-toolbar-slot');
    if (slot) slot.replaceWith(toolbar); else anchor.insertBefore(toolbar, firstCard);
    if (!summary.isConnected) anchor.insertBefore(summary, firstCard);

    // Container "load more" + empty state, după ultimul card
    const lastCard = cardEls[cardEls.length - 1];
    const loadMore = document.createElement('div');
    loadMore.className = 'tp-loadmore';
    loadMore.innerHTML = `<button class="tp-btn tp-btn-primary" id="tp-load-more">Încarcă încă ${CFG.pageSize} →</button>`;
    lastCard.parentElement.insertBefore(loadMore, lastCard.nextSibling);

    // Sentinel invizibil — marchează poziția originală a cardurilor în DOM
    // Folosit de applyFilters pentru insertBefore în loc de appendChild (care muta itemii la finalul wrap-ului)
    const tpRestoreRef = document.createElement('span');
    tpRestoreRef.style.cssText = 'display:none';
    tpRestoreRef.setAttribute('data-tp-ref', '1');
    loadMore.parentElement.insertBefore(tpRestoreRef, loadMore);

    const empty = document.createElement('div');
    empty.className = 'tp-empty tp-card-hidden';
    empty.id = 'tp-empty';
    empty.innerHTML = `<p>🤷 Niciun rezultat pentru filtrele curente.</p>
      <button class="tp-btn" onclick="document.getElementById('tp-reset').click()">Curăță filtrele</button>`;
    loadMore.parentElement.insertBefore(empty, loadMore);

    // Setăm sortarea salvată
    $('#tp-sort').value = state.sort;

    // ─── EVENT BINDING ────────────────────────────────────────
    const apply = debounce(() => applyFilters(items, state), 80);

    $('#tp-q').addEventListener('input', (e) => {
      setQuery(state, e.target.value);
      state.shown = CFG.pageSize;
      apply();
    });
    // Chips severitate. Comportament intuitiv: din starea „toate pornite",
    // un click IZOLEAZĂ severitatea aleasă (nu o ascunde, cum se întâmpla
    // înainte). Click-urile următoare adaugă/scot severități; dacă rămâne
    // niciuna, revenim la toate.
    const SEVS = ['CRITIC', 'MAJOR', 'MEDIU'];
    function syncSevChips() {
      toolbar.querySelectorAll('.tp-chip[data-sev]').forEach(c => {
        const on = !!state.sev[c.dataset.sev];
        c.classList.toggle('active', on);
        c.setAttribute('aria-pressed', on ? 'true' : 'false');
        c.title = on ? 'Afișat — click pentru a ascunde' : 'Ascuns — click pentru a afișa';
      });
    }
    toolbar.querySelectorAll('.tp-chip[data-sev]').forEach(chip => {
      chip.addEventListener('click', () => {
        const s = chip.dataset.sev;
        const allOn = SEVS.every(x => state.sev[x]);
        if (allOn) {
          SEVS.forEach(x => { state.sev[x] = (x === s); });   // izolează
        } else {
          state.sev[s] = !state.sev[s];
          if (!SEVS.some(x => state.sev[x])) SEVS.forEach(x => { state.sev[x] = true; });
        }
        syncSevChips();
        state.shown = CFG.pageSize;
        apply();
      });
    });
    toolbar.querySelectorAll('.tp-chip[data-shell]').forEach(chip => {
      chip.addEventListener('click', () => {
        const s = chip.dataset.shell;
        const isActive = state.shellFilter === s;
        // Toggle: click activ → dezactivare; click inactiv → activare (exclusiv)
        state.shellFilter = isActive ? '' : s;
        toolbar.querySelectorAll('.tp-chip[data-shell]').forEach(c => {
          c.classList.toggle('active', c.dataset.shell === state.shellFilter);
          c.setAttribute('aria-pressed', c.dataset.shell === state.shellFilter ? 'true' : 'false');
        });
        state.shown = CFG.pageSize;
        apply();
      });
    });
    $('#tp-supplier').addEventListener('change', (e) => {
      state.supplier = e.target.value;
      state.shown = CFG.pageSize;
      apply();
    });
    $('#tp-sort').addEventListener('change', (e) => {
      state.sort = e.target.value;
      savePrefs({ ...loadPrefs(), sort: state.sort });
      apply();
    });
    $('#tp-reset').addEventListener('click', () => {
      setQuery(state, ''); state.supplier = ''; state.shellFilter = ''; state.onlyNew = false;
      state.sev = { CRITIC: true, MAJOR: true, MEDIU: true };
      state.shown = CFG.pageSize;
      $('#tp-q').value = '';
      $('#tp-supplier').value = '';
      syncSevChips();
      toolbar.querySelectorAll('.tp-chip[data-shell]').forEach(c => {
        c.classList.remove('active');
        c.setAttribute('aria-pressed', 'false');
      });
      apply();
    });
    toolbar.querySelector('#tp-stats').addEventListener('click', (e) => {
      if (e.target.id !== 'tp-show-all') return;
      e.preventDefault();
      state.onlyNew = false;
      history.replaceState(null, '', location.pathname + location.search);
      apply();
    });
    // Linkul „N semnale noi” din banda de sus, apăsat chiar pe pagina raportului
    window.addEventListener('hashchange', () => {
      if (location.hash !== '#noi') return;
      state.onlyNew = items.some(it => it.isNew);
      state.shown = CFG.pageSize;
      apply();
      toolbar.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    $('#tp-export-csv').addEventListener('click', () => exportCSV(items, state));
    $('#tp-export-json').addEventListener('click', () => exportJSON(items, state));
    // Toolbar sticky top — calculat dinamic după înălțimea nav
    function updateToolbarTop() {
      const navEl = document.querySelector('.tp-nav');
      const toolbarEl = document.querySelector('.tp-toolbar');
      if (navEl && toolbarEl) toolbarEl.style.top = navEl.offsetHeight + 'px';
    }
    updateToolbarTop();
    window.addEventListener('resize', updateToolbarTop);
    const navObs = new ResizeObserver(updateToolbarTop);
    const navElObs = document.querySelector('.tp-nav');
    if (navElObs) navObs.observe(navElObs);

    $('#tp-load-more').addEventListener('click', () => {
      const firstHidden = items.find(it => it.el.classList.contains('tp-card-hidden'));
      state.shown += CFG.pageSize;
      apply();
      if (firstHidden) requestAnimationFrame(() => firstHidden.el.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    });

    // Scurtături tastatură: "/" focus search, Esc clear
    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea, select')) {
        if (e.key === 'Escape' && e.target.id === 'tp-q') {
          e.target.value = '';
          setQuery(state, '');
          apply();
        }
        return;
      }
      if (e.key === '/') {
        e.preventDefault();
        $('#tp-q').focus();
      }
    });

    // Aplicăm hash din URL (dacă există filtre / ancoră)
    applyHash(items, state);
    // Cardurile de după primele 25 vin ascunse din HTML (tp-pre-hidden); de aici
    // le gestionează paginarea. Același cadru de desenare → nimic nu clipește.
    items.forEach(it => it.el.classList.remove('tp-pre-hidden'));
    applyFilters(items, state);

    // Dacă URL conține #nereguli-X, scrollăm acolo după render
    if (/^#nereguli-\d+$/.test(location.hash)) {
      requestAnimationFrame(() => {
        const t = document.getElementById(location.hash.slice(1));
        if (t) {
          state.shown = Math.max(state.shown,
            (items.find(i => i.el === t)?.idx || 0) + 5);
          apply();
          t.scrollIntoView({ behavior: 'smooth', block: 'start' });
          t.classList.add('tp-card-flash');
          setTimeout(() => t.classList.remove('tp-card-flash'), 1500);
        }
      });
    }
  }

  function applyHash(items, state) {
    // Permite #q=foo&sev=CRITIC&supplier=BAR în URL
    let h = location.hash.replace(/^#/, '');
    // ?q=… vine din formularul de căutare de pe prima pagină când JS-ul ei nu rulează
    const qs = new URLSearchParams(location.search).get('q');
    if (!h.includes('=') && qs) h = 'q=' + encodeURIComponent(qs);
    if (h === 'noi') { state.onlyNew = items.some(it => it.isNew); return; }
    if (!h.includes('=')) return;
    const params = new URLSearchParams(h);
    if (params.has('q')) {
      setQuery(state, params.get('q'));
      const inp = $('#tp-q'); if (inp) inp.value = params.get('q');
    }
    if (params.has('sev')) {
      const sevs = params.get('sev').split(',').map(s => s.toUpperCase());
      ['CRITIC','MAJOR','MEDIU'].forEach(s => {
        state.sev[s] = sevs.includes(s);
        const chip = document.querySelector(`.tp-chip[data-sev="${s}"]`);
        if (chip) {
          chip.classList.toggle('active', state.sev[s]);
          chip.setAttribute('aria-pressed', state.sev[s] ? 'true' : 'false');
        }
      });
    }
    if (params.has('supplier')) {
      state.supplier = params.get('supplier');
      const sel = $('#tp-supplier'); if (sel) sel.value = state.supplier;
    }
  }

  function applyFilters(items, state) {
    // 1. Filtru
    let visible = items.filter(it => {
      if (state.onlyNew && !it.isNew) return false;
      if (!state.sev[it.severity]) return false;
      if (state.supplier && it.supplier !== state.supplier) return false;
      if (!matchesQuery(it, state)) return false;
      // Filtre shell company (bazate pe panelul risc_firma.py)
      if (state.shellFilter) {
        const f = state.shellFilter;
        if (f === 'any-risk'  && it.riskCount <= 0) return false;
        if (f === 'zero-sal'  && !(it.riskText.includes('ZERO ANGAJATI') ||
                                    it.riskText.includes('PUTINI ANGAJATI'))) return false;
        if (f === 'zero-ca'   && !(it.riskText.includes('CIFRA AFACERI ZERO') ||
                                    it.riskText.includes('AFACERI MULT SUB'))) return false;
        if (f === 'ca-sub'    && !(it.riskText.includes('CIFRA AFACERI SUB CONTRACT') &&
                                    !it.riskText.includes('MULT SUB'))) return false;
        if (f === 'presa-risc' && !it.riskText.includes('MENTIUNI PRESA')) return false;
      }
      return true;
    });

    // 2. Sortare
    const cmp = {
      'idx-asc':       (a, b) => a.idx - b.idx,
      'sev-asc':       (a, b) => CFG.severityOrder[a.severity] - CFG.severityOrder[b.severity] || a.idx - b.idx,
      'sum-desc':      (a, b) => b.sum - a.sum,
      'sum-asc':       (a, b) => a.sum - b.sum,
      'supplier-asc':  (a, b) => (a.supplier || 'zzz').localeCompare(b.supplier || 'zzz', 'ro'),
      'date-desc':     (a, b) => (b.date || '').localeCompare(a.date || ''),
    }[state.sort] || ((a, b) => a.idx - b.idx);

    const sorted = visible.slice().sort(cmp);

    // 3. Reordonare DOM (doar dacă sortarea diferă de idx-asc)
    // BUG FIX: folosim insertBefore(item, tpRestoreRef) în loc de appendChild(item)
    // appendChild muta TOȚI itemii la finalul div.wrap (după statistici), spărgând paginarea.
    const tpRef = document.querySelector('[data-tp-ref]');
    const tpParent = tpRef ? tpRef.parentElement : items[0].el.parentElement;
    if (state.sort !== 'idx-asc') {
      state._domReordered = true;
      sorted.forEach(it => tpParent.insertBefore(it.el, tpRef));
    } else if (state._domReordered) {
      // Restaurăm ordinea originală NUMAI dacă am sortat anterior
      state._domReordered = false;
      items.slice().sort((a, b) => a.idx - b.idx).forEach(it => tpParent.insertBefore(it.el, tpRef));
    }
    // else: idx-asc fără reordonare anterioară — nu mișcăm nimic, elementele sunt deja în ordine

    // 4. Show/hide + paginare
    const visibleSet = new Set(sorted.slice(0, state.shown).map(it => it.el));
    items.forEach(it => {
      it.el.classList.toggle('tp-card-hidden', !visibleSet.has(it.el));
    });

    // 5. Stats — valoarea contractelor DISTINCTE (un contract cu 4 semnale se
    // numără o dată; înainte se adunau sumele semnalelor: 245 mil. vs 167 mil. total)
    const totalSum = sumaContracteDistincte(visible);
    const byS = visible.reduce((acc, it) => {
      acc[it.severity] = (acc[it.severity] || 0) + 1; return acc;
    }, {});
    const stats = $('#tp-stats');
    if (stats) {
      stats.innerHTML = `
      <span><strong>${visible.length}</strong> / ${items.length} semnale afișate</span>
        <span>CRITIC: <strong>${byS.CRITIC || 0}</strong>, MAJOR: <strong>${byS.MAJOR || 0}</strong>, MEDIU: <strong>${byS.MEDIU || 0}</strong></span>
        <span title="Fiecare contract numărat o singură dată, chiar dacă are mai multe semnale">Contracte implicate: <strong>${fmtRON(totalSum)}</strong></span>
        ${state.onlyNew ? `<span>Doar semnalele noi · <a href="#" id="tp-show-all">arată toate</a></span>` : ''}
        ${state.shown < visible.length ? `<span style="color: var(--tp-muted)">Vizibile primele ${Math.min(state.shown, visible.length)}</span>` : ''}
      `;
    }

    // 6. Load more / empty
    const lm = $('#tp-load-more');
    if (lm) {
      const rest = visible.length - state.shown;
      if (rest > 0) {
        lm.parentElement.classList.remove('tp-card-hidden');
        lm.textContent = `Încarcă încă ${Math.min(rest, CFG.pageSize)} (rămase: ${rest}) →`;
      } else {
        lm.parentElement.classList.add('tp-card-hidden');
      }
    }
    const emp = $('#tp-empty');
    if (emp) {
      emp.classList.toggle('tp-card-hidden', visible.length > 0);
      if (!visible.length) renderEmptyState(emp, items, state);
    }
  }

  // Stare goală utilă: spune CE filtru a dat zero și propune firme apropiate.
  // (Înainte afișa doar „🤷 Niciun rezultat", ceea ce părea că firma nu există.)
  function renderEmptyState(emp, items, state) {
    const sugg = state.qTokens && state.qTokens.length
      ? suggestSuppliers(items, state, 5) : [];
    const sevOff = ['CRITIC', 'MAJOR', 'MEDIU'].filter(s => !state.sev[s]);
    let html = '';

    if (state.qRaw) {
      html += `<p>🤷 Niciun rezultat pentru <strong>„${escapeHTML(state.qRaw)}"</strong>.</p>`;
    } else {
      html += '<p>🤷 Niciun rezultat pentru filtrele curente.</p>';
    }

    if (sugg.length) {
      html += '<p style="font-size:.9rem">Ai vrut să spui:</p><div class="tp-suggest">'
        + sugg.map(name =>
            `<button class="tp-btn tp-suggest-btn" data-suggest="${escapeHTML(name)}">${escapeHTML(name)}</button>`
          ).join('')
        + '</div>';
    } else if (state.qRaw) {
      html += '<p style="font-size:.85rem;color:var(--tp-muted)">'
        + 'Caută după o parte din nume (ex. <code>dav</code> sau <code>garden</code>), '
        + 'după CUI, sau după codul contractului. Sufixele SRL / S.A. sunt ignorate automat.</p>';
    }

    if (sevOff.length) {
      html += `<p style="font-size:.85rem;color:var(--tp-muted)">Filtre de severitate dezactivate: `
        + `${sevOff.join(', ')}. Rezultatele de acest tip sunt ascunse.</p>`;
    }
    if (state.supplier) {
      html += `<p style="font-size:.85rem;color:var(--tp-muted)">Filtrat pe furnizorul `
        + `<strong>${escapeHTML(state.supplier)}</strong>.</p>`;
    }

    html += '<button class="tp-btn" id="tp-empty-reset">Curăță filtrele</button>';
    emp.innerHTML = html;

    const rst = emp.querySelector('#tp-empty-reset');
    if (rst) rst.addEventListener('click', () => {
      const r = document.getElementById('tp-reset'); if (r) r.click();
    });
    emp.querySelectorAll('[data-suggest]').forEach(btn => {
      btn.addEventListener('click', () => {
        const inp = $('#tp-q');
        if (inp) { inp.value = btn.dataset.suggest; }
        setQuery(state, btn.dataset.suggest);
        state.shown = CFG.pageSize;
        applyFilters(items, state);
      });
    });
  }

  // ──────────────────────────────────────────────────────────────
  // EXPORT
  // ──────────────────────────────────────────────────────────────
  function getFiltered(items, state) {
    return items.filter(it => {
      if (!state.sev[it.severity]) return false;
      if (state.supplier && it.supplier !== state.supplier) return false;
      if (!matchesQuery(it, state)) return false;
      return true;
    });
  }

  function exportCSV(items, state) {
    const data = getFiltered(items, state);
    const cols = ['nr', 'severitate', 'titlu', 'furnizor', 'suma_RON', 'data', 'cod_contract', 'link'];
    const rows = data.map(it => [
      it.idx + 1,
      it.severity,
      it.title,
      it.supplier,
      it.sum,
      it.date,
      it.contract,
      location.origin + location.pathname + '#nereguli-' + (it.idx + 1),
    ]);
    const csv = [cols.join(',')].concat(
      rows.map(r => r.map(v => {
        const s = String(v == null ? '' : v).replace(/"/g, '""');
        return /[",\n;]/.test(s) ? `"${s}"` : s;
      }).join(','))
    ).join('\n');
    download(csv, 'nereguli-pantelimon.csv', 'text/csv;charset=utf-8');
  }

  function exportJSON(items, state) {
    const data = getFiltered(items, state).map(it => ({
      nr: it.idx + 1,
      severitate: it.severity,
      titlu: it.title,
      furnizor: it.supplier,
      suma_RON: it.sum,
      data: it.date,
      cod_contract: it.contract,
      link: location.origin + location.pathname + '#nereguli-' + (it.idx + 1),
    }));
    const payload = {
      sursa: location.href,
      generat_la: new Date().toISOString(),
      total: data.length,
      filtru: { q: state.q, severitate: state.sev, furnizor: state.supplier, sortare: state.sort },
      nereguli: data,
    };
    download(JSON.stringify(payload, null, 2), 'nereguli-pantelimon.json', 'application/json');
  }

  function download(content, filename, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
  }

  // ──────────────────────────────────────────────────────────────
  // SUMMARY WIDGET
  // ──────────────────────────────────────────────────────────────
  function buildSummaryWidget(items, suppliers) {
    const wrap = document.createElement('section');
    wrap.className = 'tp-summary';
    wrap.setAttribute('aria-label', 'Rezumat statistici');

    // Severitate
    const sevCount = { CRITIC: 0, MAJOR: 0, MEDIU: 0 };
    items.forEach(it => sevCount[it.severity]++);
    const total = items.length || 1;

    // Top furnizori după număr
    const topByCount = suppliers.slice(0, 10);
    // Top furnizori după valoare
    const topByValue = suppliers.slice().sort((a, b) => b[1].sum - a[1].sum).slice(0, 10);

    wrap.innerHTML = `
      <h3>Rezumat: ${items.length} semnale automate</h3>
      <div class="tp-summary-bar" aria-label="Distribuție pe severități">
        <span style="background:${CFG.severityColor.CRITIC}; width:${(sevCount.CRITIC/total*100).toFixed(1)}%">
          ${sevCount.CRITIC > 5 ? sevCount.CRITIC : ''}
        </span>
        <span style="background:${CFG.severityColor.MAJOR}; width:${(sevCount.MAJOR/total*100).toFixed(1)}%">
          ${sevCount.MAJOR > 5 ? sevCount.MAJOR : ''}
        </span>
        <span style="background:${CFG.severityColor.MEDIU}; width:${(sevCount.MEDIU/total*100).toFixed(1)}%">
          ${sevCount.MEDIU > 5 ? sevCount.MEDIU : ''}
        </span>
      </div>
      <div class="tp-summary-grid" style="margin-top:1rem">
        <div>
          <strong style="font-size:.9rem">Firmele cu cele mai multe semnale</strong>
          <div class="tp-summary-list" style="margin-top:.5rem">
            ${topByCount.map(([name, info]) => `
              <div class="tp-summary-li">
                <button class="tp-link-btn" data-supplier="${escapeHTML(name)}"
                        style="background:none;border:0;color:var(--tp-link);cursor:pointer;text-align:left;padding:0;font:inherit">
                  ${escapeHTML(name)}
                </button>
                <span><strong>${info.count}</strong> <span class="tp-muted">${fmtRON(info.sum)}</span></span>
              </div>
            `).join('') || '<div class="tp-muted">—</div>'}
          </div>
        </div>
        <div>
          <strong style="font-size:.9rem">Firmele cu cea mai mare valoare semnalată</strong>
          <div class="tp-summary-list" style="margin-top:.5rem">
            ${topByValue.map(([name, info]) => `
              <div class="tp-summary-li">
                <button class="tp-link-btn" data-supplier="${escapeHTML(name)}"
                        style="background:none;border:0;color:var(--tp-link);cursor:pointer;text-align:left;padding:0;font:inherit">
                  ${escapeHTML(name)}
                </button>
                <span><strong>${fmtRON(info.sum)}</strong> <span class="tp-muted">${info.count} ctr.</span></span>
              </div>
            `).join('') || '<div class="tp-muted">—</div>'}
          </div>
        </div>
      </div>
    `;

    // Click pe furnizor → filtrăm
    wrap.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-supplier]');
      if (!btn) return;
      const sel = $('#tp-supplier');
      if (sel) {
        sel.value = btn.dataset.supplier;
        sel.dispatchEvent(new Event('change'));
        sel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });

    return wrap;
  }

  // ──────────────────────────────────────────────────────────────
  // WEBVIEW DETECTION + MAILTO FALLBACK
  // ──────────────────────────────────────────────────────────────
  function isWebView() {
    var ua = navigator.userAgent || '';
    return /FBAN|FBAV|Instagram|Line\/|Snapchat|Twitter|MicroMessenger|WebView|wv\)/i.test(ua);
  }

  function showMailtoModal(emailTo, subject, bodyText, webUrl) {
    var existing = document.querySelector('.tp-mailto-modal-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'tp-mailto-modal-overlay';
    var subjectDecoded = decodeURIComponent(subject);
    var bodyDecoded = decodeURIComponent(bodyText);

    overlay.innerHTML = '<div class="tp-mailto-modal">'
      + '<button class="tp-mailto-modal-close" aria-label="Închide">×</button>'
      + '<h3>Sesizare — ' + emailTo + '</h3>'
      + '<div class="tp-mailto-field"><label>Destinatar</label>'
      + '<input type="text" value="' + emailTo + '" readonly></div>'
      + '<div class="tp-mailto-field"><label>Subiect</label>'
      + '<input type="text" value="' + subjectDecoded.replace(/"/g, '&quot;') + '" readonly></div>'
      + '<div class="tp-mailto-field"><label>Text sesizare (editabil)</label>'
      + '<textarea rows="10">' + bodyDecoded.replace(/</g, '&lt;') + '</textarea></div>'
      + '<div class="tp-mailto-actions">'
      + '<button class="tp-mailto-copy" data-action="copy">Copiază textul</button>'
      + (webUrl ? '<a class="tp-mailto-web" href="' + webUrl + '" target="_blank" rel="noopener noreferrer">Deschide formularul online</a>' : '')
      + '<a class="tp-mailto-email" href="mailto:' + emailTo + '?subject=' + subject + '&body=' + bodyText + '">Deschide în email</a>'
      + '</div></div>';

    overlay.addEventListener('click', function(e) {
      if (e.target === overlay || e.target.classList.contains('tp-mailto-modal-close')) {
        overlay.remove();
      }
      if (e.target.dataset.action === 'copy') {
        var ta = overlay.querySelector('textarea');
        var fullText = 'Către: ' + emailTo + '\nSubiect: ' + subjectDecoded + '\n\n' + ta.value;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(fullText).then(function() { showToast('Text copiat!'); });
        } else {
          ta.select();
          document.execCommand('copy');
          showToast('Text copiat!');
        }
      }
    });

    document.body.appendChild(overlay);
  }

  function showToast(msg) {
    var t = document.createElement('div');
    t.className = 'tp-mailto-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function() { t.remove(); }, 2500);
  }

  function handleMailtoClick(e, emailTo, subject, bodyText, webUrl) {
    if (isWebView()) {
      e.preventDefault();
      showMailtoModal(emailTo, subject, bodyText, webUrl);
    }
  }

  // ──────────────────────────────────────────────────────────────
  // EMAIL SESIZARE ANAP (§5.2)
  // ──────────────────────────────────────────────────────────────
  function generateAnapEmailParts(card) {
    var subject = encodeURIComponent(
      'Sesizare achiziții publice — Primăria Pantelimon' + (card.contract ? ' — ' + card.contract : '')
    );
    var cardUrl = location.origin + location.pathname + '#nereguli-' + (card.idx + 1);
    var body = encodeURIComponent([
      'Subsemnatul/a [NUMELE TĂU], domiciliat în [ADRESA], CNP [CNP],',
      'în calitate de cetățean, solicit verificarea următorului semnal automat:',
      '',
      'OBIECT: ' + card.title,
      '',
      'DETALII:',
      '- Autoritate contractantă: Primăria Pantelimon (CIF 4420759)',
      card.contract   ? '- Cod contract: ' + card.contract : '',
      card.sum        ? '- Valoare: ' + fmtRON(card.sum)   : '',
      card.supplier   ? '- Furnizor: ' + card.supplier     : '',
      card.date       ? '- Data: ' + card.date              : '',
      '- Severitate detectată: ' + card.severity,
      '',
      'SURSĂ DATE:',
      '- Analiză automată: ' + cardUrl,
      '- Date publice SEAP (e-licitatie.ro) și ANAF',
      '',
      'Solicit verificarea acestei achiziții și comunicarea rezultatelor.',
      '',
      'Data: ' + new Date().toLocaleDateString('ro-RO'),
      'Semnătura: [SEMNĂTURĂ OLOGRAFĂ]',
    ].filter(Boolean).join('\n'));

    return { email: 'contact@anap.gov.ro', subject: subject, body: body, webUrl: 'https://anap.gov.ro/ro/contact/' };
  }

  function generateAnapEmail(card) {
    var parts = generateAnapEmailParts(card);
    return 'mailto:' + parts.email + '?subject=' + parts.subject + '&body=' + parts.body;
  }

  // Raportul nou construiește detaliile cardului la prima deschidere (evenimentul
  // tp:detalii); atunci adăugăm și butonul ANAP — nu pentru toate cardurile la încărcare.
  function injectAnapButtons(items) {
    if (document.querySelector('.tp-flag[data-title]')) {
      const peEl = new Map(items.map(it => [it.el, it]));
      document.addEventListener('tp:detalii', (ev) => {
        const it = peEl.get(ev.target);
        if (it) adaugaAnap(it);
      });
      return;
    }
    items.forEach(adaugaAnap);
  }

  function adaugaAnap(card) {
    [card].forEach(function(card) {
      if (card.el.querySelector('.tp-anap-btn')) return;
      var btn = document.createElement('a');
      btn.className = 'tp-anap-btn';
      btn.href = generateAnapEmail(card);
      btn.textContent = 'Sesizare către ANAP';
      btn.title = 'Deschide client email cu sesizare pre-completată pentru ANAP';
      btn.addEventListener('click', function(e) {
        var parts = generateAnapEmailParts(card);
        handleMailtoClick(e, parts.email, parts.subject, parts.body, parts.webUrl);
      });
      // în rândul de acțiuni din detaliile cardului (nu pe fața lui, lângă 4 alte butoane)
      var actiuni = card.el.querySelector('.flag-actions');
      (actiuni || card.el).appendChild(btn);
    });
  }

  // ──────────────────────────────────────────────────────────────
  // BANDĂ „Date SEAP până la …" — limita datelor, pe toate paginile
  // ──────────────────────────────────────────────────────────────
  function fmtDataRO(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '.' + m[2] + '.' + m[1] : '';
  }

  async function injectDataBand() {
    if ($('.tp-data-band')) return;
    const base = siteBase();
    let iso = '';
    try {
      const r = await fetch(base + 'delta.json', { cache: 'no-store' });
      if (r.ok) iso = ((await r.json()).date_seap_pana_la) || '';
    } catch (e) {}
    if (!iso) {
      // Rezervă: calculăm din contracte.json (mai mare, doar dacă delta.json nu are câmpul)
      try {
        const r = await fetch(base + 'contracte.json');
        if (r.ok) {
          const c = await r.json();
          (Array.isArray(c) ? c : []).forEach(x => {
            const d = String(x.data || '').slice(0, 10);
            if (/^\d{4}-\d{2}-\d{2}$/.test(d) && d > iso) iso = d;
          });
        }
      } catch (e) {}
    }
    const txt = fmtDataRO(iso);
    if (!txt || $('.tp-data-band')) return;
    const band = document.createElement('div');
    band.className = 'tp-data-band';
    band.setAttribute('role', 'note');
    band.innerHTML = '<strong>Date SEAP până la ' + txt + '.</strong> ' +
      'Din 7 octombrie 2026, contractele vin direct din SEAP (e-licitatie.ro), nu din exportul ' +
      'trimestrial de pe data.gov.ro. Totalul numără o singură dată contractele câștigate de asocieri ' +
      'și nu include acordurile-cadru (plafoane). ' +
      '<a href="' + base + 'despre.html#schimbare-surse">Ce s-a schimbat →</a>';
    const nav = $('.tp-nav');
    if (nav && nav.parentNode) nav.parentNode.insertBefore(band, nav.nextSibling);
    else document.body.insertBefore(band, document.body.firstChild);
  }

  // ──────────────────────────────────────────────────────────────
  // PARTAJARE — WhatsApp / Facebook / copiere link
  // ──────────────────────────────────────────────────────────────
  const SITE_URL = 'https://transparenta-pantelimon.eu';

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', '');
        ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        ok ? resolve() : reject(new Error('copy'));
      } catch (e) { reject(e); }
    });
  }

  function buildShareRow(url, text, extraClass) {
    const row = document.createElement('div');
    row.className = 'tp-share no-print' + (extraClass ? ' ' + extraClass : '');
    row.setAttribute('data-tp-share', '1');
    const wa = 'https://wa.me/?text=' + encodeURIComponent(text + ' ' + url);
    const fb = 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(url);
    row.innerHTML =
      '<span class="tp-share-lbl">Distribuie:</span>' +
      '<a class="tp-sh-wa" href="' + wa + '" target="_blank" rel="noopener noreferrer" aria-label="Distribuie pe WhatsApp">WhatsApp</a>' +
      '<a class="tp-sh-fb" href="' + fb + '" target="_blank" rel="noopener noreferrer" aria-label="Distribuie pe Facebook">Facebook</a>' +
      '<button type="button" class="tp-sh-copy">Copiază link</button>';
    // Clicurile nu trebuie să deschidă/închidă cardul din raport
    row.addEventListener('click', e => e.stopPropagation());
    row.querySelector('.tp-sh-copy').addEventListener('click', () => {
      copyText(url).then(() => showToast('Link copiat')).catch(() => {
        window.prompt('Copiază linkul:', url);
      });
    });
    return row;
  }

  function sumaScurta(n) {
    n = Number(n) || 0;
    if (!n) return '';
    return Math.round(n).toLocaleString('ro-RO') + ' RON';
  }

  // Raport: câte un rând de partajare pe fiecare card; linkul duce la pagina
  // semnalului (semnale/<slug>.html), care are propria imagine de previzualizare.
  async function injectShareReport() {
    const cards = $$('.tp-flag[id]');
    if (!cards.length) return;
    // Raportul nou: rândul de distribuire apare când cardul e deschis
    if (cards.every(c => c.dataset.slug)) {
      document.addEventListener('tp:detalii', (ev) => {
        if (ev.target.matches && ev.target.matches('.tp-flag[id]')) adaugaShare(ev.target, {});
      });
      return;
    }
    let harta = {};
    if (cards.some(c => !c.dataset.slug)) {
      try {
        const r = await fetch(siteBase() + 'semnale/harta.json');
        if (r.ok) harta = await r.json();
      } catch (e) {}
    }
    cards.forEach(card => adaugaShare(card, harta));
  }

  function adaugaShare(card, harta) {
    const pagina = SITE_URL + '/raport_transparenta.html';
    [card].forEach(card => {
      if (card.querySelector('[data-tp-share]')) return;
      const slug = card.dataset.slug || harta[card.id];
      const url = slug ? SITE_URL + '/semnale/' + slug + '.html' : pagina + '#' + card.id;
      const titluEl = card.querySelector('.flag-title') ||
        Array.from(card.querySelectorAll('span')).find(sp => /^\s*—\s*\S/.test(sp.textContent));
      const titlu = card.dataset.title ||
        (titluEl ? titluEl.textContent.replace(/^\s*—\s*/, '').trim() : 'Semnal automat');
      const firma = (card.dataset.supplier || '').trim();
      const suma = sumaScurta(card.dataset.sumRon);
      const text = titlu + (firma ? ' — ' + firma : '') + (suma ? ', ' + suma : '') +
        '. Verifică singur pe transparenta-pantelimon.eu:';
      const row = buildShareRow(url, text);
      const actiuni = card.querySelector('.flag-share');
      const detail = card.querySelector('.flag-detail');
      if (actiuni) actiuni.appendChild(row);
      else if (detail) card.insertBefore(row, detail); else card.appendChild(row);
    });
  }

  // Pagini de furnizor și pagini de semnal: un rând sub titlu
  function injectSharePage() {
    const path = location.pathname;
    if ($('[data-tp-share]')) return;
    const h1 = $('h1');
    if (!h1) return;
    const canonical = $('link[rel="canonical"]');
    const url = canonical ? canonical.href : SITE_URL + path;
    let text;
    if (/\/furnizori\//.test(path)) {
      text = 'Contractele ' + h1.textContent.trim() + ' cu Primăria Pantelimon, într-un singur loc. Verifică singur pe transparenta-pantelimon.eu:';
      const anchor = $('.stats') || $('.meta') || h1;
      anchor.parentNode.insertBefore(buildShareRow(url, text, 'tp-share-page'), anchor.nextSibling);
    } else if (/\/semnale\//.test(path)) {
      const art = $('[data-tp-share-title]');
      const firma = art ? art.getAttribute('data-tp-share-firma') : '';
      const suma = art ? art.getAttribute('data-tp-share-suma') : '';
      text = h1.textContent.trim() + (firma ? ' — ' + firma : '') + (suma ? ', ' + suma : '') +
        '. Verifică singur pe transparenta-pantelimon.eu:';
      const btns = $('.btns');
      (btns || h1).parentNode.insertBefore(buildShareRow(url, text, 'tp-share-page'), (btns || h1).nextSibling);
    }
  }


  // ──────────────────────────────────────────────────────────────
  // TEMĂ — retușuri de DOM pe paginile generate (fără emoji în titluri,
  // etichete de prioritate în loc de CRITIC/MAJOR/MEDIU, antet raport sobru)
  // ──────────────────────────────────────────────────────────────
  const EMOJI_LEAD = /^[\s←-⇿⌀-➿⬀-⯿️‍]*(?:[\u{1F000}-\u{1FAFF}☀-➿][️‍]?\s*)+/u;
  const EMOJI_ONLY = /^[\s\u{1F000}-\u{1FAFF}☀-➿️‍]+$/u;

  function stripLeadingEmoji(el) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      n.nodeValue = n.nodeValue.replace(EMOJI_LEAD, '');
      break;
    }
  }

  function sevPill(sev) {
    const sp = document.createElement('span');
    sp.className = 'tp-sevpill';
    sp.textContent = CFG.sevLabel[sev] || sev;
    return sp;
  }

  function themeDom() {
    $$('h1, h2, h3, h4').forEach(stripLeadingEmoji);
    const path = location.pathname.toLowerCase();

    if (/raport_transparenta/.test(path)) {
      const hero = $('body > div[style*="linear-gradient"]');
      if (hero) {
        hero.classList.add('tp-rhero');
        hero.removeAttribute('style');
        hero.querySelectorAll('[style]').forEach(e => e.removeAttribute('style'));
        const inner = hero.firstElementChild;
        if (inner && inner.lastElementChild) inner.lastElementChild.classList.add('tp-rhero-stats');
        const kicker = inner && inner.firstElementChild;
        if (kicker && !kicker.matches('h1')) kicker.remove();
        hero.querySelectorAll('button, a').forEach(stripLeadingEmoji);
        hero.querySelectorAll('span').forEach(sp => {
          if (/^\s*→/.test(sp.textContent)) sp.textContent = sp.textContent.replace(/^\s*→\s*/, '');
        });
      }
      $$('.tp-flag[data-severity]').forEach(card => {
        const head = card.firstElementChild;
        if (!head) return;
        // Rândul de fapte (sumă, firmă, dată…) și butoanele din detalii: fără emoji
        card.querySelectorAll(':scope > div:nth-child(3) > span, .flag-detail a, .flag-detail button').forEach(stripLeadingEmoji);
        Array.from(head.children).forEach(ch => {
          const t = ch.textContent.trim();
          if (ch.tagName === 'SPAN' && t && EMOJI_ONLY.test(t)) ch.remove();
          else if (ch.tagName === 'STRONG' && /^\[(CRITIC|MAJOR|MEDIU)\]$/.test(t)) ch.replaceWith(sevPill(card.dataset.severity));
          else if (ch.tagName === 'SPAN' && /RISC\s+\d+/.test(t)) {
            ch.classList.add('tp-riskpill');
            ch.textContent = 'Scor firmă ' + (t.match(/\d+/) || [''])[0];
          }
        });
      });
    }

    if (/\/furnizori\/[^/]+\.html$/.test(path) && !/\/furnizori\/index\.html$/.test(path)) {
      $$('.container div[style*="border-left:4px solid"] > div:first-child').forEach(div => {
        const m = /^\s*\S*\s*\[(CRITIC|MAJOR|MEDIU)\]\s*/u.exec(div.textContent);
        if (!m) return;
        const titlu = div.textContent.slice(m[0].length);
        div.textContent = '';
        const pill = sevPill(m[1]);
        const sevVar = { CRITIC: 'hi', MAJOR: 'mid', MEDIU: 'low' }[m[1]];
        pill.style.cssText = `--sev:var(--tp-${sevVar});--sev-t:var(--tp-${sevVar}-t);margin-right:8px`;
        div.append(pill, document.createTextNode(titlu));
        div.style.color = 'var(--tp-fg)';
      });
      $$('.container .ext-btn').forEach(stripLeadingEmoji);
    }
  }

  // ──────────────────────────────────────────────────────────────
  // BOOT
  // ──────────────────────────────────────────────────────────────
  async function injectLastUpdated() {
    // Injectează "Date actualizate: [lună] [an]" în nav brand (credibilitate)
    try {
      const r = await fetch(siteBase() + 'delta.json', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      const dateStr = d.data_curenta || d.data_anterioara || '';
      if (!dateStr) return;
      const dt = new Date(dateStr);
      if (isNaN(dt)) return;
      const luni = ['ian','feb','mar','apr','mai','iun','iul','aug','sep','oct','nov','dec'];
      const label = `${luni[dt.getMonth()]} ${dt.getFullYear()}`;
      const brand = document.querySelector('.tp-nav-brand');
      if (brand && !brand.querySelector('.tp-nav-date')) {
        const span = document.createElement('span');
        span.className = 'tp-nav-date';
        span.setAttribute('aria-label', `Date actualizate ${label}`);
        span.textContent = label;
        brand.appendChild(span);
      }
    } catch (e) {}
  }

  async function showWhatsNewBanner() {
    try {
      // siteBase(): pe furnizori/ și semnale/ calea relativă dădea 404
      const r = await fetch(siteBase() + 'delta.json', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      if (!d.nereguli_noi || d.nereguli_noi === 0) return;

      // Nu afișa bannerul dacă a fost deja respins pentru acest raport
      const dismissedFor = localStorage.getItem('tp-banner-dismissed');
      if (dismissedFor === d.data_curenta) return;

      const topNoi = (d.top_noi || []).slice(0, 2)
        .map(n => `<strong>${n.severitate}</strong>: ${escapeHTML(n.titlu)}`).join('; ');
      const link = siteBase() + 'raport_transparenta.html#noi';

      const banner = document.createElement('div');
      banner.className = 'tp-banner-whats-new';
      banner.setAttribute('role', 'status');
      banner.innerHTML =
      `<strong>${d.nereguli_noi} semnale noi</strong> față de raportul anterior` +
        (topNoi ? ` — ${topNoi}` : '') +
        ` <a href="${link}">vezi raportul →</a>` +
        `<button class="tp-banner-close" aria-label="Închide bannerul">×</button>`;

      banner.querySelector('.tp-banner-close').addEventListener('click', () => {
        try { localStorage.setItem('tp-banner-dismissed', d.data_curenta); } catch (e) {}
        banner.remove();
      });

      document.body.insertBefore(banner, document.body.firstChild);
    } catch (e) { /* fail silently — delta.json poate să nu existe */ }
  }

  function applyTheme() {
    try {
      const saved = localStorage.getItem('tp-theme');
      if (saved) {
        document.documentElement.dataset.tpTheme = saved;
      } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.dataset.tpTheme = 'dark';
      }
    } catch (e) {}
  }

  // ──────────────────────────────────────────────────────────────
  // §4.5 CORE WEB VITALS — lazy loading imagini sub fold
  // ──────────────────────────────────────────────────────────────
  function injectLazyImages() {
    // Adăugăm loading="lazy" pe orice <img> care nu are deja atributul
    // și nu se află în <nav> (adică nu e above-the-fold).
    $$('img:not([loading])').forEach(img => {
      if (!img.closest('.tp-nav')) {
        img.setAttribute('loading', 'lazy');
      }
    });
  }

  function interceptMailtoLinks() {
    if (!isWebView()) return;
    var WEB_URLS = {
      'contact@anap.gov.ro': 'https://anap.gov.ro/ro/contact/',
      'anticoruptie@dna.ro': 'https://www.dna.ro/sesizare.xhtml',
      'petitii@avp.ro': 'https://avp.ro/index.php/contact/sediul-central/',
      'relatiicupublicul@prefecturailfov.ro': 'https://if.prefectura.mai.gov.ro/petitii/',
      'secretariat@primariapantelimon.ro': 'https://www.primariapantelimon.ro/registratura-online/'
    };
    document.addEventListener('click', function(e) {
      var link = e.target.closest('a[href^="mailto:"]');
      if (!link) return;
      e.preventDefault();
      var href = link.href || link.getAttribute('href') || '';
      var match = href.match(/^mailto:([^?]+)/);
      if (!match) return;
      var emailTo = decodeURIComponent(match[1]);
      var params = new URLSearchParams(href.split('?')[1] || '');
      var subject = params.get('subject') || '';
      var body = params.get('body') || '';
      showMailtoModal(emailTo, encodeURIComponent(subject), encodeURIComponent(body), WEB_URLS[emailTo] || '');
    });
  }

  // ──────────────────────────────────────────────────────────────
  // BREADCRUMBS — navigare ierarhică pe paginile secundare
  // ──────────────────────────────────────────────────────────────
  var BREADCRUMB_MAP = {
    'raport_transparenta.html': 'Raport semnale de risc',
    'transparenta_pantelimon.html': 'Buget & Grafice',
    'harta.html': 'Hartă Furnizori',
    'presa.html': 'Presă',
    'despre.html': 'Despre',
    'petitie.html': 'Petiție',
    'gdpr.html': 'GDPR',
    'retele.html': 'Rețele',
    'modele.html': 'Modele de cereri'
  };

  function injectBreadcrumbs() {
    var path = location.pathname.split('/').pop() || 'index.html';
    if (path === 'index.html' || path === '' || path === '/') return;
    var pageName = BREADCRUMB_MAP[path];
    if (!pageName && /\/furnizori\//.test(location.pathname)) pageName = document.title.split('—')[0].trim() || 'Furnizor';
    if (!pageName && /\/semnale\//.test(location.pathname)) pageName = 'Semnal';
    if (!pageName) return;

    var nav = document.createElement('nav');
    nav.className = 'tp-breadcrumb';
    nav.setAttribute('aria-label', 'Breadcrumb');
    var ol = document.createElement('ol');
    ol.innerHTML = '<li><a href="' + siteBase() + 'index.html">Acasă</a></li><li aria-current="page">' + escapeHTML(pageName) + '</li>';
    nav.appendChild(ol);
    var main = document.querySelector('main, .page-wrap, header');
    if (main) main.parentNode.insertBefore(nav, main);
  }

  // ──────────────────────────────────────────────────────────────
  // STICKY CTA — bar fixat pe mobile cu acțiuni principale
  // ──────────────────────────────────────────────────────────────
  function injectStickyCTA() {
    var path = location.pathname.split('/').pop() || 'index.html';
    if (path !== 'index.html' && path !== '' && path !== '/') return;

    var bar = document.createElement('div');
    bar.className = 'tp-sticky-cta';
    bar.innerHTML = '<a href="raport_transparenta.html">Semnale</a>' +
      '<a href="furnizori/index.html">Firme</a>' +
      '<a href="modele.html">Modele de cereri</a>';
    document.body.appendChild(bar);
  }

  function boot() {
    document.documentElement.classList.add('tp-theme');
    // Cadrul static (site_shell.py): meniu, bandă de date, breadcrumb și tema sunt
    // deja în HTML. Fără el (pagină veche), le construim aici, ca înainte.
    const cadruStatic = !!$('.tp-nav');
    if (!cadruStatic) {
      applyTheme();
      injectHead();
      injectStyle();
    }
    injectNav();
    var fallbackNav = document.querySelector('.static-nav');
    if (fallbackNav) fallbackNav.style.display = 'none';
    var fallbackSkip = document.querySelector('.skip-link');
    if (fallbackSkip) fallbackSkip.style.display = 'none';
    injectMainId();
    if (!cadruStatic) {
      injectBreadcrumbs();
      injectLastUpdated();
      showWhatsNewBanner();
      injectDataBand();
    }
    injectLazyImages();
    injectBackToTop();
    interceptMailtoLinks();
    injectStickyCTA();

    themeDom();
    const path = location.pathname.toLowerCase();
    if (/raport_transparenta/.test(path)) {
      enhanceReport();
      injectShareReport();
    } else if (/\/(furnizori|semnale)\/[^/]+\.html$/.test(path) && !/\/furnizori\/index\.html$/.test(path)) {
      injectSharePage();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // ──────────────────────────────────────────────────────────────
  // PRINT / PDF — funcție apelată din raport_transparenta.html
  // ──────────────────────────────────────────────────────────────
  function printRaport() {
    // 0. Detaliile construite la cerere (raportul nou) — le construim pe toate
    if (window._construiesteDetalii) document.querySelectorAll('.tp-flag').forEach(window._construiesteDetalii);
    // 1. Colectăm elementele ascunse
    const hiddenCards   = Array.from(document.querySelectorAll('.tp-card-hidden'));
    const hiddenDetails = Array.from(document.querySelectorAll('.flag-detail'));

    // 2. Afișăm tot
    hiddenCards.forEach(el => el.classList.remove('tp-card-hidden'));
    hiddenDetails.forEach(el => { el._origDisplay = el.style.display; el.style.display = 'block'; });

    // 3. Printăm
    window.print();

    // 4. Restaurăm după închiderea dialogului de print
    function restore() {
      hiddenCards.forEach(el => el.classList.add('tp-card-hidden'));
      hiddenDetails.forEach(el => { el.style.display = el._origDisplay || 'none'; delete el._origDisplay; });
    }
    // afterprint se declanșează când utilizatorul închide dialogul
    window.addEventListener('afterprint', restore, { once: true });
    // Fallback pentru browsere care nu suportă afterprint
    setTimeout(() => {
      window.removeEventListener('afterprint', restore);
      restore();
    }, 30000);
  }
  // Expunem global — butonul din raport_transparenta.html apelează printRaport()
  window.printRaport = printRaport;

  // ── §4.3 Service Worker + PWA manifest ──────────────────────────────────────
  (function initPWA() {
    // Înregistrare Service Worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(reg => {
          // Verifică update-uri la navigare
          reg.addEventListener('updatefound', () => {
            const newSW = reg.installing;
            if (!newSW) return;
            newSW.addEventListener('statechange', () => {
              if (newSW.state === 'installed' && navigator.serviceWorker.controller) {
                // Există versiune nouă — notificăm discret
                console.info('[SW] Versiune nouă disponibilă — reîncarcă pagina pentru update.');
              }
            });
          });
        })
        .catch(() => {}); // Eșec silențios (ex: file://, localhost fără HTTPS)
    }

    // Injectează <link rel="manifest"> dacă lipsește
    if (!document.querySelector('link[rel="manifest"]')) {
      const link = document.createElement('link');
      link.rel = 'manifest';
      link.href = '/manifest.webmanifest';
      document.head.appendChild(link);
    }

    // Injectează <meta name="theme-color"> dacă lipsește
    if (!document.querySelector('meta[name="theme-color"]')) {
      const meta = document.createElement('meta');
      meta.name = 'theme-color';
      meta.content = '#14263D';
      document.head.appendChild(meta);
    }
  })();

})();
