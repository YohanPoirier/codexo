// Notifications push d'Anki : abonnement de l'appareil (bandeau de l'accueil et page
// « Notifications »). Rien n'est demandé à l'élève sans qu'il appuie sur « Activer » :
// Android refuse d'ailleurs toute demande d'autorisation qui ne suit pas un geste.
(function () {
  'use strict';

  var racine = document.querySelector('[data-notifications]');
  if (!racine) return;

  var mode = racine.dataset.mode; // "invitation" (bandeau) ou "page"
  var cle = racine.dataset.cle;
  var urlAbonner = racine.dataset.urlAbonner;
  var urlDesabonner = racine.dataset.urlDesabonner;
  var csrf = racine.dataset.csrf;

  var CLE_PLUS_TARD = 'anki-notifications-plus-tard';
  var DELAI_PLUS_TARD_MS = 7 * 24 * 3600 * 1000;

  var supporte = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

  function el(selecteur) { return racine.querySelector(selecteur); }

  function base64VersUint8(b64) {
    var rembourrage = '='.repeat((4 - (b64.length % 4)) % 4);
    var brut = atob((b64 + rembourrage).replace(/-/g, '+').replace(/_/g, '/'));
    var sortie = new Uint8Array(brut.length);
    for (var i = 0; i < brut.length; i++) sortie[i] = brut.charCodeAt(i);
    return sortie;
  }

  function post(url, corps) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(corps),
    });
  }

  function lire(cleStockage) {
    try { return window.localStorage.getItem(cleStockage); } catch (e) { return null; }
  }
  function ecrire(cleStockage, valeur) {
    try { window.localStorage.setItem(cleStockage, valeur); } catch (e) { /* navigation privée */ }
  }

  async function abonnementActuel() {
    var reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }

  // Demande l'autorisation puis enregistre l'appareil. Retourne "ok" ou "refuse".
  async function activer() {
    var permission = await Notification.requestPermission();
    if (permission !== 'granted') return 'refuse';
    var reg = await navigator.serviceWorker.ready;
    var abonnement = await reg.pushManager.getSubscription();
    if (!abonnement) {
      var options = { userVisibleOnly: true, applicationServerKey: base64VersUint8(cle) };
      try {
        abonnement = await reg.pushManager.subscribe(options);
      } catch (e) {
        // Clés d'envoi changées depuis le dernier abonnement : on repart de zéro.
        var ancien = await reg.pushManager.getSubscription();
        if (ancien) await ancien.unsubscribe();
        abonnement = await reg.pushManager.subscribe(options);
      }
    }
    var reponse = await post(urlAbonner, abonnement.toJSON());
    if (!reponse.ok) throw new Error('Enregistrement refusé par le serveur');
    return 'ok';
  }

  async function desactiver() {
    var abonnement = await abonnementActuel();
    if (!abonnement) return;
    var endpoint = abonnement.endpoint;
    await abonnement.unsubscribe();
    await post(urlDesabonner, { endpoint: endpoint });
  }

  // ------------------------------------------------------------ bandeau (accueil)
  async function initBandeau() {
    if (!supporte || !cle) return;
    if (Notification.permission === 'denied') return;
    var plusTard = parseInt(lire(CLE_PLUS_TARD) || '0', 10);
    if (plusTard && Date.now() - plusTard < DELAI_PLUS_TARD_MS) return;
    var abonnement = await abonnementActuel();
    // Déjà abonné sur cet appareil : rien à proposer. Autorisation accordée mais sans abonnement
    // (abonnement perdu) : on repropose.
    if (abonnement) return;
    racine.hidden = false;

    var retour = el('[data-retour]');
    el('[data-action="activer"]').addEventListener('click', async function (evt) {
      var bouton = evt.currentTarget;
      bouton.disabled = true;
      try {
        var etat = await activer();
        if (etat === 'ok') {
          racine.innerHTML = '<p class="notif-invitation-retour">Notifications activées sur cet appareil. Tu peux régler ce que tu reçois dans « Notifications ».</p>';
          setTimeout(function () { racine.hidden = true; }, 6000);
        } else {
          ecrire(CLE_PLUS_TARD, String(Date.now()));
          racine.hidden = true;
        }
      } catch (e) {
        bouton.disabled = false;
        retour.textContent = "L'activation a échoué. Réessaie, ou utilise la page « Notifications ».";
        retour.hidden = false;
      }
    });
    el('[data-action="plus-tard"]').addEventListener('click', function () {
      ecrire(CLE_PLUS_TARD, String(Date.now()));
      racine.hidden = true;
    });
  }

  // ------------------------------------------------------------ page de réglages
  async function initPage() {
    var statut = el('[data-statut]');
    var aide = el('[data-aide]');
    var boutonActiver = el('[data-action="activer"]');
    var boutonDesactiver = el('[data-action="desactiver"]');
    // Bloc « Tester » : visible seulement si CET appareil est abonné (hors de la section).
    var blocTest = document.querySelector('[data-test]');

    function montrerAide(texte) { aide.textContent = texte; aide.hidden = !texte; }

    async function rafraichir() {
      boutonActiver.hidden = true;
      boutonDesactiver.hidden = true;
      if (blocTest) blocTest.hidden = true;
      montrerAide('');
      if (!supporte || !cle) {
        statut.textContent = "Cet appareil ne permet pas les notifications ici.";
        montrerAide("Sur iPhone, ajoute d'abord Anki à l'écran d'accueil (voir plus bas), puis rouvre-le depuis son icône.");
        return;
      }
      if (Notification.permission === 'denied') {
        statut.textContent = "Notifications bloquées sur cet appareil.";
        montrerAide("Pour les réactiver : réglages du téléphone ou du navigateur, autorisations du site, Notifications.");
        return;
      }
      var abonnement = await abonnementActuel();
      if (abonnement) {
        statut.textContent = 'Notifications activées sur cet appareil.';
        boutonDesactiver.hidden = false;
        if (blocTest) blocTest.hidden = false;
      } else {
        statut.textContent = "Notifications désactivées sur cet appareil.";
        boutonActiver.hidden = false;
      }
    }

    // Aucun rechargement de page : sur Android, une navigation vers une adresse couverte par
    // une appli installée peut ouvrir cette appli au lieu de rester dans le navigateur.
    boutonActiver.addEventListener('click', async function () {
      boutonActiver.disabled = true;
      var reussi = false;
      try {
        reussi = (await activer()) === 'ok';
      } catch (e) {
        montrerAide("L'activation a échoué. Réessaie dans un instant.");
      }
      boutonActiver.disabled = false;
      await rafraichir();
    });
    boutonDesactiver.addEventListener('click', async function () {
      boutonDesactiver.disabled = true;
      var reussi = false;
      try {
        await desactiver();
        reussi = true;
      } catch (e) {
        montrerAide("La désactivation a échoué. Réessaie dans un instant.");
      }
      boutonDesactiver.disabled = false;
      await rafraichir();
    });

    await rafraichir();
  }

  if (mode === 'invitation') initBandeau().catch(function () {});
  else if (mode === 'page') initPage().catch(function () {});
})();
