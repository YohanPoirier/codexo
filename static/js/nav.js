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
})();
