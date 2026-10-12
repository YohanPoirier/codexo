(function () {
  const editor = document.getElementById("sandbox-editor");
  const runBtn = document.getElementById("sandbox-run-btn");
  const stopBtn = document.getElementById("sandbox-stop-btn");
  const clearBtn = document.getElementById("sandbox-clear-btn");
  const output = document.getElementById("sandbox-output");

  const STORAGE_KEY = "codexo-sandbox-code";
  const DEFAULT_CODE = "# Écrivez votre code ici\nprint(\"Bonjour !\")\n";
  // Garde-fou : un programme qui affiche sans fin ne doit pas faire exploser la page.
  const MAX_PRINT_CHARS = 200000;

  let cm = null;
  let worker = null; // Pyodide tourne dans un worker (voir sandbox-worker.js)
  let ready = false;
  let running = false;

  // Sortie de l'exécution en cours (les print() arrivent au fil de l'eau)
  let printedText = "";
  let truncated = false;
  let renderTimer = null;

  // --- Sauvegarde locale (navigateur uniquement, rien n'est envoyé au serveur) ---
  function loadSavedCode() {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      return saved !== null ? saved : DEFAULT_CODE;
    } catch (e) {
      return DEFAULT_CODE; // stockage indisponible (navigation privée, etc.)
    }
  }
  function saveCode(code) {
    try {
      window.localStorage.setItem(STORAGE_KEY, code);
    } catch (e) {
      /* silencieux : la sauvegarde locale n'est qu'un confort */
    }
  }

  function getCode() {
    return cm ? cm.getValue() : editor.value;
  }
  function setCode(value) {
    if (cm) cm.setValue(value);
    else editor.value = value;
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // --- Éditeur (mêmes réglages que les exercices, voir exercise.js) ---
  function insertTabAtCursor(cmInstance) {
    if (cmInstance.somethingSelected()) {
      cmInstance.execCommand("indentMore");
    } else {
      cmInstance.replaceSelection("    ", "end");
    }
  }

  const PYTHON_HINT_WORDS = [
    "and", "as", "assert", "break", "class", "continue", "def", "del", "elif", "else",
    "except", "False", "finally", "for", "from", "if", "import", "in", "is", "lambda",
    "None", "not", "or", "pass", "print", "raise", "return", "True", "try", "while", "with",
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "map",
    "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "type", "zip",
  ];

  function pythonHint(cmInstance) {
    const cursor = cmInstance.getCursor();
    const line = cmInstance.getLine(cursor.line);
    let start = cursor.ch;
    while (start > 0 && /\w/.test(line.charAt(start - 1))) start--;
    const typed = line.slice(start, cursor.ch);
    if (!typed) return { list: [], from: cursor, to: cursor };

    const anywordResult = CodeMirror.hint.anyword(cmInstance) || { list: [] };
    const fromKeywords = PYTHON_HINT_WORDS.filter((w) => w.startsWith(typed) && w !== typed);
    const list = Array.from(new Set([...fromKeywords, ...anywordResult.list]));
    return { list, from: CodeMirror.Pos(cursor.line, start), to: CodeMirror.Pos(cursor.line, cursor.ch) };
  }

  function initCodeMirror(initialValue) {
    editor.value = initialValue; // valeur de secours si CodeMirror ne charge pas (CDN indisponible)
    if (typeof CodeMirror === "undefined") return;
    const isMobile = window.matchMedia("(max-width: 640px)").matches;
    const rulers = isMobile
      ? [4, 8, 12, 16, 20, 24, 28, 32].map((col) => ({
          column: col,
          color: "rgba(255,255,255,.12)",
          lineStyle: "solid",
        }))
      : false;
    cm = CodeMirror.fromTextArea(editor, {
      mode: "python",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      viewportMargin: Infinity,
      lineWrapping: true,
      rulers: rulers,
      hintOptions: { hint: pythonHint, completeSingle: false },
      extraKeys: {
        Tab: insertTabAtCursor,
        "Shift-Tab": "indentLess",
        "Ctrl-Space": "autocomplete",
        "Ctrl-Enter": function () { runCode(); },
      },
    });
    cm.on("inputRead", function (instance, change) {
      if (change.origin !== "+input") return;
      const lastChar = change.text[change.text.length - 1];
      if (!lastChar || !/\w/.test(lastChar)) return;
      if (instance.state.completionActive) return;
      instance.showHint({ hint: pythonHint, completeSingle: false });
    });
    cm.setValue(initialValue);
  }

  // --- Fenêtre de résultat : blocs « print », « erreur » et « information » ---
  function block(kind, title, text) {
    return (
      '<div class="sandbox-block sandbox-' + kind + '">' +
      '<span class="sandbox-block-title">' + title + "</span>" +
      "<pre>" + escapeHtml(text) + "</pre>" +
      "</div>"
    );
  }

  // isRunning : exécution en cours (rien d'affiché pour l'instant => « en cours »)
  // error     : texte de l'erreur à afficher en rouge (ou null)
  // notice    : message d'information (ex. exécution interrompue)
  function render(isRunning, error, notice) {
    let html = "";
    if (printedText) {
      let text = printedText.replace(/\n$/, "");
      if (truncated) text += "\n… (affichage tronqué)";
      html += block("print", "Affichage (print)", text);
    }
    if (error) html += block("error", "Erreur", error.replace(/\n$/, ""));
    if (notice) html += block("notice", "Information", notice);
    if (!html) {
      html = isRunning
        ? '<p class="sandbox-placeholder">Exécution en cours…</p>'
        : '<p class="sandbox-placeholder">Le code s\'est exécuté sans rien afficher.</p>';
    }
    output.innerHTML = html;
  }

  function resetOutput() {
    printedText = "";
    truncated = false;
    output.innerHTML = '<p class="sandbox-placeholder">Le résultat de l\'exécution apparaîtra ici.</p>';
  }

  // Les print() arrivent un par un : on regroupe les mises à jour de l'affichage (toutes les
  // 100 ms au plus) pour ne pas saturer la page si le programme affiche à toute vitesse.
  function scheduleRender() {
    if (renderTimer) return;
    renderTimer = setTimeout(function () {
      renderTimer = null;
      if (running) render(true, null, null);
    }, 100);
  }

  function setIdle() {
    running = false;
    stopBtn.hidden = true;
    runBtn.disabled = false;
    runBtn.textContent = "Exécuter";
  }

  // --- Worker : démarrage, messages, arrêt ---
  function startWorker() {
    ready = false;
    runBtn.disabled = true;
    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";

    const w = new Worker(SANDBOX_WORKER_URL);
    worker = w;

    w.onmessage = function (ev) {
      if (w !== worker) return; // message d'un ancien worker (déjà arrêté)
      const msg = ev.data;
      if (msg.type === "ready") {
        ready = true;
        setIdle();
      } else if (msg.type === "stdout") {
        if (!running || truncated) return;
        printedText += msg.text;
        if (printedText.length > MAX_PRINT_CHARS) {
          printedText = printedText.slice(0, MAX_PRINT_CHARS);
          truncated = true;
        }
        scheduleRender();
      } else if (msg.type === "done") {
        if (!running) return;
        setIdle();
        render(false, msg.error, null);
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
      const wasRunning = running;
      setIdle();
      if (wasRunning) render(false, "Erreur inattendue du moteur Python.", null);
      startWorker();
    };
  }

  function runCode() {
    if (!ready || running) return;
    const code = getCode();
    saveCode(code);

    running = true;
    printedText = "";
    truncated = false;
    runBtn.disabled = true;
    runBtn.textContent = "Exécution…";
    stopBtn.hidden = false;
    render(true, null, null);

    worker.postMessage({ type: "run", code: code });
  }

  // Bouton « Arrêter » : on supprime le worker (ce qui coupe net le programme, même une boucle
  // infinie) puis on en relance un neuf. Python est rechargé à chaque arrêt (quelques
  // secondes, le fichier étant alors déjà en cache) ; les variables de l'exécution
  // interrompue sont perdues, ce qui est sans importance puisque chaque exécution repart de zéro.
  function stopCode() {
    if (!running) return;
    const old = worker;
    worker = null; // les derniers messages éventuels de l'ancien worker seront ignorés
    old.terminate();
    running = false;
    stopBtn.hidden = true;
    render(false, null, "Exécution interrompue.");
    startWorker();
  }

  stopBtn.addEventListener("click", stopCode);

  clearBtn.addEventListener("click", function () {
    if (getCode().trim() !== "" && !window.confirm("Vider l'éditeur ? Le code actuel sera perdu.")) return;
    setCode("");
    saveCode("");
    if (!running) resetOutput();
  });

  // Même délai que pour « Vérifier » dans les exercices : laisse au clavier virtuel mobile le
  // temps de transmettre la dernière frappe à l'éditeur avant de lire le code.
  runBtn.addEventListener("click", function () {
    setTimeout(runCode, 150);
  });

  // Sauvegarde locale du brouillon quand on quitte la page ou qu'elle passe en arrière-plan.
  window.addEventListener("pagehide", function () { saveCode(getCode()); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") saveCode(getCode());
  });

  initCodeMirror(loadSavedCode());
  startWorker();
})();
