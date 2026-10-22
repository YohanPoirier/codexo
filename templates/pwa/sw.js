/* Service worker de Codexo / Anki — servi à la racine par codexo/pwa.py.
 *
 * Ce qu'il met en cache :
 *  - les fichiers statiques du site (/static/...) : leurs noms contiennent un hash
 *    (WhiteNoise « Manifest »), donc un fichier modifié a une nouvelle adresse et
 *    l'ancienne version ne peut jamais être servie par erreur ;
 *  - les bibliothèques des CDN (Pyodide, CodeMirror, KaTeX) : adresses versionnées,
 *    ce qui évite de retélécharger Pyodide (plusieurs dizaines de Mo) à chaque visite.
 *
 * Ce qu'il ne met JAMAIS en cache : les pages HTML, /api/, /admin/, /media/ et tout
 * ce qui n'est pas un GET. Les pages dépendent du compte connecté ; les garder en
 * cache risquerait d'afficher les données d'un autre utilisateur.
 *
 * Il affiche aussi les notifications push d'Anki (voir anki_review/notifications.py).
 *
 * Pas de liste de fichiers à maintenir : tout est mis en cache à la première demande.
 * Pour forcer le renouvellement complet des caches, incrémenter VERSION.
 */
const VERSION = 'v1';
const CACHE_STATIC = 'codexo-static-' + VERSION;
const CACHE_CDN = 'codexo-cdn-' + VERSION;
const CACHES_ACTUELS = [CACHE_STATIC, CACHE_CDN];

const DEBUG = {{ debug|yesno:"true,false" }};
const PREFIXE_STATIC = '{{ static_prefix }}';
const HOTES_CDN = ['cdn.jsdelivr.net', 'cdnjs.cloudflare.com'];

const PAGE_HORS_LIGNE = `<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hors ligne</title>
<style>
  body { font-family: system-ui, sans-serif; background: #f6f2e9; color: #21262b;
         display: flex; min-height: 100vh; align-items: center; justify-content: center;
         margin: 0; padding: 1.5rem; text-align: center; }
  button { font: inherit; padding: .6rem 1.2rem; border: 0; border-radius: .4rem;
           background: #2b3a67; color: #fff; margin-top: 1rem; }
</style></head>
<body><div>
  <h1>Pas de connexion</h1>
  <p>Cette page nécessite une connexion à Internet.</p>
  <button onclick="location.reload()">Réessayer</button>
</div></body></html>`;

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const noms = await caches.keys();
    await Promise.all(
      noms.filter((nom) => !CACHES_ACTUELS.includes(nom)).map((nom) => caches.delete(nom))
    );
    await self.clients.claim();
  })());
});

// Réponse du cache si elle existe, sinon réseau puis mise en cache (réponses 200 seulement :
// Cache.put refuse les réponses partielles et on ne garde pas les erreurs).
async function cacheEnPremier(request, nomCache) {
  const cache = await caches.open(nomCache);
  const enCache = await cache.match(request);
  if (enCache) return enCache;
  const reponse = await fetch(request);
  if (reponse.status === 200) {
    cache.put(request, reponse.clone());
  }
  return reponse;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  // En développement les fichiers statiques n'ont pas de hash : pas de cache du tout.
  if (DEBUG) return;

  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith(PREFIXE_STATIC)) {
      event.respondWith(cacheEnPremier(request, CACHE_STATIC));
      return;
    }
    if (request.mode === 'navigate') {
      // Toujours le réseau ; seul le cas « pas de connexion » est géré.
      event.respondWith(
        fetch(request).catch(() => new Response(PAGE_HORS_LIGNE, {
          status: 503,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }))
      );
    }
    return;
  }

  if (HOTES_CDN.includes(url.hostname)) {
    event.respondWith(cacheEnPremier(request, CACHE_CDN));
  }
});

// ---------------------------------------------------------------- notifications push

self.addEventListener('push', (event) => {
  let donnees = {};
  try {
    donnees = event.data ? event.data.json() : {};
  } catch (e) {
    donnees = {};
  }
  const options = {
    body: donnees.corps || '',
    icon: donnees.icone || undefined,
    // Un nouveau message remplace l'ancien au lieu de s'empiler.
    tag: 'anki-rappel',
    data: { url: donnees.url || '/anki/' },
  };
  event.waitUntil(self.registration.showNotification(donnees.titre || 'Anki', options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/anki/';
  event.waitUntil((async () => {
    const fenetres = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const fenetre of fenetres) {
      if (new URL(fenetre.url).pathname.startsWith('/anki/') && 'focus' in fenetre) {
        if ('navigate' in fenetre) await fenetre.navigate(url);
        return fenetre.focus();
      }
    }
    return self.clients.openWindow(url);
  })());
});
