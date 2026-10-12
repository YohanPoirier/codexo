(function () {
  const editor = document.getElementById("sandbox-editor");
  const runBtn = document.getElementById("sandbox-run-btn");
  const clearBtn = document.getElementById("sandbox-clear-btn");
  const output = document.getElementById("sandbox-output");

  const STORAGE_KEY = "codexo-sandbox-code";
  const DEFAULT_CODE = "# Écrivez votre code ici\nprint(\"Bonjour !\")\n";

  let pyodide = null;
  let cm = null;

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

  // --- Fenêtre de résultat ---
  function block(kind, title, text) {
    return (
      '<div class="sandbox-block sandbox-' + kind + '">' +
      '<span class="sandbox-block-title">' + title + "</span>" +
      "<pre>" + escapeHtml(text) + "</pre>" +
      "</div>"
    );
  }

  function showOutput(printed, error) {
    let html = "";
    if (printed) html += block("print", "Affichage (print)", printed.replace(/\n$/, ""));
    if (error) html += block("error", "Erreur", error.replace(/\n$/, ""));
    if (!html) {
      html = '<p class="sandbox-placeholder">Le code s\'est exécuté sans rien afficher.</p>';
    }
    output.innerHTML = html;
  }

  function resetOutput() {
    output.innerHTML = '<p class="sandbox-placeholder">Le résultat de l\'exécution apparaîtra ici.</p>';
  }

  // Exécution dans un espace de noms frais à chaque clic (comme pour les exercices, voir
  // __EXEC_NS__ dans exercise.js) : une variable définie lors d'une exécution précédente ne
  // reste pas disponible par erreur. Seuls les print() (stdout) et les erreurs sont remontés.
  const RUNNER = `
import sys, io, traceback

__sb_out__ = io.StringIO()
__sb_error__ = None
__sb_ns__ = {"__name__": "__main__"}

_sb_old_stdout = sys.stdout
sys.stdout = __sb_out__
try:
    exec(compile(__SB_CODE__, "<code>", "exec"), __sb_ns__)
except SyntaxError:
    __sb_error__ = "".join(traceback.format_exception_only(*sys.exc_info()[:2]))
except BaseException:
    _sb_et, _sb_ev, _sb_tb = sys.exc_info()
    __sb_error__ = (
        "Traceback (most recent call last):\\n"
        + "".join(traceback.format_list(traceback.extract_tb(_sb_tb.tb_next)))
        + "".join(traceback.format_exception_only(_sb_et, _sb_ev))
    )
finally:
    sys.stdout = _sb_old_stdout
__sb_printed__ = __sb_out__.getvalue()
`;

  async function runCode() {
    if (!pyodide || runBtn.disabled) return;
    const code = getCode();
    saveCode(code);
    runBtn.disabled = true;
    runBtn.textContent = "Exécution…";

    try {
      if (/\bnumpy\b/.test(code)) {
        await pyodide.loadPackage("numpy");
      }
      pyodide.globals.set("__SB_CODE__", code);
      await pyodide.runPythonAsync(RUNNER);
      const printed = pyodide.globals.get("__sb_printed__");
      const error = pyodide.globals.get("__sb_error__");
      showOutput(printed, error);
    } catch (e) {
      showOutput("", "Erreur inattendue : " + e.message);
    }

    runBtn.disabled = false;
    runBtn.textContent = "Exécuter";
  }

  clearBtn.addEventListener("click", function () {
    if (getCode().trim() !== "" && !window.confirm("Vider l'éditeur ? Le code actuel sera perdu.")) return;
    setCode("");
    saveCode("");
    resetOutput();
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

  async function init() {
    initCodeMirror(loadSavedCode());
    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";
    try {
      pyodide = await loadPyodide();
    } catch (e) {
      runBtn.textContent = "Erreur de chargement de Python";
      return;
    }
    runBtn.disabled = false;
    runBtn.textContent = "Exécuter";
  }

  init();
})();
