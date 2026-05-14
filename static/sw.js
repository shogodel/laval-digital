/* ── Laval Digital Service Worker ─────────────────────────────────────
   Provides offline caching for the dashboard and push notification support.
   Installed when the user opens the dashboard and their browser supports it.
   ────────────────────────────────────────────────────────────────────── */

const CACHE_NAME = 'laval-digital-v1';

const PRECACHE_URLS = [
  '/admin/dashboard',
  '/admin',
  '/api/orchestrator/status',
  '/api/events/history',
  '/api/events/stats',
  '/api/orchestrator/activity',
  '/static/logo.svg',
];

/* ── Install: precache app shell ── */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  self.skipWaiting();
});

/* ── Activate: clean old caches ── */
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

/* ── Fetch: network-first with cache fallback ── */
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Only handle our own origin
  if (url.origin !== self.location.origin) return;

  // API /api/ calls: network only (no stale data)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request).catch(() => {
      return new Response(JSON.stringify({ error: 'offline' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
    return;
  }

  // Static files: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        return cached || fetch(event.request).then(response => {
          return caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, response.clone());
            return response;
          });
        });
      })
    );
    return;
  }

  // HTML pages: network-first, fallback to cache
  event.respondWith(
    fetch(event.request).then(response => {
      return caches.open(CACHE_NAME).then(cache => {
        cache.put(event.request, response.clone());
        return response;
      });
    }).catch(() => {
      return caches.match(event.request).then(cached => {
        if (cached) return cached;
        return caches.match('/admin/dashboard');
      });
    })
  );
});

/* ── Push notification received ── */
self.addEventListener('push', event => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch (e) {
    return;
  }

  const title = data.title || 'Laval Digital';
  const options = {
    body: data.body || '',
    icon: data.icon || '/static/logo.svg',
    badge: data.badge || '/static/logo.svg',
    vibrate: [200, 100, 200],
    data: {
      url: data.url || '/admin/dashboard',
    },
    tag: 'laval-digital',
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

/* ── Notification click ── */
self.addEventListener('notificationclick', event => {
  event.notification.close();

  const url = event.notification.data?.url || '/admin/dashboard';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if (client.url.includes(url) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
