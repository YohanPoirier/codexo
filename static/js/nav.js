(function () {
  const toggle = document.getElementById("nav-toggle");
  const nav = document.getElementById("site-nav");
  if (!toggle || !nav) return;

  toggle.addEventListener("click", function () {
    const isOpen = nav.classList.toggle("open");
    toggle.classList.toggle("open", isOpen);
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  // Referme le menu si on clique sur un lien ou sur le bouton "Déconnexion" (utile en
  // navigation sur la même page, sinon le menu resterait ouvert visuellement pendant le
  // chargement de la page suivante). Le bouton de déconnexion est inclus ici : ce n'est
  // plus un <a> mais un <button> dans un <form>, depuis le passage de la déconnexion en
  // POST (LogoutView de Django exige POST, un lien <a> classique ferait un GET et
  // provoquerait une erreur 405).
  nav.querySelectorAll("a, .nav-link-btn").forEach(function (link) {
    link.addEventListener("click", function () {
      nav.classList.remove("open");
      toggle.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    });
  });

  // Menu déroulant "Espace prof" (ajout du 06/09/2026, regroupe les liens réservés
  // aux profs qui étaient auparavant à plat dans la nav, voir base.html/style.css).
  // Le bouton ".nav-dropdown-toggle" n'est volontairement PAS un ".nav-link-btn" :
  // le boucle ci-dessus fermerait tout le menu mobile au clic dessus, alors qu'on
  // veut seulement ouvrir/fermer le sous-menu.
  document.querySelectorAll(".nav-dropdown").forEach(function (dropdown) {
    const dropToggle = dropdown.querySelector(".nav-dropdown-toggle");
    const menu = dropdown.querySelector(".nav-dropdown-menu");
    if (!dropToggle || !menu) return;

    dropToggle.addEventListener("click", function (event) {
      event.stopPropagation();
      const isOpen = menu.classList.toggle("open");
      dropToggle.classList.toggle("open", isOpen);
      dropToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  });

  // Ferme tout menu déroulant "Espace prof" ouvert si on clique en dehors de
  // celui-ci (les clics sur les liens à l'intérieur le ferment déjà via la boucle
  // "a, .nav-link-btn" ci-dessus, puisque ce sont de vrais <a>).
  document.addEventListener("click", function (event) {
    document.querySelectorAll(".nav-dropdown").forEach(function (dropdown) {
      if (dropdown.contains(event.target)) return;
      const dropToggle = dropdown.querySelector(".nav-dropdown-toggle");
      const menu = dropdown.querySelector(".nav-dropdown-menu");
      if (menu) menu.classList.remove("open");
      if (dropToggle) {
        dropToggle.classList.remove("open");
        dropToggle.setAttribute("aria-expanded", "false");
      }
    });
  });
})();
