// Enregistre le service worker (servi à la racine : voir codexo/pwa.py).
// Sans lui le site fonctionne exactement comme avant ; il apporte l'installation
// sur l'écran d'accueil et le cache des fichiers statiques / de Pyodide.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function () {});
  });
}
