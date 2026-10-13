(function () {
  "use strict";

  // Mode pas à pas (EN TEST, réservé aux admins : voir exercise_detail.html).
  //
  // Principe : au clic sur « Pas à pas », le code de l'éditeur est exécuté UNE SEULE FOIS sous
  // sys.settrace côté Python, qui enregistre pour chaque ligne sur le point d'être exécutée
  // l'état des variables (sous forme de texte). « Avancer » et « Reculer » ne font ensuite que
  // parcourir cet enregistrement : reculer est donc exact et gratuit, sans jamais ré-exécuter
  // le code.
  //
  // Les exercices sont des fonctions que les tests appellent : le serveur fournit donc un appel
  // par cas de test (step_calls, ex : "puissance(2, 3)") et le mode pas à pas ajoute l'appel
  // choisi à la suite du code de l'éditeur avant de tracer. Un sélecteur permet de changer de
  // test ; « Code seul » trace le code sans aucun appel.
  //
  // Limites connues (volontaires pour cette première version) :
  // - seul l'appel d'UN cas de test est tracé (pas la comparaison avec le corrigé) ;
  // - ce que le code affiche avec print() n'est pas montré ;
  // - exercices Python uniquement (pas SQL).

  const MAX_STEPS = 5000; // garde-fou contre les boucles infinies (une étape = une ligne exécutée)
  const LINE_CLASS = "stepper-current-line";

  // Le code Python est dans une chaîne JS : pas de backtick, de "${" ni d'antislash dedans.
  const PY_TRACER = `
import sys, json, types, reprlib

def __trace_student__(source, max_steps):
    FILENAME = "<student>"
    MAX_FRAMES = 25
    steps = []
    truncated = False

    rep = reprlib.Repr()
    rep.maxlist = rep.maxtuple = rep.maxset = rep.maxfrozenset = rep.maxdeque = rep.maxarray = 20
    rep.maxdict = 12
    rep.maxstring = rep.maxother = 80
    rep.maxlevel = 3

    def visible(name, value):
        if name.startswith("__"):
            return False
        return not isinstance(value, (types.FunctionType, types.BuiltinFunctionType, types.ModuleType, type))

    def snap_vars(mapping):
        out = []
        for name, value in list(mapping.items()):
            if visible(name, value):
                out.append([name, rep.repr(value)])
        return out

    def snap_stack(frame):
        stack = []
        while frame is not None and frame.f_code.co_filename == FILENAME:
            if len(stack) >= MAX_FRAMES:
                stack.append({"scope": "... appels plus anciens non affichés", "vars": None})
                break
            name = frame.f_code.co_name
            label = "Variables globales" if name == "<module>" else "Dans " + name + "()"
            stack.append({"scope": label, "vars": snap_vars(frame.f_locals)})
            frame = frame.f_back
        return stack

    class _Stop(BaseException):
        pass

    def tracer(frame, event, arg):
        nonlocal truncated
        if frame.f_code.co_filename != FILENAME:
            return None
        if event == "line" and frame.f_lineno >= 1:
            if len(steps) >= max_steps:
                truncated = True
                raise _Stop()
            steps.append({"line": frame.f_lineno, "stack": snap_stack(frame)})
        return tracer

    try:
        code = compile(source, FILENAME, "exec")
    except SyntaxError as e:
        return json.dumps({"steps": [], "truncated": False,
                           "error": "SyntaxError (ligne %s) : %s" % (e.lineno, e.msg)})

    ns = {"__name__": "__main__"}
    error = None
    sys.settrace(tracer)
    try:
        exec(code, ns)
    except _Stop:
        pass
    except BaseException as e:
        error = "%s : %s" % (type(e).__name__, e)
        tb = e.__traceback__
        last = None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == FILENAME:
                last = tb
            tb = tb.tb_next
        if last is not None:
            steps.append({"line": last.tb_lineno, "stack": snap_stack(last.tb_frame), "error": error})
        else:
            steps.append({"line": None, "stack": [], "error": error})
    finally:
        sys.settrace(None)

    if error is None and not truncated:
        end = {"line": None, "end": True,
               "stack": [{"scope": "Variables globales", "vars": snap_vars(ns)}]}
        if "__retour_test__" in ns:
            end["retour"] = rep.repr(ns["__retour_test__"])
        steps.append(end)

    return json.dumps({"steps": steps, "truncated": truncated, "error": error})

__trace_student__(__STEP_SOURCE__, __STEP_MAX__)
`;

  const btn = document.getElementById("stepper-btn");
  const panel = document.getElementById("stepper-panel");
  if (!btn || !panel) return;

  const prevBtn = document.getElementById("stepper-prev");
  const nextBtn = document.getElementById("stepper-next");
  const exitBtn = document.getElementById("stepper-exit");
  const posEl = document.getElementById("stepper-pos");
  const msgEl = document.getElementById("stepper-msg");
  const varsBox = document.getElementById("stepper-vars");
  const caseRow = document.getElementById("stepper-case-row");
  const caseSel = document.getElementById("stepper-case");

  let steps = [];
  let truncated = false;
  let index = 0;
  let currentLine = null; // numéro de ligne CodeMirror (base 0) actuellement surlignée
  let callLine = null; // numéro (base 1) de la ligne d'appel du test, ajoutée après le code ; null si « Code seul »
  let callText = ""; // l'appel tracé, ex : "puissance(2, 3)"

  function ctx() {
    return window.codexoCtx || null;
  }

  // exercise.js publie window.codexoCtx et l'événement "codexo:ready" une fois Python chargé.
  if (ctx()) btn.disabled = false;
  else document.addEventListener("codexo:ready", function () { btn.disabled = false; });

  function clearHighlight() {
    const c = ctx();
    const cm = c && c.getCM();
    if (cm && currentLine !== null) cm.removeLineClass(currentLine, "background", LINE_CLASS);
    currentLine = null;
  }

  function showMessage(text, isError) {
    msgEl.hidden = !text;
    msgEl.textContent = text || "";
    msgEl.classList.toggle("error", !!isError);
  }

  function renderVars(stack) {
    varsBox.textContent = "";
    if (!stack || stack.length === 0) {
      const none = document.createElement("div");
      none.className = "stepper-empty";
      none.textContent = "Aucune variable.";
      varsBox.appendChild(none);
      return;
    }
    stack.forEach(function (scope, i) {
      const section = document.createElement("div");
      section.className = "stepper-scope" + (i === 0 ? " current" : "");
      const title = document.createElement("div");
      title.className = "stepper-scope-title";
      title.textContent = scope.scope;
      section.appendChild(title);

      if (scope.vars !== null) {
        if (scope.vars.length === 0) {
          const empty = document.createElement("div");
          empty.className = "stepper-empty";
          empty.textContent = "(aucune variable)";
          section.appendChild(empty);
        } else {
          const table = document.createElement("table");
          table.className = "stepper-table";
          scope.vars.forEach(function (pair) {
            const tr = document.createElement("tr");
            const tdName = document.createElement("td");
            const tdValue = document.createElement("td");
            tdName.textContent = pair[0];
            tdValue.textContent = pair[1]; // textContent : jamais d'HTML issu du code testé
            tr.appendChild(tdName);
            tr.appendChild(tdValue);
            table.appendChild(tr);
          });
          section.appendChild(table);
        }
      }
      varsBox.appendChild(section);
    });
  }

  function render() {
    const c = ctx();
    const cm = c && c.getCM();
    clearHighlight();

    const step = steps[index];
    // La ligne d'appel du test n'existe pas dans l'éditeur : rien à surligner, on l'indique en message.
    const onCall = callLine !== null && step.line === callLine;
    if (step.line >= 1 && !onCall && cm) {
      currentLine = step.line - 1;
      cm.addLineClass(currentLine, "background", LINE_CLASS);
      cm.scrollIntoView({ line: currentLine, ch: 0 }, 80);
    }

    posEl.textContent = "Étape " + (index + 1) + " / " + steps.length;
    prevBtn.disabled = index === 0;
    nextBtn.disabled = index === steps.length - 1;

    if (step.error) {
      showMessage("Erreur : " + step.error, true);
    } else if (step.end) {
      showMessage(
        "Fin du programme." +
          (step.retour !== undefined ? " " + callText + " a renvoyé " + step.retour + "." : ""),
        false
      );
    } else if (onCall) {
      showMessage("Appel du test : " + callText, false);
    } else if (truncated && index === steps.length - 1) {
      showMessage(
        "Trace interrompue après " + MAX_STEPS + " étapes (boucle infinie ou programme très long ?).",
        true
      );
    } else {
      showMessage("", false);
    }
    renderVars(step.stack);
  }

  // Remplit le sélecteur avec un appel par cas de test (le premier est choisi d'office) plus
  // « Code seul ». Masqué s'il n'y a aucun cas de test.
  function fillCases(calls) {
    caseSel.textContent = "";
    calls.forEach(function (call, i) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = call;
      caseSel.appendChild(opt);
    });
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "Code seul (sans appel)";
    caseSel.appendChild(none);
    caseSel.value = calls.length ? "0" : "";
    caseRow.hidden = calls.length === 0;
  }

  // Trace le code de l'éditeur suivi de l'appel choisi dans le sélecteur, puis affiche l'étape 1.
  async function trace() {
    const c = ctx();
    const calls = c.getStepCalls ? c.getStepCalls() : [];
    const code = c.getCode();

    callText = caseSel.value !== "" ? calls[Number(caseSel.value)] || "" : "";
    let source = code;
    callLine = null;
    if (callText) {
      // L'appel est ajouté APRÈS le code, dans le même module : la pile d'appels garde ainsi le
      // niveau « Variables globales ». Sa ligne = nombre de lignes du code + 1.
      source = code + "\n__retour_test__ = " + callText + "\n";
      callLine = code.split("\n").length + 1;
    }

    caseSel.disabled = true;
    let result;
    try {
      const pyodide = c.getPyodide();
      pyodide.globals.set("__STEP_SOURCE__", source);
      pyodide.globals.set("__STEP_MAX__", MAX_STEPS);
      result = JSON.parse(await pyodide.runPythonAsync(PY_TRACER));
    } catch (e) {
      result = { steps: [], truncated: false, error: "Erreur inattendue : " + e.message };
    }
    caseSel.disabled = false;

    clearHighlight();
    steps = result.steps;
    truncated = !!result.truncated;
    index = 0;
    panel.hidden = false;
    varsBox.textContent = "";

    if (steps.length === 0) {
      // Rien à parcourir (erreur de syntaxe...) : on l'indique, l'éditeur reste libre.
      posEl.textContent = "";
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      showMessage(result.error || "Aucune ligne à exécuter.", true);
      return;
    }

    // Éditeur verrouillé pendant le pas à pas : le code affiché doit rester celui qui a été tracé.
    const cm = c.getCM();
    if (cm) cm.setOption("readOnly", "nocursor");
    render();
  }

  async function start() {
    const c = ctx();
    if (!c) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Analyse…";

    fillCases(c.getStepCalls ? c.getStepCalls() : []);
    await trace();

    btn.textContent = label;
    // Pendant un pas à pas le bouton reste grisé (on en sort avec « Quitter ») ; s'il n'y avait
    // rien à parcourir, on le laisse actif pour pouvoir corriger le code et réessayer.
    btn.disabled = steps.length > 0;
  }

  function exit() {
    clearHighlight();
    const c = ctx();
    const cm = c && c.getCM();
    if (cm) cm.setOption("readOnly", false);
    steps = [];
    panel.hidden = true;
    btn.disabled = false;
  }

  btn.addEventListener("click", start);
  caseSel.addEventListener("change", trace); // autre test choisi : on retrace depuis le début
  nextBtn.addEventListener("click", function () {
    if (index < steps.length - 1) { index++; render(); }
  });
  prevBtn.addEventListener("click", function () {
    if (index > 0) { index--; render(); }
  });
  exitBtn.addEventListener("click", exit);
})();
