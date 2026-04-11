const CACHE_NAME = 'tabuada-turbo-v2';
const ASSETS = [
  '/',
  '/robots.txt',
  '/sitemap.xml',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  // Não cachear HTML - sempre buscar do servidor
  if (url.pathname.endsWith('.html') || url.pathname === '/') {
    event.respondWith(fetch(request).catch(() => caches.match('/')));
    return;
  }

  // API vai direto
  if (url.pathname.startsWith('/api')) {
    return;
  }

  event.respondWith(
    caches.match(request)
      .then((cached) => {
        const networked = fetch(request)
          .then((response) => {
            if (response.ok && response.status === 200) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return response;
          })
          .catch(() => cached);
        return cached || networked;
      })
  );
});

self.addEventListener('push', (event) => {
  const data = event.data?.json() || {};
  self.registration.showNotification('Tabuada Turbo ⚡', {
    body: data.body || 'Hora de praticar a tabuada!',
    icon: '/icon-192.png',
    badge: '/icon-96.png'
  });
});