(function () {
  const editor = document.getElementById("code-editor");
  const runBtn = document.getElementById("run-btn");
  const resultBox = document.getElementById("result-box");

  let pyodide = null;
  let testCode = "";

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

  const resetBtn = document.getElementById("reset-btn");
  let starterCode = "";

  async function init() {
    try {
      const res = await fetch(TESTS_URL);
      const data = await res.json();
      starterCode = data.starter_code || "";
      testCode = data.test_code || "";
    } catch (e) {
      runBtn.textContent = "Erreur : exercice non chargé";
      return;
    }

    // LAST_SUBMITTED_CODE est injecté par le template : le code de la dernière
    // tentative enregistrée en base pour cet exercice (ou null si aucune).
    editor.value = LAST_SUBMITTED_CODE !== null && LAST_SUBMITTED_CODE !== "" ? LAST_SUBMITTED_CODE : starterCode;

    runBtn.textContent = "Chargement de Python (peut prendre quelques secondes)…";
    try {
      pyodide = await loadPyodide();
    } catch (e) {
      runBtn.textContent = "Erreur de chargement de Python";
      return;
    }
    runBtn.disabled = false;
    runBtn.textContent = "Vérifier";
  }

  async function submitResult(code, success) {
    try {
      await fetch(SUBMIT_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ code, success }),
      });
    } catch (e) {
      /* silencieux : l'échec de sauvegarde ne doit pas bloquer le retour visuel */
    }
  }

  async function runCheck() {
    const code = editor.value;
    runBtn.disabled = true;
    runBtn.textContent = "Vérification…";
    resultBox.classList.add("hidden");

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
        await submitResult(code, false);
      } else {
        const resultsProxy = pyodide.globals.get("__RESULTS__");
        const results = resultsProxy ? resultsProxy.toJs() : [];
        const items = results.map((item) => ({ ok: item[0], msg: item[1], printed: item[2] || "" }));
        if (items.length === 0) items.push({ ok: false, msg: "Aucun test défini pour cet exercice." });
        const allOk = items.length > 0 && items.every((it) => it.ok);
        showResultLines(items);
        await submitResult(code, allOk);
      }
    } catch (e) {
      showRuntimeError("Erreur inattendue : " + e.message);
    }

    runBtn.disabled = false;
    runBtn.textContent = "Vérifier";
  }

  editor.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      const indent = "    "; // 4 espaces, convention Python

      if (start === end) {
        // Pas de sélection : insère juste l'indentation au curseur
        editor.value = editor.value.slice(0, start) + indent + editor.value.slice(end);
        editor.selectionStart = editor.selectionEnd = start + indent.length;
      } else {
        // Sélection multi-lignes : indente (ou désindente avec Shift+Tab) chaque ligne sélectionnée
        const before = editor.value.slice(0, start);
        const selected = editor.value.slice(start, end);
        const after = editor.value.slice(end);
        const lines = selected.split("\n");

        let newLines, addedFirstLine, removedFirstLine;
        if (e.shiftKey) {
          newLines = lines.map((line) => (line.startsWith(indent) ? line.slice(indent.length) : line.replace(/^\s{1,4}/, "")));
        } else {
          newLines = lines.map((line) => indent + line);
        }
        const newSelected = newLines.join("\n");
        editor.value = before + newSelected + after;
        editor.selectionStart = start;
        editor.selectionEnd = start + newSelected.length;
      }
    }
  });

  resetBtn.addEventListener("click", function () {
    if (editor.value.trim() === starterCode.trim()) return;
    const confirmed = window.confirm(
      "Revenir au code de départ ? Ton code actuel dans l'éditeur sera perdu (mais tes tentatives déjà validées restent enregistrées)."
    );
    if (confirmed) {
      editor.value = starterCode;
      resultBox.classList.add("hidden");
    }
  });

  runBtn.addEventListener("click", runCheck);
  init();
})();
