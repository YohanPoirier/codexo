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
  // Limites connues (volontaires pour cette première version) :
  // - seul le code de l'éditeur est exécuté, pas les tests : une fonction n'est visible « en
  //   action » que si le code contient un appel (ex : print(ma_fonction(3)) en bas) ;
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
        steps.append({"line": None, "end": True,
                      "stack": [{"scope": "Variables globales", "vars": snap_vars(ns)}]})

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

  let steps = [];
  let truncated = false;
  let index = 0;
  let currentLine = null; // numéro de ligne CodeMirror (base 0) actuellement surlignée

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
    if (step.line >= 1 && cm) {
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
      showMessage("Fin du programme.", false);
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

  async function start() {
    const c = ctx();
    if (!c) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Analyse…";

    let result;
    try {
      const pyodide = c.getPyodide();
      pyodide.globals.set("__STEP_SOURCE__", c.getCode());
      pyodide.globals.set("__STEP_MAX__", MAX_STEPS);
      result = JSON.parse(await pyodide.runPythonAsync(PY_TRACER));
    } catch (e) {
      result = { steps: [], truncated: false, error: "Erreur inattendue : " + e.message };
    }
    btn.textContent = label;

    steps = result.steps;
    truncated = !!result.truncated;
    index = 0;
    panel.hidden = false;
    varsBox.textContent = "";

    if (steps.length === 0) {
      // Rien à parcourir (erreur de syntaxe, code vide...) : on l'indique, l'éditeur reste libre.
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
  nextBtn.addEventListener("click", function () {
    if (index < steps.length - 1) { index++; render(); }
  });
  prevBtn.addEventListener("click", function () {
    if (index > 0) { index--; render(); }
  });
  exitBtn.addEventListener("click", exit);
})();
