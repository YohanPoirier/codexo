// Version simplifiée de exercise.js, réservée à la page prof "demande_aide_detail" : permet
// de tester le code soumis par un élève, avec le même moteur Pyodide, mais SANS jamais appeler
// submit_result (pas de sauvegarde automatique, pas d'indices, pas d'abandon) — ce code
// s'exécute sous le compte du PROF, et un Result créé ici serait à tort attribué à sa propre
// progression (voir /profil/) si on réutilisait exercise.js tel quel.
(function () {
  const editor = document.getElementById("code-editor");
  const runBtn = document.getElementById("run-btn");
  const resultBox = document.getElementById("result-box");
  const solutionToggleBtn = document.getElementById("solution-toggle-btn");
  const solutionBox = document.getElementById("solution-reveal");
  const solutionCodeEl = document.getElementById("solution-reveal-code");

  const stopBtn = document.getElementById("stop-btn");

  // Pyodide tourne dans un worker (voir check-worker.js, le même que pour exercise.js) : un code
  // qui boucle sans fin ne fige pas la page, la vérification est coupée au bout de
  // CHECK_TIMEOUT_MS (à garder identique à celui de exercise.js) ou au clic sur « Arrêter ».
  const CHECK_TIMEOUT_MS = 10000;
  let worker = null;
  let ready = false; // le worker a fini de charger Python
  let useNumpy = false;
  // Vérification en cours (null si aucune) : résultats déjà reçus (un par test, au fil de
  // l'eau), appel du test en cours (ex. « nombre_de_lettres('a') », null si inconnu), minuteur.
  let running = null;
  let testCode = "";
  let solutionCode = "";
  let cm = null;
  let solutionCM = null;

  function getCode() {
    return cm ? cm.getValue() : editor.value;
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
      .replace(/\n$/, "")
      .split("\n")
      .map((line) => ">> " + line)
      .join("\n");
  }

  function showResultLines(items) {
    resultBox.classList.remove("hidden", "all-success", "all-error");
    const allOk = items.length > 0 && items.every((it) => it.ok);
    resultBox.classList.add(allOk ? "all-success" : "all-error");

    resultBox.innerHTML = items
      .map((it) => {
        const printsBlock = it.printed
          ? '<details class="prints-toggle">' +
            "<summary>Ce qui a été affiché</summary>" +
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
  }

  function initCodeMirror(initialValue) {
    editor.value = initialValue;
    cm = CodeMirror.fromTextArea(editor, {
      mode: EXERCISE_KIND === "sql" ? "text/x-sql" : "python",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      viewportMargin: Infinity,
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
      testCode = data.test_code || "";
      solutionCode = data.solution_code || "";
    } catch (e) {
      runBtn.textContent = "Erreur : exercice non chargé";
      return;
    }

    initCodeMirror(typeof INITIAL_CODE !== "undefined" && INITIAL_CODE ? INITIAL_CODE : "");

    useNumpy = /(import|from)\s+numpy\b/.test(testCode);
    startWorker();
  }

  // --- Worker : démarrage, messages, arrêt ---
  function startWorker() {
    ready = false;
    runBtn.disabled = true;
    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";

    const w = new Worker(CHECK_WORKER_URL);
    worker = w;

    w.onmessage = function (ev) {
      if (w !== worker) return; // message d'un ancien worker (déjà arrêté)
      const msg = ev.data;
      if (msg.type === "ready") {
        ready = true;
        runBtn.disabled = false;
        runBtn.textContent = "Tester ce code";
      } else if (msg.type === "start") {
        if (running) running.current = msg.call;
      } else if (msg.type === "result") {
        if (running) {
          running.items.push({ ok: msg.ok, msg: msg.msg, printed: msg.printed || "" });
          running.current = null;
        }
      } else if (msg.type === "done") {
        onCheckDone(msg);
      } else if (msg.type === "fatal") {
        runBtn.textContent = "Erreur de chargement de Python";
      }
    };

    // Erreur du worker lui-même (script introuvable, CDN indisponible, plantage...)
    w.onerror = function () {
      if (w !== worker) return;
      if (!ready) {
        runBtn.textContent = "Erreur de chargement de Python";
        return;
      }
      if (running) interruptCheck("Erreur inattendue du moteur Python.");
      else startWorker();
    };

    w.postMessage({ type: "init", numpy: useNumpy, sqlite: EXERCISE_KIND === "sql" });
  }

  function endRun() {
    if (running && running.timer) clearTimeout(running.timer);
    running = null;
    if (stopBtn) stopBtn.hidden = true;
  }

  // Coupe net la vérification en cours (limite de temps, bouton « Arrêter ») : on supprime le
  // worker puis on en relance un neuf. Les résultats des tests déjà terminés restent affichés,
  // suivis du motif de l'interruption.
  function interruptCheck(reason) {
    if (!running) return;
    const items = running.items.slice();
    endRun();

    const old = worker;
    worker = null; // les derniers messages éventuels de l'ancien worker seront ignorés
    if (old) old.terminate();
    startWorker();

    showResultLines(items.concat([{ ok: false, msg: reason, printed: "" }]));
  }

  function onTimeout() {
    if (!running) return;
    const seconds = Math.round(CHECK_TIMEOUT_MS / 1000);
    const which = running.current
      ? running.current + " : le test ne s'est pas terminé"
      : "La vérification ne s'est pas terminée";
    interruptCheck(
      which + " en moins de " + seconds + " secondes (boucle infinie ?). Vérifier les " +
        "conditions d'arrêt des boucles et des appels récursifs."
    );
  }

  if (stopBtn) {
    stopBtn.addEventListener("click", function () {
      interruptCheck("Vérification interrompue.");
    });
  }

  function runCheck() {
    if (!ready || running) return;
    const code = getCode();
    running = { items: [], current: null, timer: null };
    runBtn.disabled = true;
    runBtn.textContent = "Vérification…";
    if (stopBtn) stopBtn.hidden = false;
    resultBox.classList.add("hidden");

    running.timer = setTimeout(onTimeout, CHECK_TIMEOUT_MS);
    worker.postMessage({ type: "run", kind: EXERCISE_KIND, code: code, testCode: testCode });
  }

  // Fin normale de la vérification (message « done » du worker).
  function onCheckDone(msg) {
    if (!running) return;
    endRun();

    if (msg.runtimeError) {
      showRuntimeError("Erreur dans ce code :\n\n" + msg.runtimeError);
    } else {
      const items = (msg.results || []).map((item) => ({ ok: item[0], msg: item[1], printed: item[2] || "" }));
      if (items.length === 0) items.push({ ok: false, msg: "Aucun test défini pour cet exercice." });
      showResultLines(items);
    }

    runBtn.disabled = false;
    runBtn.textContent = "Tester ce code";
  }

  // Bouton manuel "Voir le corrigé" : contrairement à la page élève (exercise.js), le corrigé
  // n'est pas conditionné à une réussite — le prof doit pouvoir le consulter à tout moment
  // pour aider l'élève, sans avoir à faire passer les tests au code soumis au préalable.
  if (solutionToggleBtn && solutionBox && solutionCodeEl) {
    solutionToggleBtn.addEventListener("click", function () {
      const opening = solutionBox.hidden;
      if (opening) {
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
          solutionCM.refresh();
        }
        solutionToggleBtn.textContent = "Cacher le corrigé";
      } else {
        solutionBox.hidden = true;
        solutionToggleBtn.textContent = "Voir le corrigé";
      }
    });
  }

  runBtn.addEventListener("click", runCheck);
  init();
})();
