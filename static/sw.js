'use strict';

const CACHE_NAME = 'custos-static-v160h-hercules-watermark-fix-r26';
const STATIC_ASSETS = [
  '/static/css/style.css',
  '/static/js/pwa.js',
  '/static/js/theme.js',
  '/static/js/code_highlight.js',
  '/static/js/student_form.js',
  '/static/js/ui_controls.js',
  '/static/js/exam.js',
  '/static/js/exam_tools.js',
  '/static/js/notebook_workbench.js',
  '/static/js/ide.js',
  '/static/img/favicon.png',
  '/static/img/apple-touch-icon.png',
  '/static/img/pwa-icon-192.png',
  '/static/img/pwa-icon-512.png',
  '/static/img/csdc101-logo.webp',
  '/static/img/csec303-logo.webp',
  '/static/img/custos-background.webp',
  '/static/img/hercules-beetle.svg',
  '/static/img/caudex-logo.png',
  '/static/img/caudex-wordmark-light.png',
  '/static/img/caudex-wordmark-dark.png',
  '/static/img/csdc101-background.webp',
  '/static/img/csec303-background.webp',
  '/static/img/csec303-watermark.png',
  '/static/img/csec303-watermark-dark.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      // Fetch each asset with a release-specific query and bypass every cache
      // (browser HTTP cache and any CDN such as Cloudflare), then store it under
      // the plain path. A plain cache.addAll(STATIC_ASSETS) could pre-cache a
      // stale copy a CDN still held for the unversioned URL - and the fetch
      // handler below would then serve that stale file for every ?v= request.
      .then(cache => Promise.all(STATIC_ASSETS.map(path =>
        fetch(new Request(`${path}?release=${encodeURIComponent(CACHE_NAME)}`, {cache: 'reload'}))
          .then(response => {
            if (!response.ok) throw new Error(`Pre-cache failed for ${path}`);
            return cache.put(path, response);
          })
      )))
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

// Custos 1.6.0.h · Hercules watermark fix cache refresh.
