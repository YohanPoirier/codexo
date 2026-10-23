// Bandeau « Installer l'appli » (Anki, ou Codexo avec data-appli="codexo" sur la balise
// <script>). Chargé SANS defer et tout en haut : l'événement
// beforeinstallprompt peut partir avant la fin du chargement de la page, il faut que
// l'écouteur existe déjà. Le bandeau lui-même est affiché une fois la page prête.
//
// Android / Chrome : le navigateur fournit un événement beforeinstallprompt, qui permet un
// vrai bouton « Installer ». iPhone / iPad : pas d'équivalent, on affiche le geste à faire.
// Jamais affiché si l'appli est déjà ouverte comme une appli, ni sur ordinateur.
// Le choix est mémorisé sur l'appareil (localStorage), pas sur le compte.
(function () {
  'use strict';

  var script = document.currentScript;
  var APPLI = (script && script.dataset.appli) || 'anki';
  var CLE_PLUS_TARD = APPLI + '-installation-plus-tard';
  var CLE_FAIT = APPLI + '-installation-faite';
  var CLASSE_VISIBLE = APPLI + '-install-visible';
  var DELAI_PLUS_TARD_MS = 7 * 24 * 3600 * 1000;

  function lire(cle) {
    try { return window.localStorage.getItem(cle); } catch (e) { return null; }
  }
  function ecrire(cle, valeur) {
    try { window.localStorage.setItem(cle, valeur); } catch (e) { /* navigation privée */ }
  }

  function dejaInstallee() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
      || window.navigator.standalone === true;
  }

  function estIos() {
    var ua = window.navigator.userAgent || '';
    // iPadOS se présente comme un Mac : on le reconnaît à son écran tactile.
    return /iPhone|iPad|iPod/.test(ua)
      || (/Macintosh/.test(ua) && window.navigator.maxTouchPoints > 1);
  }

  function masque() {
    if (lire(CLE_FAIT) === '1') return true;
    var plusTard = parseInt(lire(CLE_PLUS_TARD) || '0', 10);
    return !!plusTard && Date.now() - plusTard < DELAI_PLUS_TARD_MS;
  }

  if (dejaInstallee()) { ecrire(CLE_FAIT, '1'); return; }

  var evenementInstall = null;
  window.addEventListener('beforeinstallprompt', function (evt) {
    evt.preventDefault(); // on déclenche nous-mêmes l'invite, depuis le bouton
    evenementInstall = evt;
    quandPret(afficher);
  });
  window.addEventListener('appinstalled', function () {
    ecrire(CLE_FAIT, '1');
    evenementInstall = null;
    fermer();
  });

  function quandPret(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function bandeau() { return document.getElementById('install-invitation'); }

  function afficher() {
    var el = bandeau();
    if (!el || masque()) return;
    var ios = estIos() && !evenementInstall;
    if (!ios && !evenementInstall) return; // ni Android installable ni iPhone : rien à proposer
    el.querySelector('[data-install-ios]').hidden = !ios;
    el.querySelector('[data-install-android]').hidden = ios;
    el.querySelector('[data-install-action="installer"]').hidden = ios;
    el.querySelector('[data-install-action="plus-tard"]').textContent = ios ? 'Compris' : 'Plus tard';
    el.hidden = false;
    // Tant que ce bandeau est visible, celui des notifications reste caché (voir installation.css).
    document.body.classList.add(CLASSE_VISIBLE);
  }

  function fermer() {
    var el = bandeau();
    if (el) el.hidden = true;
    document.body.classList.remove(CLASSE_VISIBLE);
  }

  quandPret(function () {
    var el = bandeau();
    if (!el) return;
    el.querySelector('[data-install-action="plus-tard"]').addEventListener('click', function () {
      ecrire(CLE_PLUS_TARD, String(Date.now()));
      fermer();
    });
    el.querySelector('[data-install-action="installer"]').addEventListener('click', async function () {
      var evt = evenementInstall;
      if (!evt) { fermer(); return; }
      evenementInstall = null; // un événement ne sert qu'une fois
      try {
        evt.prompt();
        var choix = await evt.userChoice;
        if (choix && choix.outcome === 'accepted') ecrire(CLE_FAIT, '1');
        else ecrire(CLE_PLUS_TARD, String(Date.now()));
      } catch (e) {
        ecrire(CLE_PLUS_TARD, String(Date.now()));
      }
      fermer();
    });
    // iPhone : pas d'événement à attendre, on peut afficher tout de suite.
    if (estIos()) afficher();
  });
})();
