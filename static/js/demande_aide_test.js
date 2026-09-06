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

  let pyodide = null;
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

    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";
    try {
      pyodide = await loadPyodide();
      if (testCode.includes("numpy")) {
        await pyodide.loadPackage("numpy");
      }
    } catch (e) {
      runBtn.textContent = "Erreur de chargement de Python";
      return;
    }
    runBtn.disabled = false;
    runBtn.textContent = "Tester ce code";
  }

  async function runCheck() {
    const code = getCode();
    runBtn.disabled = true;
    runBtn.textContent = "Vérification…";
    resultBox.classList.add("hidden");

    try {
      pyodide.globals.set("__TEST_CODE__", testCode);

      let runner;
      if (EXERCISE_KIND === "sql") {
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
        showRuntimeError("Erreur dans ce code :\n\n" + runtimeError);
      } else {
        const resultsProxy = pyodide.globals.get("__RESULTS__");
        const results = resultsProxy ? resultsProxy.toJs() : [];
        const items = results.map((item) => ({ ok: item[0], msg: item[1], printed: item[2] || "" }));
        if (items.length === 0) items.push({ ok: false, msg: "Aucun test défini pour cet exercice." });
        showResultLines(items);
      }
    } catch (e) {
      showRuntimeError("Erreur inattendue : " + e.message);
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
