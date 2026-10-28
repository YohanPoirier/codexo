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

// Retour à l'accueil après une longue absence (appli installée uniquement).
//
// Quand on revient sur l'appli après un certain temps, on retrouvait la dernière page
// visitée. Si l'appli est restée en arrière-plan plus de DELAI_ACCUEIL_MS, on revient
// à l'accueil de l'appli (Codexo : /, Anki : /anki/). Dans un onglet de navigateur
// classique, rien ne change.
//
// Pas de précaution particulière pour un exercice en cours : exercise.js enregistre déjà
// le code sur le serveur dès que la page passe en arrière-plan, et le restaure à la
// réouverture de l'exercice.
(function () {
  var DELAI_ACCUEIL_MS = 30 * 60 * 1000; // 30 minutes

  var enAppli = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
    window.navigator.standalone === true; // iOS
  if (!enAppli) return;

  var anki = document.documentElement.hasAttribute('data-sw-anki');
  var accueil = anki ? '/anki/' : '/';
  // Une clé par appli : Codexo et Anki partagent le même localStorage.
  var cle = 'codexo-pwa-masquee-' + (anki ? 'anki' : 'codexo');

  function lire() {
    try { return parseInt(localStorage.getItem(cle), 10) || 0; } catch (e) { return 0; }
  }
  function ecrire(valeur) {
    try {
      if (valeur) localStorage.setItem(cle, String(valeur));
      else localStorage.removeItem(cle);
    } catch (e) {}
  }

  function verifier() {
    var depuis = lire();
    ecrire(0);
    if (!depuis || Date.now() - depuis < DELAI_ACCUEIL_MS) return;
    if (window.location.pathname === accueil) return;
    window.location.replace(accueil);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') ecrire(Date.now());
    else verifier();
  });
  // Page rechargée ou restaurée après que le système a fermé l'appli en arrière-plan.
  verifier();
})();
