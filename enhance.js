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
      CRITIC: '#dc2626',
      MAJOR:  '#f59e0b',
      MEDIU:  '#eab308',
    },
  };

  // ──────────────────────────────────────────────────────────────
  // CSS (injectat inline)
  // ──────────────────────────────────────────────────────────────
  const CSS = `
:root {
  --tp-bg:#ffffff; --tp-fg:#1a1a1a; --tp-muted:#4b5563;
  --tp-border:#e5e7eb; --tp-card-bg:#fafafa; --tp-link:#2563eb;
  --tp-accent:#dc2626; --tp-warn:#f59e0b; --tp-info:#eab308;
}
html[data-tp-theme="dark"] {
  --tp-bg:#0a0a0a; --tp-fg:#f3f4f6; --tp-muted:#9ca3af;
  --tp-border:#2a2a2a; --tp-card-bg:#141414; --tp-link:#60a5fa;
  color-scheme: dark;
}

/* Skip link (keyboard accessibility) */
.tp-skip-link {
  position: absolute; top: -100%; left: 1rem;
  background: var(--tp-accent); color: #fff;
  padding: .5rem 1.1rem; border-radius: 0 0 6px 6px;
  font-size: .9rem; font-weight: 600; z-index: 9999;
  text-decoration: none; transition: top .15s;
}
.tp-skip-link:focus { top: 0; outline: 2px solid #fff; outline-offset: 2px; }

/* Sticky nav */
.tp-nav {
  position: sticky; top: 0; z-index: 100;
  background: var(--tp-bg);
  border-bottom: 1px solid var(--tp-border);
}
.tp-nav-inner {
  max-width: 1200px; margin: 0 auto;
  padding: .55rem 1rem;
  display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
}
.tp-nav-brand {
  font-weight: 700; text-decoration: none; color: var(--tp-fg);
  white-space: nowrap; font-size: .95rem; display: flex; align-items: center; gap: .4rem;
}
.tp-nav-date {
  font-size: .68rem; font-weight: 400; opacity: .65;
  background: rgba(0,0,0,.06); border-radius: 3px; padding: 1px 5px;
  white-space: nowrap;
}
.tp-nav-links {
  display: flex; gap: .15rem; flex: 1; flex-wrap: wrap;
}
.tp-nav-links a {
  padding: .4rem .75rem; border-radius: 6px;
  text-decoration: none; color: var(--tp-fg); font-size: .88rem;
}
.tp-nav-links a:hover { background: var(--tp-card-bg); }
.tp-nav-links a.active { background: var(--tp-accent); color: #fff; }

/* Toolbar */
.tp-toolbar {
  position: sticky; top: 49px; z-index: 90;
  background: var(--tp-bg);
  border-bottom: 1px solid var(--tp-border);
  padding: .65rem 1rem;
}
.tp-toolbar-inner {
  max-width: 1200px; margin: 0 auto;
  display: grid; gap: .55rem;
}
.tp-toolbar-row {
  display: flex; gap: .45rem; flex-wrap: wrap; align-items: center;
}
.tp-search {
  flex: 1; min-width: 200px;
  padding: .5rem .75rem;
  border: 1px solid var(--tp-border); border-radius: 8px;
  background: var(--tp-bg); color: var(--tp-fg); font-size: .95rem;
}
.tp-search:focus { outline: 2px solid var(--tp-link); outline-offset: -1px; }
.tp-select {
  padding: .5rem .65rem;
  border: 1px solid var(--tp-border); border-radius: 8px;
  background: var(--tp-bg); color: var(--tp-fg);
  font-size: .88rem; cursor: pointer; max-width: 280px;
}
.tp-chip {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .35rem .75rem;
  border: 1px solid var(--tp-border); border-radius: 999px;
  background: var(--tp-bg); color: var(--tp-fg);
  cursor: pointer; font-size: .82rem; user-select: none;
}
.tp-chip:hover { background: var(--tp-card-bg); }
.tp-chip[data-sev="CRITIC"].active { background: #dc2626; border-color: #dc2626; color: #fff; }
.tp-chip[data-sev="MAJOR"].active  { background: #f59e0b; border-color: #f59e0b; color: #1a1a1a; }
.tp-chip[data-sev="MEDIU"].active  { background: #eab308; border-color: #eab308; color: #1a1a1a; }
.tp-chip[data-shell].active        { background: #7c3aed; border-color: #7c3aed; color: #fff; }
.tp-chip-cnt { font-size:.75em; font-weight:700; opacity:.85; margin-left:.18em; }
/* Mini-badge financiar pe card (angajați + CA) ─ injectat de enhance.js */
.tp-fin-badge { display:flex; flex-wrap:wrap; gap:.3em; margin:.35em 0 .2em .5em; }
.tp-fin-badge .tp-fb-item {
  font-size:.72rem; color:var(--tp-muted);
  background:rgba(107,114,128,.07); border:1px solid rgba(107,114,128,.16);
  border-radius:4px; padding:.1em .45em; white-space:nowrap;
}
.tp-dark .tp-fin-badge .tp-fb-item { background:rgba(156,163,175,.1); border-color:rgba(156,163,175,.2); }
#tp-shell-row { display: none; }  /* ascuns până confirmăm că există panele */
/* Chips severitate — grupate, nu se separă pe linii diferite */
.tp-chips-sev {
  display: flex; gap: .3rem; flex-shrink: 0; flex-wrap: nowrap;
}

.tp-btn {
  padding: .45rem .85rem;
  border: 1px solid var(--tp-border); border-radius: 6px;
  background: var(--tp-bg); color: var(--tp-fg);
  cursor: pointer; font-size: .85rem; text-decoration: none;
  display: inline-flex; align-items: center; gap: .3rem;
}
.tp-btn:hover { background: var(--tp-card-bg); }
.tp-btn-primary { background: var(--tp-accent); color: #fff; border-color: var(--tp-accent); }
.tp-btn-primary:hover { background: #b91c1c; }

.tp-stats {
  font-size: .82rem; color: var(--tp-muted);
  display: flex; gap: 1rem; flex-wrap: wrap;
}
.tp-stats strong { color: var(--tp-fg); }

/* Summary widget */
.tp-summary {
  max-width: 1200px; margin: 1rem auto; padding: 1rem;
  background: var(--tp-card-bg);
  border: 1px solid var(--tp-border); border-radius: 12px;
}
.tp-summary h3 { margin: 0 0 .75rem 0; font-size: 1rem; }
.tp-summary-grid {
  display: grid; gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}
.tp-summary-list { font-size: .85rem; }
.tp-summary-li {
  display: flex; justify-content: space-between;
  padding: .35rem 0;
  border-bottom: 1px solid var(--tp-border); gap: .5rem;
}
.tp-summary-li:last-child { border: 0; }
.tp-summary-li strong { color: var(--tp-fg); font-weight: 600; }
.tp-summary-li span.tp-muted { color: var(--tp-muted); font-size: .8rem; }
.tp-summary-bar {
  height: 22px; border-radius: 6px; overflow: hidden;
  display: flex; margin-top: .35rem;
  border: 1px solid var(--tp-border);
}
.tp-summary-bar > span {
  height: 100%;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: .75rem; font-weight: 600;
}

/* Carduri */
.tp-card-hidden { display: none !important; }
.tp-card-anchor {
  margin-left: .5rem; color: var(--tp-muted);
  text-decoration: none; font-size: .8rem;
  opacity: 0; transition: opacity .15s;
}
*:hover > .tp-card-anchor { opacity: 1; }
.tp-card-anchor:hover { color: var(--tp-link); }
.tp-card-flash {
  animation: tpFlash 1.5s ease-out;
}
@keyframes tpFlash {
  0%   { background: rgba(220,38,38,.18); }
  100% { background: transparent; }
}

/* Load more / empty */
.tp-loadmore {
  max-width: 1200px; margin: 1.5rem auto;
  display: flex; justify-content: center;
}
.tp-empty {
  text-align: center; padding: 3rem 1rem;
  color: var(--tp-muted);
}
.tp-empty p { margin: .4rem 0; }
.tp-empty code {
  background: var(--tp-card-bg, #f1f5f9); padding: 1px 5px;
  border-radius: 4px; font-size: .85em;
}
.tp-suggest {
  display: flex; flex-wrap: wrap; gap: .4rem;
  justify-content: center; margin: .5rem 0 1rem;
}
.tp-suggest-btn { font-weight: 600; }

/* Back-to-top */
.tp-back-top {
  position: fixed; bottom: 1.25rem; right: 1.25rem;
  width: 44px; height: 44px; border-radius: 50%;
  border: 1px solid var(--tp-border);
  background: var(--tp-bg); color: var(--tp-fg);
  cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,.12);
  opacity: 0; pointer-events: none;
  transition: opacity .2s;
  z-index: 50; font-size: 1.1rem;
}
.tp-back-top.visible { opacity: 1; pointer-events: auto; }

/* ── Breadcrumbs ── */
.tp-breadcrumb { padding: 8px 16px; font-size: 13px; color: var(--tp-muted, #4b5563); }
.tp-breadcrumb ol { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px; max-width: 1200px; margin: 0 auto; }
.tp-breadcrumb li::after { content: '›'; margin-left: 6px; opacity: .5; }
.tp-breadcrumb li:last-child::after { content: ''; margin: 0; }
.tp-breadcrumb li:last-child { font-weight: 600; color: var(--tp-fg, #1a202c); }
.tp-breadcrumb a { color: var(--tp-accent, #00427A); text-decoration: none; }
.tp-breadcrumb a:hover { text-decoration: underline; }

/* ── Sticky CTA mobile ── */
.tp-sticky-cta { display: none; }
@media (max-width: 640px) {
  .tp-sticky-cta {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 90;
    background: var(--tp-bg, #fff); border-top: 1px solid var(--tp-border, #e2e8f0);
    display: flex; justify-content: space-around; padding: 6px 8px;
    box-shadow: 0 -2px 8px rgba(0,0,0,.1);
  }
  .tp-sticky-cta a {
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    font-size: 11px; font-weight: 600; color: var(--tp-fg, #1a202c);
    text-decoration: none; padding: 6px 12px; border-radius: 8px;
    min-height: 44px; justify-content: center;
  }
  .tp-sticky-cta a:hover, .tp-sticky-cta a:active { background: var(--tp-card-bg, #f7fafc); }
  body { padding-bottom: 64px; }
}
@media print { .tp-sticky-cta { display: none !important; } }

/* ── Focus-visible pe elemente interactive ── */
.tp-chip:focus-visible, .tp-btn:focus-visible, .tp-nav-links a:focus-visible,
.tp-theme-toggle:focus-visible, .tp-back-top:focus-visible, .tp-search:focus-visible,
#tp-load-more:focus-visible, .tp-hamburger:focus-visible {
  outline: 2px solid var(--tp-accent, #00427A); outline-offset: 2px; border-radius: 6px;
}

/* ── Print ── */
@media print {
  .tp-nav, .tp-toolbar, .tp-back-top, .tp-breadcrumb, .alert-banner { display: none !important; }
  body { padding-bottom: 0 !important; }
}

/* ── touch-action pe toate elementele interactive ── */
.tp-chip, .tp-btn, .tp-nav-links a, #tp-load-more, .tp-theme-toggle, .tp-back-top {
  touch-action: manipulation;
}
/* ── Touch targets min 44px ── */
.tp-chip { min-height: 44px; display: inline-flex; align-items: center; }
.tp-btn { min-height: 44px; display: inline-flex; align-items: center; }
.tp-search { min-height: 44px; }
.tp-select { min-height: 44px; }
.tp-nav-links a { min-height: 44px; display: inline-flex; align-items: center; }
#tp-load-more { min-height: 44px; min-width: 200px; }
/* ── Hamburger ── */
.tp-hamburger {
  display: none; flex-direction: column; justify-content: center; align-items: center;
  gap: 5px; padding: 10px; border: none; background: transparent;
  cursor: pointer; min-width: 44px; min-height: 44px;
  color: var(--tp-fg); border-radius: 6px; touch-action: manipulation; flex-shrink: 0;
}
.tp-hamburger span { display: block; width: 22px; height: 2px; background: currentColor; border-radius: 2px; transition: transform .2s, opacity .2s; }
.tp-nav.open .tp-hamburger span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
.tp-nav.open .tp-hamburger span:nth-child(2) { opacity: 0; }
.tp-nav.open .tp-hamburger span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
/* ── Mobile ── */
@media (max-width: 640px) {
  .tp-nav-inner { padding: .4rem .6rem; gap: .4rem; flex-wrap: nowrap; align-items: center; }
  .tp-hamburger { display: flex; }
  .tp-nav-links {
    display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 200;
    flex-direction: column; gap: 0; background: var(--tp-bg);
    border-bottom: 2px solid var(--tp-accent); box-shadow: 0 4px 16px rgba(0,0,0,.12); padding: .5rem .6rem;
  }
  .tp-nav.open .tp-nav-links { display: flex; }
  .tp-nav-links a { padding: .6rem .8rem; font-size: .95rem; border-radius: 6px; border-bottom: 1px solid var(--tp-border); min-height: 48px; }
  .tp-nav-links a:last-child { border-bottom: none; }
  .tp-nav-brand { font-size: .82rem; flex: 1; }
  .tp-toolbar { padding: .5rem .6rem; }
  .tp-toolbar-row { flex-wrap: wrap; max-width: 100%; }
  .tp-chips-sev { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .tp-chips-sev::-webkit-scrollbar { display: none; }
  .tp-toolbar-row:nth-child(2) { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .tp-toolbar-row:nth-child(2)::-webkit-scrollbar { display: none; }
  .tp-select { min-width: 140px; flex: 0 0 auto; }
  .tp-search { font-size: 16px; flex: 1 1 100%; min-width: 0; }
}
@media (max-width: 480px) {
  .tp-nav-brand { font-size: .78rem; }
  .tp-chip { font-size: .8rem; padding: .3rem .6rem; }
}
@media (min-width: 641px) { .tp-hamburger { display: none !important; } }

/* Print */
@media print {
  .tp-nav, .tp-toolbar, .tp-back-top,
  .tp-loadmore, .tp-summary, .tp-banner-whats-new { display: none !important; }
  .tp-card-hidden { display: block !important; }
  .flag-detail { display: block !important; }
  .no-print { display: none !important; }
  details { page-break-inside: avoid; }
  details summary { font-weight: 700; }
  details:not([open]) > *:not(summary) { display: block !important; }
  body { font-size: 11pt; }
  a { color: inherit; text-decoration: none; }
  a[href]::after { content: " (" attr(href) ")"; font-size: 9pt; color: #555; }
  a[href^="#"]::after,
  a[href^="javascript"]::after { content: ""; }
  .tp-flag { page-break-inside: avoid; border: 1px solid #ddd !important; margin-bottom: 8pt !important; }
}

/* Dark mode toggle */
.tp-theme-toggle {
  padding: .35rem .6rem; border-radius: 6px;
  background: transparent; border: 1px solid var(--tp-border);
  color: var(--tp-fg); cursor: pointer; font-size: 1rem; line-height: 1;
  flex-shrink: 0;
}
.tp-theme-toggle:hover { background: var(--tp-card-bg); }

/* Buton sesizare ANAP pe carduri */
.tp-anap-btn {
  display: inline-flex; align-items: center; gap: .3rem;
  margin-top: .5rem;
  padding: .35rem .75rem;
  background: #fef2f2; border: 1px solid #fca5a5; border-radius: 6px;
  color: #b91c1c; text-decoration: none; font-size: .82rem;
  cursor: pointer; font-family: inherit;
}
.tp-anap-btn:hover { background: #fee2e2; }
html[data-tp-theme="dark"] .tp-anap-btn {
  background: #3f1515; border-color: #7f1d1d; color: #fca5a5;
}

/* Modal mailto fallback (WebView) */
.tp-mailto-modal-overlay {
  position: fixed; inset: 0; z-index: 10000;
  background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
}
.tp-mailto-modal {
  background: var(--tp-bg, #fff); border-radius: 14px;
  max-width: 480px; width: 100%; max-height: 85vh; overflow-y: auto;
  padding: 1.5rem; box-shadow: 0 12px 40px rgba(0,0,0,.25);
  position: relative;
}
.tp-mailto-modal h3 { font-size: 1rem; font-weight: 600; margin-bottom: .75rem; }
.tp-mailto-modal-close {
  position: absolute; top: .75rem; right: .75rem;
  background: none; border: none; font-size: 1.3rem; cursor: pointer;
  color: var(--tp-muted, #888); padding: .25rem;
}
.tp-mailto-field { margin-bottom: .75rem; }
.tp-mailto-field label { display: block; font-size: .75rem; font-weight: 600; color: var(--tp-muted, #888); margin-bottom: .25rem; text-transform: uppercase; letter-spacing: .5px; }
.tp-mailto-field textarea, .tp-mailto-field input {
  width: 100%; border: 1px solid var(--tp-border, #e5e7eb); border-radius: 6px;
  padding: .5rem; font-size: .85rem; font-family: inherit;
  background: var(--tp-card-bg, #fafafa); color: var(--tp-fg, #1a1a1a);
  resize: vertical;
}
.tp-mailto-actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: 1rem; }
.tp-mailto-actions a, .tp-mailto-actions button {
  padding: .55rem 1rem; border-radius: 8px; font-size: .85rem; font-weight: 600;
  text-decoration: none; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: .35rem;
  min-height: 44px;
}
.tp-mailto-copy { background: #fef2f2; color: #b91c1c; border: 1px solid #fca5a5 !important; }
.tp-mailto-copy:hover { background: #fee2e2; }
.tp-mailto-web { background: #e67e22; color: #fff; }
.tp-mailto-web:hover { background: #d35400; }
.tp-mailto-email { background: #0070C0; color: #fff; }
.tp-mailto-email:hover { background: #005a9e; }
.tp-mailto-toast {
  position: fixed; bottom: 2rem; left: 50%; transform: translateX(-50%);
  background: #27ae60; color: #fff; padding: .6rem 1.2rem; border-radius: 8px;
  font-size: .85rem; font-weight: 600; z-index: 10001;
  animation: tpToastIn .3s ease;
}
@keyframes tpToastIn { from { opacity: 0; transform: translateX(-50%) translateY(10px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
html[data-tp-theme="dark"] .tp-mailto-modal { background: #1a1a1a; }
html[data-tp-theme="dark"] .tp-mailto-copy { background: #3f1515; border-color: #7f1d1d !important; color: #fca5a5; }
html[data-tp-theme="dark"] .tp-mailto-field textarea,
html[data-tp-theme="dark"] .tp-mailto-field input { background: #141414; border-color: #2a2a2a; color: #f3f4f6; }

/* Banner "ce e nou" */
.tp-banner-whats-new {
  background: var(--tp-accent, #dc2626); color: #fff;
  padding: .6rem 1rem; text-align: center;
  position: relative; font-size: .9rem;
}
.tp-banner-whats-new a { color: #fff; text-decoration: underline; margin: 0 .4rem; }
.tp-banner-close {
  position: absolute; right: 1rem; top: 50%;
  transform: translateY(-50%);
  background: transparent; border: 0; color: #fff;
  font-size: 1.4rem; line-height: 1; cursor: pointer;
  padding: 0 .2rem;
}
.tp-banner-close:hover { opacity: .8; }
`;

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

  // ──────────────────────────────────────────────────────────────
  // NAV (toate paginile)
  // ──────────────────────────────────────────────────────────────
  function injectStyle() {
    if ($('#tp-enhance-styles')) return;
    const s = document.createElement('style');
    s.id = 'tp-enhance-styles';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function injectManifest() {
    if (document.querySelector('link[rel="manifest"]')) return;
    const link = document.createElement('link');
    link.rel = 'manifest'; link.href = '/manifest.webmanifest';
    document.head.appendChild(link);
    if (!document.querySelector('meta[name="theme-color"]')) {
      const meta = document.createElement('meta');
      meta.name = 'theme-color'; meta.content = '#dc2626';
      document.head.appendChild(meta);
    }
  }

  function injectNav() {
    if ($('.tp-nav')) return;
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
    const base = location.pathname.replace(/\/[^/]*$/, '/');

    // §4.4 aria-hidden on decorative emojis — screen readers announce link text only
    const links = [
      { href: 'index.html',                   emoji: '🏠', text: 'Acasă' },
      { href: 'raport_transparenta.html',      emoji: '🚩', text: 'Semnale de risc' },
      { href: 'transparenta_pantelimon.html',  emoji: '📊', text: 'Buget' },
      { href: 'despre.html',                   emoji: 'ℹ️', text: 'Despre' },
      { href: 'presa.html',                    emoji: '🗞️', text: 'Presă' },
      { href: 'petitie.html',                  emoji: '✍️', text: 'Petiție' },
      { href: 'harta.html',                    emoji: '🗺️', text: 'Hartă' },
      { href: 'retele.html',                   emoji: '🔗', text: 'Rețele' },
    ];

    const linksHTML = links.map(l => {
      const active = l.href.toLowerCase() === here || (here === '' && l.href === 'index.html');
      return `<a href="${base}${l.href}"${active ? ' class="active" aria-current="page"' : ''}><span aria-hidden="true">${l.emoji}</span> ${l.text}</a>`;
    }).join('');

    nav.style.position = 'sticky';
    nav.innerHTML = `
      <div class="tp-nav-inner">
        <a href="${base}index.html" class="tp-nav-brand"><span aria-hidden="true">🏛️</span> Transparența Pantelimon</a>
        <button class="tp-hamburger" id="tp-hamburger" aria-label="Meniu" aria-expanded="false" aria-controls="tp-nav-links">
          <span></span><span></span><span></span>
        </button>
        <div class="tp-nav-links" id="tp-nav-links">
          ${linksHTML}
          <a href="https://transparenta.eu/entities/4420759" target="_blank" rel="noopener">ANAF ↗</a>
          <a href="https://github.com/transparenta-locala/transparenta-pantelimon" target="_blank" rel="noopener">GitHub ↗</a>
        </div>
        <button class="tp-theme-toggle" id="tp-theme-btn" aria-label="Comută temă luminoasă/întunecată" title="Comută temă"><span aria-hidden="true">🌓</span></button>
      </div>
    `;
    document.body.insertBefore(nav, skipLink.nextSibling);

    // Hamburger toggle
    const hamburgerBtn = document.getElementById('tp-hamburger');
    if (hamburgerBtn) {
      hamburgerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = nav.classList.toggle('open');
        hamburgerBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });
      document.addEventListener('click', (e) => {
        if (!nav.contains(e.target)) { nav.classList.remove('open'); hamburgerBtn.setAttribute('aria-expanded', 'false'); }
      });
      nav.querySelectorAll('.tp-nav-links a').forEach(a => {
        a.addEventListener('click', () => { nav.classList.remove('open'); hamburgerBtn.setAttribute('aria-expanded', 'false'); });
      });
    }

    // Toggle dark/light mode
    $('#tp-theme-btn').addEventListener('click', () => {
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
      })).filter(it => it.el);
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
      if (!it.supplier) return;
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
    };

    // ─── TOOLBAR ──────────────────────────────────────────────
    const toolbar = document.createElement('div');
    toolbar.className = 'tp-toolbar';
    toolbar.setAttribute('role', 'search');
    toolbar.innerHTML = `
      <div class="tp-toolbar-inner">
        <div class="tp-toolbar-row">
          <input type="search" class="tp-search" id="tp-q"
                 placeholder="🔍 Caută firmă, CUI, cod contract sau cuvânt-cheie…"
                 aria-label="Caută în semnalele automate">
          <div class="tp-chips-sev">
            <button class="tp-chip active" data-sev="CRITIC" aria-pressed="true">🔴 CRITIC</button>
            <button class="tp-chip active" data-sev="MAJOR"  aria-pressed="true">🟠 MAJOR</button>
            <button class="tp-chip active" data-sev="MEDIU"  aria-pressed="true">🟡 MEDIU</button>
          </div>
        </div>
        <div class="tp-toolbar-row">
          <select class="tp-select" id="tp-supplier" aria-label="Filtrează după furnizor">
            <option value="">Toți furnizorii (${suppliers.length})</option>
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
          <button class="tp-btn" id="tp-export-csv" title="Descarcă rezultatele filtrate ca CSV">⬇ CSV</button>
          <button class="tp-btn" id="tp-export-json" title="Descarcă rezultatele filtrate ca JSON">⬇ JSON</button>
          <button class="tp-btn" id="tp-reset" title="Curăță toate filtrele">✕ Reset</button>
        </div>
        <div class="tp-toolbar-row" id="tp-shell-row">
          <span style="font-size:.78rem;color:var(--tp-muted);margin-right:.25rem">🏢 Profil firmă:</span>
          <button class="tp-chip" data-shell="zero-sal" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are 0 angajați declarați la ANAF">👥 0 angajați</button>
          <button class="tp-chip" data-shell="zero-ca" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are cifra de afaceri 0 RON">📉 CA = 0 RON</button>
          <button class="tp-chip" data-shell="ca-sub" aria-pressed="false"
                  title="Arată semnale unde cifra de afaceri a furnizorului e sub 50% din valoarea contractului">📊 CA sub contract</button>
          <button class="tp-chip" data-shell="any-risk" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are cel puțin un indicator de risc financiar">⚠️ Orice risc</button>
          <button class="tp-chip" data-shell="presa-risc" aria-pressed="false"
                  title="Arată doar semnale unde furnizorul are mențiuni de risc detectate automat în presă" style="display:none">📰 În presă</button>
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
    const summary = buildSummaryWidget(items, suppliers);

    // Inserăm toolbar + summary înainte de primul card
    const firstCard = cardEls[0];
    const anchor = firstCard.parentElement;
    anchor.insertBefore(toolbar, firstCard);
    anchor.insertBefore(summary, firstCard);

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
      setQuery(state, ''); state.supplier = ''; state.shellFilter = '';
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
    apply();

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
    const h = location.hash.replace(/^#/, '');
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

    // 5. Stats
    const totalSum = visible.reduce((s, it) => s + it.sum, 0);
    const byS = visible.reduce((acc, it) => {
      acc[it.severity] = (acc[it.severity] || 0) + 1; return acc;
    }, {});
    const stats = $('#tp-stats');
    if (stats) {
      stats.innerHTML = `
      <span><strong>${visible.length}</strong> / ${items.length} semnale afișate</span>
        <span>🔴 <strong>${byS.CRITIC || 0}</strong> · 🟠 <strong>${byS.MAJOR || 0}</strong> · 🟡 <strong>${byS.MEDIU || 0}</strong></span>
        <span>Total: <strong>${fmtRON(totalSum)}</strong></span>
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
      <h3>📈 Rezumat — ${items.length} semnale automate</h3>
      <div class="tp-summary-bar" aria-label="Distribuție pe severități">
        <span style="background:${CFG.severityColor.CRITIC}; width:${(sevCount.CRITIC/total*100).toFixed(1)}%">
          ${sevCount.CRITIC > 5 ? sevCount.CRITIC + ' CRITIC' : ''}
        </span>
        <span style="background:${CFG.severityColor.MAJOR}; color:#1a1a1a; width:${(sevCount.MAJOR/total*100).toFixed(1)}%">
          ${sevCount.MAJOR > 5 ? sevCount.MAJOR + ' MAJOR' : ''}
        </span>
        <span style="background:${CFG.severityColor.MEDIU}; color:#1a1a1a; width:${(sevCount.MEDIU/total*100).toFixed(1)}%">
          ${sevCount.MEDIU > 5 ? sevCount.MEDIU + ' MEDIU' : ''}
        </span>
      </div>
      <div class="tp-summary-grid" style="margin-top:1rem">
        <div>
          <strong style="font-size:.85rem">🏢 Top furnizori după numărul de semnale</strong>
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
          <strong style="font-size:.85rem">💰 Top furnizori după valoare</strong>
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

    return { email: 'sesizari@anap.gov.ro', subject: subject, body: body, webUrl: 'https://www.anap.gov.ro/web/sesizari/' };
  }

  function generateAnapEmail(card) {
    var parts = generateAnapEmailParts(card);
    return 'mailto:' + parts.email + '?subject=' + parts.subject + '&body=' + parts.body;
  }

  function injectAnapButtons(items) {
    items.forEach(function(card) {
      if (card.el.querySelector('.tp-anap-btn')) return;
      var btn = document.createElement('a');
      btn.className = 'tp-anap-btn';
      btn.href = generateAnapEmail(card);
      btn.textContent = '📧 Sesizare ANAP';
      btn.title = 'Deschide client email cu sesizare pre-completată pentru ANAP';
      btn.addEventListener('click', function(e) {
        var parts = generateAnapEmailParts(card);
        handleMailtoClick(e, parts.email, parts.subject, parts.body, parts.webUrl);
      });
      card.el.appendChild(btn);
    });
  }

  // ──────────────────────────────────────────────────────────────
  // BOOT
  // ──────────────────────────────────────────────────────────────
  async function injectLastUpdated() {
    // Injectează "Date actualizate: [lună] [an]" în nav brand (credibilitate)
    try {
      const r = await fetch('delta.json', { cache: 'no-store' });
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
      // Calea relativă funcționează atât pe GitHub Pages cât și local
      const r = await fetch('delta.json', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      if (!d.nereguli_noi || d.nereguli_noi === 0) return;

      // Nu afișa bannerul dacă a fost deja respins pentru acest raport
      const dismissedFor = localStorage.getItem('tp-banner-dismissed');
      if (dismissedFor === d.data_curenta) return;

      const topNoi = (d.top_noi || []).slice(0, 2)
        .map(n => `<strong>${n.severitate}</strong>: ${escapeHTML(n.titlu)}`).join('; ');
      const link = 'raport_transparenta.html#nereguli-1';

      const banner = document.createElement('div');
      banner.className = 'tp-banner-whats-new';
      banner.setAttribute('role', 'status');
      banner.innerHTML =
      `🚩 <strong>${d.nereguli_noi} semnale noi</strong> față de raportul anterior` +
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
      'sesizari@anap.gov.ro': 'https://www.anap.gov.ro/web/sesizari/',
      'sesizari@pna.ro': 'https://www.pna.ro/sesizare.xhtml',
      'avp@avp.ro': 'https://www.avp.ro/index.php/petitii-si-sesizari',
      'prefectura@prefecturaif.ro': 'https://ilfov.prefecturas.ro/contact/',
      'secretariat@primariapantelimon.ro': 'https://www.primariapantelimon.ro/contact/'
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
    'retele.html': 'Rețele'
  };

  function injectBreadcrumbs() {
    var path = location.pathname.split('/').pop() || 'index.html';
    if (path === 'index.html' || path === '' || path === '/') return;
    var pageName = BREADCRUMB_MAP[path];
    if (!pageName && /^furnizori\//.test(location.pathname)) pageName = document.title.split('—')[0].trim() || 'Furnizor';
    if (!pageName) return;

    var nav = document.createElement('nav');
    nav.className = 'tp-breadcrumb';
    nav.setAttribute('aria-label', 'Breadcrumb');
    var ol = document.createElement('ol');
    ol.innerHTML = '<li><a href="index.html">Acasă</a></li><li aria-current="page">' + pageName + '</li>';
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
    bar.innerHTML = '<a href="raport_transparenta.html"><span aria-hidden="true">🚩</span> Raport</a>' +
      '<a href="transparenta_pantelimon.html"><span aria-hidden="true">📊</span> Buget</a>' +
      '<a href="petitie.html"><span aria-hidden="true">✍️</span> Petiție</a>';
    document.body.appendChild(bar);
  }

  function boot() {
    applyTheme();
    injectHead();
    injectStyle();
    injectNav();
    var fallbackNav = document.querySelector('.static-nav');
    if (fallbackNav) fallbackNav.style.display = 'none';
    var fallbackSkip = document.querySelector('.skip-link');
    if (fallbackSkip) fallbackSkip.style.display = 'none';
    injectMainId();
    injectBreadcrumbs();
    injectLazyImages();
    injectBackToTop();
    injectLastUpdated();
    showWhatsNewBanner();
    interceptMailtoLinks();
    injectStickyCTA();

    const path = location.pathname.toLowerCase();
    if (/raport_transparenta/.test(path)) {
      enhanceReport();
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
      meta.content = '#dc2626';
      document.head.appendChild(meta);
    }
  })();

})();
