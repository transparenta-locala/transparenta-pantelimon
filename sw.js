/**
 * sw.js — Service Worker §4.3
 * Transparența Pantelimon — https://transparenta-pantelimon.eu
 *
 * Strategie: Cache-First pentru resurse statice, Network-First pentru date JSON.
 * Permite consultare offline a raportului și paginii principale.
 */

const CACHE_VERSION = 'tp-v7';
const CACHE_STATIC = 'tp-static-v7';
const CACHE_DATA   = 'tp-data-v2';

// Resurse core — pre-cached la install (offline-first pentru navigare)
const CORE_URLS = [
  '/',
  '/index.html',
  '/transparenta_pantelimon.html',
  '/enhance.min.js',
  '/harta.html',
  '/retele.html',
  '/presa.html',
  '/despre.html',
  '/petitie.html',
  '/gdpr.html',
  '/offline.html',
];

// Date care se schimbă frecvent — Network-First cu fallback cache
// IMPORTANT: raport_transparenta.html e generat săptămânal → network-first
const DATA_URLS = [
  '/raport_transparenta.html',
  '/raport.json',
  '/delta.json',
  '/contracte.json',
  '/press_kit.json',
  '/firme_geocoded.json',
  '/retele_firme.json',
  '/mentiuni_presa_auto.json',
  '/contracte.csv',
];

// ── Install: pre-cache resurse core ───────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(CORE_URLS).catch(err => {
        // Dacă o resursă lipsește, ignorăm eroarea (graceful)
        console.warn('[SW] Pre-cache parțial:', err.message);
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: șterge cache-uri vechi ─────────────────────────────────────────
self.addEventListener('activate', event => {
  const KEEP = [CACHE_STATIC, CACHE_DATA];
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => !KEEP.includes(k)).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: strategii diferite per tip resursă ─────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignorăm request-uri non-GET și cross-origin
  if (request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  // Date/pagini care se schimbă frecvent — Network-First (vrem date proaspete)
  const isDataUrl = DATA_URLS.some(u => url.pathname === u)
                 || url.pathname.endsWith('.json')
                 || url.pathname.endsWith('.csv');
  if (isDataUrl) {
    event.respondWith(
      url.pathname.endsWith('.csv') ? networkFirstCsv(request) : networkFirstHtmlOrJson(request)
    );
    return;
  }

  // Pagini HTML și resurse statice — Cache-First
  event.respondWith(cacheFirstStatic(request));
});

// ── Cache-First pentru resurse statice ───────────────────────────────────────
async function cacheFirstStatic(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_STATIC);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Offline și nu în cache — returnăm pagina offline stilizată
    const fallback = await caches.match('/offline.html');
    return fallback || new Response('Offline — deschideți https://transparenta-pantelimon.eu pentru a accesa datele salvate.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
  }
}

// ── Network-First pentru HTML dinamic + JSON ──────────────────────────────────
// Folosit și pentru raport_transparenta.html (generat săptămânal — nu cacheable!)
async function networkFirstHtmlOrJson(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_DATA);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    const ct = request.url.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/json';
    return cached || new Response(request.url.endsWith('.html') ? '' : '{}', {
      headers: { 'Content-Type': ct }
    });
  }
}

// ── Network-First pentru date CSV ─────────────────────────────────────────────
async function networkFirstCsv(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_DATA);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response('id,titlu,valoare,data,tip,firma,cui,ofertanti\n', {
      headers: { 'Content-Type': 'text/csv; charset=utf-8' }
    });
  }
}
