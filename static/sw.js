'use strict';

const CACHE_NAME = 'custos-static-v101-goliathus-portable-r2-google';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/js/pwa.js',
  '/static/js/theme.js',
  '/static/js/code_highlight.js',
  '/static/js/student_form.js',
  '/static/js/exam.js',
  '/static/js/ide.js',
  '/static/img/favicon.png',
  '/static/img/apple-touch-icon.png',
  '/static/img/pwa-icon-192.png',
  '/static/img/pwa-icon-512.png',
  '/static/img/csdc101-logo.webp',
  '/static/img/caudex-logo.png',
  '/static/img/caudex-wordmark-light.png',
  '/static/img/caudex-wordmark-dark.png',
  '/static/img/csdc101-background.webp'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Exam pages, APIs, logins, and instructor data must always come from Custos.
  if (
    request.mode === 'navigate' ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/exam') ||
    url.pathname.startsWith('/instructions') ||
    url.pathname.startsWith('/admin') ||
    url.pathname.startsWith('/login') ||
    url.pathname.startsWith('/ide')
  ) {
    event.respondWith(fetch(request));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    // Cache-first for release-versioned static assets. ignoreSearch lets the
    // pre-cached /static/foo.css satisfy /static/foo.css?v=<release>. A cache
    // name bump on each release guarantees updates without background refetches.
    event.respondWith(
      caches.match(request, {ignoreSearch: true}).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          }
          return response;
        });
      })
    );
  }
});

// UI cache refresh: Caudex IDE reveal 2026-09-27

// UI cache refresh: Caudex compact lockup 2026-09-27

// UI cache refresh: theme-aware Caudex wordmark 2026-09-27

// UI + assessment engine refresh: free-form custom assessments 2026-09-27

// Custos 1.0 · Goliathus portable/performance cache refresh.
