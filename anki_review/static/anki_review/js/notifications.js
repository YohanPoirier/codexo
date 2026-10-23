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
  // Appli et service worker auxquels rattacher l'abonnement (cf. static/js/pwa.js).
  var appli = racine.dataset.appli || 'anki';
  var urlSw = racine.dataset.sw || '/sw.js';
  var perimetre = racine.dataset.scope || '/';

  // Une clé par appli : « Plus tard » sur Codexo ne doit pas masquer le bandeau d'Anki.
  var CLE_PLUS_TARD = appli === 'codexo' ? 'codexo-notifications-plus-tard' : 'anki-notifications-plus-tard';
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

  // Enregistrement du service worker de cette appli, une fois actif (s'il est déjà
  // enregistré, register() renvoie simplement l'existant).
  async function registrationAppli() {
    var reg = await navigator.serviceWorker.register(urlSw, { scope: perimetre });
    if (reg.active) return reg;
    var travailleur = reg.installing || reg.waiting;
    if (!travailleur) return navigator.serviceWorker.ready;
    await new Promise(function (ok) {
      travailleur.addEventListener('statechange', function () {
        if (travailleur.state === 'activated') ok();
      });
    });
    return reg;
  }

  async function abonnementActuel() {
    var reg = await registrationAppli();
    return reg.pushManager.getSubscription();
  }

  // Bascule automatique (sans geste de l'utilisateur) : notifications déjà autorisées, pas
  // encore d'abonnement sur le service worker d'Anki, mais un ancien abonnement Anki sur celui
  // de la racine (pris avant /anki/sw.js). On en crée un nouveau, puis on retire l'ancien —
  // seulement s'il était bien marqué Anki ; sinon (abonnement Codexo) on annule tout.
  async function basculerAncienAbonnement() {
    if (perimetre === '/' || Notification.permission !== 'granted' || !cle) return;
    var reg = await registrationAppli();
    if (await reg.pushManager.getSubscription()) return;
    var racineReg = await navigator.serviceWorker.getRegistration('/');
    if (!racineReg || racineReg.scope !== location.origin + '/') return;
    var ancien = await racineReg.pushManager.getSubscription();
    if (!ancien) return;
    var nouveau = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: base64VersUint8(cle),
    });
    var corps = nouveau.toJSON();
    corps.appli = appli;
    var reponse = await post(urlAbonner, corps);
    if (!reponse.ok) { await nouveau.unsubscribe(); return; }
    var retrait = await post(urlDesabonner, { endpoint: ancien.endpoint, appli: 'anki' });
    var donnees = retrait.ok ? await retrait.json() : {};
    if (donnees.supprimes) {
      await ancien.unsubscribe();
    } else {
      await post(urlDesabonner, { endpoint: nouveau.endpoint });
      await nouveau.unsubscribe();
    }
  }

  // Service worker propre à Anki : l'ancien abonnement Anki pris via le service worker de la
  // racine ferait doublon. Le serveur ne le supprime que s'il est bien marqué Anki (jamais un
  // abonnement Codexo) ; l'appareil ne s'en désinscrit qu'ensuite.
  async function retirerAncienAbonnementRacine() {
    if (perimetre === '/') return;
    var racineReg = await navigator.serviceWorker.getRegistration('/');
    if (!racineReg || racineReg.scope !== location.origin + '/') return;
    var ancien = await racineReg.pushManager.getSubscription();
    if (!ancien) return;
    var reponse = await post(urlDesabonner, { endpoint: ancien.endpoint, appli: 'anki' });
    var donnees = reponse.ok ? await reponse.json() : {};
    if (donnees.supprimes) await ancien.unsubscribe();
  }

  // Demande l'autorisation puis enregistre l'appareil. Retourne "ok" ou "refuse".
  async function activer() {
    var permission = await Notification.requestPermission();
    if (permission !== 'granted') return 'refuse';
    var reg = await registrationAppli();
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
    var corps = abonnement.toJSON();
    corps.appli = appli;
    var reponse = await post(urlAbonner, corps);
    if (!reponse.ok) throw new Error('Enregistrement refusé par le serveur');
    try { await retirerAncienAbonnementRacine(); } catch (e) { /* sans gravité : doublon possible */ }
    return 'ok';
  }

  async function desactiver() {
    var abonnement = await abonnementActuel();
    if (!abonnement) return;
    var endpoint = abonnement.endpoint;
    await abonnement.unsubscribe();
    await post(urlDesabonner, { endpoint: endpoint });
  }

  // Autorisation refusée ou jamais demandée à l'écran : Chrome masque parfois la fenêtre
  // « Autoriser les notifications ? » (site déjà signalé, demandes jugées trop fréquentes) et
  // répond « pas de décision » sans rien montrer. On l'explique au lieu de ne rien faire.
  function texteRefus() {
    if (Notification.permission === 'denied') {
      return "Notifications bloquées pour ce site. Pour les autoriser : touche l'icône à gauche de l'adresse (le cadenas), puis Autorisations, Notifications, Autoriser, et réessaie.";
    }
    return "Ton navigateur n'a pas affiché la demande d'autorisation. Touche l'icône à gauche de l'adresse (cadenas ou cloche barrée), autorise les notifications pour ce site, puis réessaie.";
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
          // Pas d'autorisation : on reste affiché avec l'explication (plutôt que de disparaître
          // comme si tout s'était bien passé).
          bouton.disabled = false;
          retour.textContent = texteRefus();
          retour.hidden = false;
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
      var etat = null;
      try {
        etat = await activer();
      } catch (e) {
        etat = 'erreur';
      }
      boutonActiver.disabled = false;
      await rafraichir();
      if (etat === 'refuse') montrerAide(texteRefus());
      else if (etat === 'erreur') montrerAide("L'activation a échoué. Réessaie dans un instant.");
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

  // La bascule passe avant l'affichage : sinon le bandeau inviterait à réactiver des
  // notifications déjà actives.
  var bascule = supporte ? basculerAncienAbonnement().catch(function () {}) : Promise.resolve();
  bascule.then(function () {
    if (mode === 'invitation') initBandeau().catch(function () {});
    else if (mode === 'page') initPage().catch(function () {});
  });
})();
