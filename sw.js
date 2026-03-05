const CACHE_NAME = 'nba-pro-v1';
self.addEventListener('install', event => {
    self.skipWaiting();
});
self.addEventListener('fetch', event => {
    event.respondWith(fetch(event.request).catch(() => new Response('Offline')));
});
