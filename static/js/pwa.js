// Enregistre le service worker (servi par codexo/pwa.py).
// Sans lui le site fonctionne exactement comme avant ; il apporte l'installation
// sur l'écran d'accueil et le cache des fichiers statiques / de Pyodide.
//
// Pages d'Anki (marquées data-sw-anki) : service worker propre à Anki (/anki/sw.js, périmètre /anki/), pour que ses notifications
// soient attribuées à l'appli Anki installée et non à Chrome.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    var anki = document.documentElement.hasAttribute('data-sw-anki');
    var promesse = anki
      ? navigator.serviceWorker.register('/anki/sw.js', { scope: '/anki/' })
      : navigator.serviceWorker.register('/sw.js');
    promesse.catch(function () {});
  });
}
