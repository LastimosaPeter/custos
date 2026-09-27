'use strict';

const CACHE_NAME = 'custos-static-v098-next3';
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
  '/static/img/csdc101-logo.png'
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
    event.respondWith(
      caches.match(request).then(cached => {
        const network = fetch(request).then(response => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          }
          return response;
        }).catch(() => cached);
        return cached || network;
      })
    );
  }
});
