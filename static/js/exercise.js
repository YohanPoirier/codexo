(function () {
  const editor = document.getElementById("code-editor");
  const runBtn = document.getElementById("run-btn");
  const resultBox = document.getElementById("result-box");
  const solutionBox = document.getElementById("solution-reveal");
  const solutionCodeEl = document.getElementById("solution-reveal-code");

  let pyodide = null;
  let testCode = "";
  let solutionCode = "";
  let cm = null; // instance CodeMirror de l'éditeur, créée dans init()
  let solutionCM = null; // instance CodeMirror (lecture seule) du corrigé, créée à la 1ère réussite

  // --- Suivi du temps passé : voir submitResult() plus bas pour le détail du calcul ---
  let lastCheckpoint = Date.now();

  function elapsedSecondsSinceCheckpoint() {
    const now = Date.now();
    const seconds = Math.max(0, Math.round((now - lastCheckpoint) / 1000));
    lastCheckpoint = now;
    return seconds;
  }

  function getCode() {
    return cm ? cm.getValue() : editor.value;
  }
  function setCode(value) {
    if (cm) cm.setValue(value);
    else editor.value = value;
  }

  function getCookie(name) {
    const match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function showRuntimeError(text) {
    resultBox.classList.remove("hidden", "all-success", "all-error");
    resultBox.classList.add("all-error");
    resultBox.innerHTML =
      '<div class="result-line fail"><span class="result-icon">✗</span><pre class="result-msg">' +
      escapeHtml(text) +
      "</pre></div>";
  }

  function prefixLines(text) {
    return text
      .replace(/\n$/, "") // évite une ligne vide en trop à la fin (print ajoute déjà un \n)
      .split("\n")
      .map((line) => ">> " + line)
      .join("\n");
  }

  // Mémorise quels menus "Affichages" sont ouverts, pour les garder ouverts
  // d'une vérification à l'autre (les tests restent dans le même ordre).
  const openPrintIndices = new Set();

  function showResultLines(items) {
    resultBox.classList.remove("hidden", "all-success", "all-error");
    const allOk = items.length > 0 && items.every((it) => it.ok);
    resultBox.classList.add(allOk ? "all-success" : "all-error");

    resultBox.innerHTML = items
      .map((it, i) => {
        const printsBlock = it.printed
          ? '<details class="prints-toggle" data-index="' + i + '"' +
            (openPrintIndices.has(i) ? " open" : "") + ">" +
            '<summary>Affichages <span class="info-dot" title="Ce que print() a affiché pendant ce test">?</span></summary>' +
            '<pre class="prints-output">' + escapeHtml(prefixLines(it.printed)) + "</pre>" +
            "</details>"
          : "";
        return (
          '<div class="result-line ' +
          (it.ok ? "ok" : "fail") +
          '">' +
          '<span class="result-icon">' + (it.ok ? "✓" : "✗") + "</span>" +
          '<div class="result-body">' +
          '<span class="result-msg">' + escapeHtml(it.msg) + "</span>" +
          printsBlock +
          "</div>" +
          "</div>"
        );
      })
      .join("");

    resultBox.querySelectorAll(".prints-toggle").forEach((el) => {
      el.addEventListener("toggle", function () {
        const idx = Number(el.dataset.index);
        if (el.open) openPrintIndices.add(idx);
        else openPrintIndices.delete(idx);
      });
    });
  }

  // Affiche (ou masque) le corrigé sous les résultats. Affiché uniquement quand TOUS les
  // tests de la vérification en cours passent — masqué sinon, pour ne pas laisser un vieux
  // corrigé visible à tort si l'étudiant modifie son code puis relance une vérification ratée.
  function showSolutionIfSuccess(allOk) {
    if (!solutionBox || !solutionCodeEl) return;
    if (allOk && solutionCode) {
      // Démasquer AVANT de créer/rafraîchir CodeMirror : un CodeMirror initialisé (ou
      // mesuré) dans un conteneur encore "hidden" (display:none) calcule mal ses
      // dimensions et s'affiche ensuite tout rétréci/mal formaté.
      solutionBox.hidden = false;
      if (!solutionCM) {
        solutionCM = CodeMirror(solutionCodeEl, {
          value: solutionCode,
          mode: EXERCISE_KIND === "sql" ? "text/x-sql" : "python",
          lineNumbers: true,
          readOnly: true,
          viewportMargin: Infinity,
        });
      } else {
        solutionCM.setValue(solutionCode);
        solutionCM.refresh();
      }
    } else {
      solutionBox.hidden = true;
    }
  }

  const resetBtn = document.getElementById("reset-btn");
  let starterCode = "";

  // --- Indices : révélation progressive, un clic = un indice de plus ---
  const hintBtn = document.getElementById("hint-btn");
  if (hintBtn) {
    const hintItems = Array.from(document.querySelectorAll(".hint-item"));
    let revealedCount = 0;

    hintBtn.addEventListener("click", function () {
      if (revealedCount < hintItems.length) {
        const item = hintItems[revealedCount];
        item.classList.remove("hidden");

        // Signale au serveur que cet indice a été vu (voir HintReveal côté Django),
        // pour la page de stats. HINT_VIEWED_URL_TEMPLATE contient un "0" à la place
        // de l'id, injecté par le template (voir exercise_detail.html).
        const hintId = item.dataset.hintId;
        if (hintId && typeof HINT_VIEWED_URL_TEMPLATE !== "undefined") {
          fetch(HINT_VIEWED_URL_TEMPLATE.replace("/0/", "/" + hintId + "/"), {
            method: "POST",
            headers: { "X-CSRFToken": getCookie("csrftoken") },
          }).catch(() => {
            /* silencieux : un indice non comptabilisé ne doit pas gêner l'étudiant */
          });
        }

        revealedCount++;
        if (revealedCount >= hintItems.length) {
          hintBtn.classList.add("hidden");
        }
      }
    });
  }

  // --- Coloration syntaxique : enveloppe la textarea #code-editor avec CodeMirror.
  // fromTextArea() garde la textarea d'origine en mémoire (cachée) et permet de
  // resynchroniser sa valeur avec cm.save() — mais ici on lit/écrit directement
  // via cm.getValue() / cm.setValue(), donc getCode()/setCode() suffisent partout
  // ailleurs dans ce fichier, pas besoin d'appeler cm.save() manuellement.
  function initCodeMirror(initialValue) {
    editor.value = initialValue; // valeur de secours si CodeMirror ne charge pas (CDN indisponible)
    cm = CodeMirror.fromTextArea(editor, {
      mode: EXERCISE_KIND === "sql" ? "text/x-sql" : "python",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      viewportMargin: Infinity, // la zone grandit avec le contenu plutôt que scroller en interne
      extraKeys: {
        Tab: function (cmInstance) {
          if (cmInstance.somethingSelected()) {
            cmInstance.execCommand("indentMore");
          } else {
            cmInstance.replaceSelection("    ", "end");
          }
        },
        "Shift-Tab": "indentLess",
      },
    });
    cm.setValue(initialValue);
  }

  async function init() {
    try {
      const res = await fetch(TESTS_URL);
      const data = await res.json();
      starterCode = data.starter_code || "";
      testCode = data.test_code || "";
      solutionCode = data.solution_code || "";
    } catch (e) {
      runBtn.textContent = "Erreur : exercice non chargé";
      return;
    }

    // LAST_SUBMITTED_CODE est injecté par le template : le code de la dernière
    // tentative enregistrée en base pour cet exercice (ou null si aucune).
    const initialCode =
      LAST_SUBMITTED_CODE !== null && LAST_SUBMITTED_CODE !== "" ? LAST_SUBMITTED_CODE : starterCode;
    initCodeMirror(initialCode);

    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";
    try {
      pyodide = await loadPyodide();
      // testCode inclut déjà le texte de solution_code (voir Exercise.build_test_code
      // côté serveur) : si l'exercice utilise numpy, "numpy" apparaît forcément dans
      // testCode. On ne charge donc le package que pour les exercices qui en ont besoin,
      // pas systématiquement pour tous (évite d'alourdir le chargement des exercices
      // qui n'en ont pas l'usage).
      if (testCode.includes("numpy")) {
        await pyodide.loadPackage("numpy");
      }
    } catch (e) {
      runBtn.textContent = "Erreur de chargement de Python";
      return;
    }
    runBtn.disabled = false;
    runBtn.textContent = "Vérifier";
  }

  async function submitResult(code, success, isAttempt) {
    // Temps écoulé depuis le dernier enregistrement (ou depuis le chargement de la page
    // si c'est le premier) : voir Result.time_seconds côté serveur. En sommant ce champ sur
    // toutes les lignes d'un couple (user, exercise), on obtient le temps total passé, même
    // si l'étudiant a quitté puis repris l'exercice plusieurs fois (chaque retour recharge la
    // page, donc lastCheckpoint repart de zéro, mais rien n'est compté pendant que l'onglet
    // était fermé, puisqu'aucun événement ne se déclenche à ce moment-là).
    const timeSeconds = elapsedSecondsSinceCheckpoint();
    try {
      await fetch(SUBMIT_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ code, success, is_attempt: !!isAttempt, time_seconds: timeSeconds }),
      });
    } catch (e) {
      /* silencieux : l'échec de sauvegarde ne doit pas bloquer le retour visuel */
    }
  }

  async function runCheck() {
    const code = getCode();
    runBtn.disabled = true;
    runBtn.textContent = "Vérification…";
    resultBox.classList.add("hidden");
    if (solutionBox) solutionBox.hidden = true;

    try {
      pyodide.globals.set("__TEST_CODE__", testCode);

      let runner;
      if (EXERCISE_KIND === "sql") {
        // En SQL, le texte de l'étudiant est une REQUÊTE, pas du code Python à exécuter :
        // on le passe tel quel comme variable, test_code (généré côté serveur) s'occupe
        // de l'exécuter via sqlite3 et de comparer le résultat à la requête de correction.
        pyodide.globals.set("__STUDENT_SQL__", code);
        runner = `
import sys, io, traceback

__stdout_capture__ = io.StringIO()
__RESULTS__ = []
__RUNTIME_ERROR__ = None

_old_stdout = sys.stdout
sys.stdout = __stdout_capture__
try:
    exec(__TEST_CODE__, globals())
except Exception:
    __RUNTIME_ERROR__ = traceback.format_exc()
finally:
    sys.stdout = _old_stdout
`;
      } else {
        pyodide.globals.set("__STUDENT_CODE__", code);
        runner = `
import sys, io, traceback

__stdout_capture__ = io.StringIO()
__RESULTS__ = []
__RUNTIME_ERROR__ = None

_old_stdout = sys.stdout
sys.stdout = __stdout_capture__
try:
    exec(__STUDENT_CODE__, globals())
    exec(__TEST_CODE__, globals())
except Exception:
    __RUNTIME_ERROR__ = traceback.format_exc()
finally:
    sys.stdout = _old_stdout
`;
      }
      await pyodide.runPythonAsync(runner);

      const runtimeError = pyodide.globals.get("__RUNTIME_ERROR__");
      if (runtimeError) {
        showRuntimeError("Erreur dans ton code :\n\n" + runtimeError);
        showSolutionIfSuccess(false);
        await submitResult(code, false, true);
      } else {
        const resultsProxy = pyodide.globals.get("__RESULTS__");
        const results = resultsProxy ? resultsProxy.toJs() : [];
        const items = results.map((item) => ({ ok: item[0], msg: item[1], printed: item[2] || "" }));
        if (items.length === 0) items.push({ ok: false, msg: "Aucun test défini pour cet exercice." });
        const allOk = items.length > 0 && items.every((it) => it.ok);
        // Si tout est bon, inutile d'afficher le détail des tests un par un : le corrigé
        // (voir showSolutionIfSuccess) suffit comme confirmation. resultBox reste donc caché
        // (déjà mis à "hidden" en début de runCheck) — on ne l'affiche qu'en cas d'échec,
        // pour aider l'étudiant à comprendre ce qui ne va pas.
        if (!allOk) {
          showResultLines(items);
        }
        showSolutionIfSuccess(allOk);
        await submitResult(code, allOk, true);
      }
    } catch (e) {
      showRuntimeError("Erreur inattendue : " + e.message);
      showSolutionIfSuccess(false);
    }

    runBtn.disabled = false;
    runBtn.textContent = "Vérifier";
  }

  resetBtn.addEventListener("click", function () {
    if (getCode().trim() === starterCode.trim()) return;
    const confirmed = window.confirm(
      "Revenir au code de départ ? Ton code actuel dans l'éditeur sera perdu (mais tes tentatives déjà validées restent enregistrées)."
    );
    if (confirmed) {
      setCode(starterCode);
      resultBox.classList.add("hidden");
      if (solutionBox) solutionBox.hidden = true;
    }
  });

  // Sauvegarde automatique du code en cours quand l'étudiant quitte la page (ex: clique sur
  // "Thèmes", "Progression", ferme l'onglet...), même s'il n'a pas cliqué sur "Vérifier".
  // NB : on marque ces sauvegardes success=false (on n'a pas le temps de relancer les tests
  // à ce moment précis) — ça n'affecte pas /profil/, qui ne compte que les tentatives réussies.
  //
  // On utilise navigator.sendBeacon() plutôt que fetch : c'est l'API conçue spécifiquement
  // pour "envoyer une petite requête juste avant que la page se ferme", et le navigateur
  // s'engage à essayer de l'envoyer même si la page est détruite juste après l'appel — ce que
  // fetch(..., { keepalive: true }) ne garantit pas dans tous les cas (fermeture brutale d'onglet).
  // sendBeacon ne permet pas d'ajouter un header personnalisé, donc le jeton CSRF est envoyé
  // dans le corps de la requête au format formulaire classique ('csrfmiddlewaretoken'),
  // que Django sait lire nativement (voir submit_result dans views.py).
  //
  // Deux événements déclenchent la sauvegarde car aucun des deux n'est fiable à 100% seul :
  // - 'pagehide' : se déclenche à la fermeture/navigation.
  // - 'visibilitychange' : se déclenche dès que l'onglet passe en arrière-plan (changement
  //   d'appli, verrouillage d'écran...), donc plus tôt et plus fiable sur mobile.
  let lastSavedCode = null; // évite une double sauvegarde si les deux événements se déclenchent l'un après l'autre

  function saveDraftOnLeave() {
    if (!testCode) return; // page pas encore chargée, rien à sauvegarder
    const code = getCode();
    if (code === lastSavedCode) return; // déjà sauvegardé (ex: pagehide juste après visibilitychange)
    lastSavedCode = code;

    // is_attempt="" (donc False côté serveur, voir submit_result) : une sauvegarde au départ
    // de la page n'est pas un "essai" au sens propre, l'étudiant n'a pas cliqué sur "Vérifier".
    const timeSeconds = elapsedSecondsSinceCheckpoint();

    const payload = new URLSearchParams();
    payload.set("code", code);
    payload.set("success", "");
    payload.set("is_attempt", "");
    payload.set("time_seconds", String(timeSeconds));
    payload.set("csrfmiddlewaretoken", getCookie("csrftoken"));

    const sent = navigator.sendBeacon && navigator.sendBeacon(SUBMIT_URL, payload);
    if (!sent) {
      // Repli si sendBeacon est indisponible (très rare) ou refuse l'envoi (payload trop gros)
      fetch(SUBMIT_URL, {
        method: "POST",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ code, success: false, is_attempt: false, time_seconds: timeSeconds }),
      }).catch(() => {});
    }
  }

  window.addEventListener("pagehide", saveDraftOnLeave);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") saveDraftOnLeave();
  });

  // Bouton disquette : enregistrement manuel explicite, sur simple clic.
  const saveBtn = document.getElementById("save-btn");
  const saveConfirm = document.getElementById("save-confirm");
  if (saveBtn) {
    saveBtn.addEventListener("click", async function () {
      await submitResult(getCode(), false, false);
      if (saveConfirm) {
        saveConfirm.classList.add("visible");
        setTimeout(() => saveConfirm.classList.remove("visible"), 1500);
      }
    });
  }

  // Bouton "Abandonner" : ouvre une fenêtre de confirmation personnalisée (plus adaptée au
  // mobile et plus flexible qu'un window.confirm natif, qui n'autorise ni texte long formaté
  // ni libellés de boutons personnalisés). La confirmation elle-même est un vrai formulaire
  // HTML (voir exercise_detail.html), pas un fetch : plus simple et plus robuste.
  const abandonBtn = document.getElementById("abandon-btn");
  const abandonModal = document.getElementById("abandon-modal");
  const abandonCancel = document.getElementById("abandon-cancel");
  if (abandonBtn && abandonModal) {
    abandonBtn.addEventListener("click", function () {
      abandonModal.classList.add("open");
    });
    abandonCancel.addEventListener("click", function () {
      abandonModal.classList.remove("open");
    });
    abandonModal.addEventListener("click", function (e) {
      if (e.target === abandonModal) abandonModal.classList.remove("open"); // clic sur le fond
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") abandonModal.classList.remove("open");
    });
  }

  runBtn.addEventListener("click", runCheck);
  init();
})();
