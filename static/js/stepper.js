(function () {
  "use strict";

  // Page du mode pas à pas (EN TEST, superusers uniquement : voir exercise_stepper.html).
  //
  // Principe : le code est exécuté UNE SEULE FOIS sous sys.settrace côté Python, qui enregistre
  // chaque étape avec l'état des variables (sous forme de texte). « Avancer » et « Reculer » ne
  // font ensuite que parcourir cet enregistrement : reculer est exact et gratuit, sans jamais
  // ré-exécuter le code.
  //
  // Les exercices sont des fonctions que les tests appellent : le serveur fournit un appel par
  // cas de test (step_calls, ex : "puissance(2, 3)") et cette page l'ajoute à la suite du code
  // avant de tracer. Un menu permet de changer de test.
  //
  // Étapes enregistrées :
  // - ENTRÉE dans une fonction : le « def » est surligné, ses paramètres apparaissent dans les
  //   variables et, si l'appel vient d'une autre ligne du code, seul cet appel y est surligné ;
  // - une ligne TERMINÉE : elle est surlignée en entier avec l'état qui la SUIT. Pour
  //   « b = carre(a) », on voit donc d'abord l'entrée dans carre et ses lignes, puis la ligne
  //   entière une fois carre terminée.
  // Les lignes du niveau global ne sont pas des étapes (elles ne contiennent que les « def » et
  // l'appel du test) ; elles le sont seulement quand il n'y a aucun test à appeler.
  //
  // Un commentaire accompagne les boucles for (valeurs prises par la variable), les boucles while
  // et les if (condition respectée ou non), l'appel d'une fonction et son retour.
  //
  // Limites connues (volontaires pour cette première version) :
  // - seul l'appel d'UN cas de test est tracé (pas la comparaison avec le corrigé) ;
  // - les variables globales ne sont pas affichées, seulement celles des fonctions ;
  // - ce que le code affiche avec print() n'est pas montré ;
  // - une récursion infinie n'affiche que l'étape d'erreur finale (aucune ligne n'aboutit) ;
  // - les fonctions lambda et les générateurs d'expression ne sont pas des étapes.

  const MAX_STEPS = 5000; // garde-fou contre les boucles infinies
  const LINE_CLASS = "stepper-current-line";
  const CALL_CLASS = "stepper-call-range";

  // Le code Python est dans une chaîne JS : pas de backtick, de "${" ni d'antislash dedans.
  const PY_TRACER = `
import sys, json, types, reprlib, ast

def __trace_student__(source, max_steps, trace_module):
    FILENAME = "<student>"
    MAX_FRAMES = 25
    MAX_EVENTS = 200000   # garde-fou sur TOUTES les lignes exécutées (même celles qui ne sont pas des étapes)
    CO_GENERATORS = 0x20 | 0x80 | 0x100 | 0x200   # générateur, coroutine, coroutine itérable, générateur asynchrone
    steps = []
    pending = {}       # id(cadre) -> (ligne en cours d'exécution dans ce cadre, ligne qui la précédait)
    last_line = {}     # id(cadre) -> dernière ligne atteinte dans ce cadre
    unwinding = set()  # cadres que traverse une exception (leur ligne en cours n'a pas abouti)
    loops = {}         # (id(cadre), ligne du for) -> boucle en cours
    all_loops = []
    pos_cache = {}
    events = 0
    truncated = False
    lines = source.split("\\n")

    rep = reprlib.Repr()
    rep.maxlist = rep.maxtuple = rep.maxset = rep.maxfrozenset = rep.maxdeque = rep.maxarray = 20
    rep.maxdict = 12
    rep.maxstring = rep.maxother = 80
    rep.maxlevel = 3

    try:
        code = compile(source, FILENAME, "exec")
        tree = ast.parse(source)
    except SyntaxError as e:
        return json.dumps({"steps": [], "truncated": False,
                           "error": "SyntaxError (ligne %s) : %s" % (e.lineno, e.msg)})

    # if / while / for dont le corps est sur d'autres lignes que le test : on y ajoute un commentaire
    ctrl = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.For)) and node.body:
            if node.body[0].lineno != node.lineno and node.lineno not in ctrl:
                ctrl[node.lineno] = node

    def target_names(target):
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for elt in target.elts:
                sub = target_names(elt)
                if sub is None:
                    return None
                names.extend(sub)
            return names
        return None

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
        # Les appels de fonction en cours, le plus récent en premier. Le niveau global
        # (<module>) et les lambda / générateurs d'expression ne sont pas affichés.
        stack = []
        while frame is not None and frame.f_code.co_filename == FILENAME:
            name = frame.f_code.co_name
            if not name.startswith("<"):
                if len(stack) >= MAX_FRAMES:
                    stack.append({"scope": "... appels plus anciens non affichés", "vars": None})
                    break
                stack.append({"scope": "État des variables dans " + name, "vars": snap_vars(frame.f_locals)})
            frame = frame.f_back
        return stack

    def char_col(line_no, byte_col):
        # Python donne des colonnes en octets UTF-8 ; CodeMirror compte des caractères.
        return len(lines[line_no - 1].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    def call_position(caller):
        # Position (ligne, colonnes) de l'expression d'appel en cours dans le cadre appelant.
        if caller is None or caller.f_code.co_filename != FILENAME:
            return None
        try:
            positions = pos_cache.get(caller.f_code)
            if positions is None:
                positions = pos_cache[caller.f_code] = list(caller.f_code.co_positions())
            line, end_line, col, end_col = positions[caller.f_lasti // 2]
            if line is None or end_line is None or col is None or end_col is None:
                return None
            return {"line": line, "col": char_col(line, col), "endLine": end_line, "endCol": char_col(end_line, end_col)}
        except Exception:
            return None

    class _Stop(BaseException):
        pass

    def entry_step(frame):
        nonlocal truncated
        if len(steps) >= max_steps:
            truncated = True
            raise _Stop()
        code = frame.f_code
        params = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]
        local = frame.f_locals
        args = ", ".join(rep.repr(local[p]) for p in params if p in local)
        step = {"line": code.co_firstlineno, "stack": snap_stack(frame),
                "note": "Appel de %s(%s)." % (code.co_name, args)}
        pos = call_position(frame.f_back)
        if pos is not None:
            step["call"] = pos
        steps.append(step)

    def annotate(step, node, frame, prev, next_line):
        # La condition est respectée si la ligne suivante de ce cadre est dans le corps.
        first, last = node.body[0].lineno, node.body[-1].end_lineno
        inside = next_line is not None and first <= next_line <= last
        if isinstance(node, ast.If):
            step["note"] = "La condition est respectée." if inside else "La condition n'est pas respectée."
        elif isinstance(node, ast.While):
            step["note"] = ("La condition est respectée." if inside
                            else "La condition n'est pas respectée : on sort de la boucle.")
        else:
            names = target_names(node.target)
            if names is None:
                return
            key = (id(frame), node.lineno)
            loop = loops.get(key)
            # nouvelle boucle si on arrive du dehors (la ligne précédente n'est pas dans le corps)
            if loop is None or prev is None or not (first <= prev <= last):
                loop = {"names": names, "vals": [], "steps": [], "exits": []}
                loops[key] = loop
                all_loops.append(loop)
            if inside:
                values = [rep.repr(frame.f_locals[n]) for n in names if n in frame.f_locals]
                loop["vals"].append(values[0] if len(values) == 1 else "(" + ", ".join(values) + ")")
                loop["steps"].append(step)
            else:
                loop["exits"].append(step)

    def finish(frame, extra=None, next_line=None):
        # La ligne en cours de ce cadre est terminée : on enregistre l'état qui la suit.
        entry = pending.pop(id(frame), None)
        if entry is None:
            return
        line, prev = entry
        step = {"line": line, "stack": snap_stack(frame)}
        if extra:
            step.update(extra)
        node = ctrl.get(line)
        if node is not None:
            annotate(step, node, frame, prev, next_line)
        steps.append(step)

    def tracer(frame, event, arg):
        nonlocal truncated, events
        code = frame.f_code
        if code.co_filename != FILENAME:
            return None
        name = code.co_name
        is_module = name == "<module>"
        if event == "call":
            if name.startswith("<") and not is_module:
                return None   # lambda, générateur d'expression... : ni étapes ni lignes
            if not is_module and not (code.co_flags & CO_GENERATORS):
                entry_step(frame)
            return tracer
        key = id(frame)
        if event == "line":
            events += 1
            if events > MAX_EVENTS:
                truncated = True
                raise _Stop()
            if frame.f_lineno < 1 or (is_module and not trace_module):
                return tracer
            unwinding.discard(key)
            finish(frame, None, frame.f_lineno)   # la ligne précédente de ce cadre vient de se terminer
            if len(steps) >= max_steps:
                truncated = True
                raise _Stop()
            pending[key] = (frame.f_lineno, last_line.get(key))
            last_line[key] = frame.f_lineno
        elif event == "exception":
            unwinding.add(key)
        elif event == "return":
            last_line.pop(key, None)
            if key in unwinding:
                # sortie par une exception : la ligne en cours n'a pas abouti, pas d'étape
                unwinding.discard(key)
                pending.pop(key, None)
            else:
                extra = None
                if not is_module and not (code.co_flags & CO_GENERATORS):
                    extra = {"renvoie": rep.repr(arg)}
                finish(frame, extra, None)
        return tracer

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

    def fmt_values(vals):
        items = vals if len(vals) <= 5 else vals[:3] + ["..."] + vals[-1:]
        return "[" + ", ".join(items) + "]"

    for loop in all_loops:
        names = ", ".join(loop["names"])
        verb = "prend" if len(loop["names"]) == 1 else "prennent"
        for st in loop["steps"]:
            st["note"] = "%s %s les valeurs %s." % (names, verb, fmt_values(loop["vals"]))
        for st in loop["exits"]:
            st["note"] = ("La boucle est terminée." if loop["vals"]
                          else "Il n'y a rien à parcourir : la boucle ne s'exécute pas.")

    return json.dumps({"steps": steps, "truncated": truncated, "error": error})

__trace_student__(__STEP_SOURCE__, __STEP_MAX__, __STEP_MODULE__)
`;

  const prevBtn = document.getElementById("stepper-prev");
  const nextBtn = document.getElementById("stepper-next");
  const posEl = document.getElementById("stepper-pos");
  const msgEl = document.getElementById("stepper-msg");
  const varsBox = document.getElementById("stepper-vars");
  const caseRow = document.getElementById("stepper-case-row");
  const caseSel = document.getElementById("stepper-case");
  const codeArea = document.getElementById("stepper-code");
  if (!prevBtn || !nextBtn || !msgEl || !codeArea) return;

  let cm = null;
  let pyodide = null;
  let calls = [];
  let steps = [];
  let truncated = false;
  let index = 0;
  let currentLine = null; // ligne CodeMirror (base 0) actuellement surlignée en entier
  let callMark = null; // surlignage de l'expression d'appel (CodeMirror TextMarker)
  let callLine = null; // ligne (base 1) de l'appel du test ajouté après le code ; null sans appel

  // Code à tracer : celui que la page de l'exercice vient de transmettre (lu une seule fois),
  // sinon le dernier code enregistré, fourni par le serveur.
  function initialCode() {
    try {
      const key = "codexo-stepper-code-" + EXERCISE_ID;
      const sent = localStorage.getItem(key);
      if (sent !== null) {
        localStorage.removeItem(key);
        return sent;
      }
    } catch (e) {
      /* localStorage indisponible : on retombe sur le code du serveur */
    }
    return INITIAL_CODE;
  }

  function clearHighlight() {
    if (cm && currentLine !== null) cm.removeLineClass(currentLine, "background", LINE_CLASS);
    currentLine = null;
    if (callMark) callMark.clear();
    callMark = null;
  }

  function showMessage(text, isError) {
    msgEl.textContent = text || "";
    msgEl.classList.toggle("error", !!isError);
  }

  // Compare l'état avant/après : pour chaque cadre (même fonction, même profondeur),
  // les variables créées ou modifiées. Renvoie { cadres: [{nom: "nouvelle"|"modifiee"}], phrases: [...] }.
  function shorten(text) {
    return text.length > 40 ? text.slice(0, 37) + "..." : text;
  }
  function diffStacks(prevStack, stack) {
    const out = { cadres: [], phrases: [] };
    if (!prevStack || !stack) return out;
    const before = prevStack.slice().reverse();
    const after = stack.slice().reverse();
    after.forEach(function (scope, i) {
      const marks = {};
      out.cadres.push(marks);
      const old = before[i];
      if (!old || old.scope !== scope.scope || !old.vars || !scope.vars) return;
      const oldVars = {};
      old.vars.forEach(function (pair) { oldVars[pair[0]] = pair[1]; });
      scope.vars.forEach(function (pair) {
        const name = pair[0];
        if (!(name in oldVars)) {
          marks[name] = "nouvelle";
          out.phrases.push(name + " est créée et vaut " + shorten(pair[1]) + ".");
        } else if (oldVars[name] !== pair[1]) {
          marks[name] = "modifiee";
          out.phrases.push(name + " passe de " + shorten(oldVars[name]) + " à " + shorten(pair[1]) + ".");
        }
      });
    });
    return out;
  }

  const TITLE_PREFIX = "État des variables dans ";

  function renderVars(stack, marks) {
    varsBox.textContent = "";
    if (!stack || stack.length === 0) return; // niveau global uniquement : rien à montrer
    // L'appelant en haut, la fonction appelée en dessous (la plus récente = la dernière).
    const ordered = stack.slice().reverse();
    ordered.forEach(function (scope, i) {
      const section = document.createElement("div");
      section.className = "stepper-scope" + (i === ordered.length - 1 ? " current" : "");
      const title = document.createElement("div");
      title.className = "stepper-scope-title";
      // « État des variables dans » une seule fois (sur le premier cadre), ensuite le nom seul.
      title.textContent = i === 0 || scope.scope.indexOf(TITLE_PREFIX) !== 0
        ? scope.scope
        : scope.scope.slice(TITLE_PREFIX.length);
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
            const mark = marks && marks[i] && marks[i][pair[0]];
            if (mark) {
              tr.className = "stepper-changed";
              const tdTag = document.createElement("td");
              tdTag.className = "stepper-tag";
              tdTag.textContent = mark === "nouvelle" ? "Créée" : "Modifiée";
              tr.appendChild(tdTag);
            }
            table.appendChild(tr);
          });
          section.appendChild(table);
        }
      }
      varsBox.appendChild(section);
    });
  }

  function render() {
    clearHighlight();

    const step = steps[index];
    const isLast = index === steps.length - 1;

    // Une erreur sur la ligne d'appel du test (ex : fonction mal nommée) n'a pas de ligne dans le code.
    const showLine = step.line >= 1 && step.line !== callLine;
    const showCall = !!step.call && step.call.line !== callLine;
    if (cm) {
      if (showLine) {
        currentLine = step.line - 1;
        cm.addLineClass(currentLine, "background", LINE_CLASS);
      }
      if (showCall) {
        callMark = cm.markText(
          { line: step.call.line - 1, ch: step.call.col },
          { line: step.call.endLine - 1, ch: step.call.endCol },
          { className: CALL_CLASS }
        );
      }
      if (showLine || showCall) {
        const where = [];
        if (showLine) where.push(step.line - 1);
        if (showCall) where.push(step.call.line - 1);
        cm.scrollIntoView(
          { from: { line: Math.min.apply(null, where), ch: 0 }, to: { line: Math.max.apply(null, where), ch: 0 } },
          60
        );
      }
    }

    const changed = diffStacks(index > 0 ? steps[index - 1].stack : null, step.stack);

    posEl.textContent = "Étape " + (index + 1) + " / " + steps.length;
    prevBtn.disabled = index === 0;
    nextBtn.disabled = isLast;

    if (step.error) {
      showMessage("Erreur : " + step.error, true);
    } else {
      const parts = [];
      if (step.note) parts.push(step.note);
      parts.push.apply(parts, changed.phrases);
      if (step.renvoie !== undefined) parts.push("Renvoie " + step.renvoie + ".");
      if (isLast) {
        parts.push(
          truncated
            ? "Trace interrompue après " + MAX_STEPS + " étapes (boucle infinie ou programme très long ?)."
            : "Fin du programme."
        );
      }
      showMessage(parts.join("\n"), isLast && truncated);
    }
    renderVars(step.stack, changed.cadres);
  }

  // Remplit le menu avec un appel par cas de test (le premier est choisi d'office).
  // Masqué s'il n'y a aucun cas de test : le code est alors tracé seul.
  function fillCases() {
    caseSel.textContent = "";
    calls.forEach(function (call, i) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = call;
      caseSel.appendChild(opt);
    });
    if (calls.length) caseSel.value = "0";
    caseRow.hidden = calls.length === 0;
  }

  // Trace le code suivi de l'appel choisi dans le menu, puis affiche l'étape 1.
  async function trace() {
    const code = cm.getValue();
    const callText = caseSel.value !== "" ? calls[Number(caseSel.value)] || "" : "";
    let source = code;
    callLine = null;
    if (callText) {
      // L'appel est ajouté APRÈS le code, dans le même module. Sa ligne = nombre de lignes du code + 1.
      source = code + "\n__retour_test__ = " + callText + "\n";
      callLine = code.split("\n").length + 1;
    }

    caseSel.disabled = true;
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    let result;
    try {
      pyodide.globals.set("__STEP_SOURCE__", source);
      pyodide.globals.set("__STEP_MAX__", MAX_STEPS);
      pyodide.globals.set("__STEP_MODULE__", !callText); // sans test à appeler, les lignes globales deviennent des étapes
      result = JSON.parse(await pyodide.runPythonAsync(PY_TRACER));
    } catch (e) {
      result = { steps: [], truncated: false, error: "Erreur inattendue : " + e.message };
    }
    caseSel.disabled = false;

    clearHighlight();
    steps = result.steps;
    truncated = !!result.truncated;
    index = 0;
    varsBox.textContent = "";

    if (steps.length === 0) {
      // Rien à parcourir (erreur de syntaxe, code vide...) : on l'indique.
      posEl.textContent = "";
      showMessage(result.error || "Aucune ligne à exécuter.", true);
      return;
    }
    render();
  }

  async function init() {
    cm = CodeMirror.fromTextArea(codeArea, {
      mode: "python",
      lineNumbers: true,
      indentUnit: 4,
      readOnly: true,
      lineWrapping: true,
      viewportMargin: Infinity,
    });
    cm.setValue(initialCode());

    try {
      const res = await fetch(TESTS_URL);
      const data = await res.json();
      calls = data.step_calls || [];
      pyodide = await loadPyodide();
      // Même règle que la page de l'exercice : numpy n'est chargé que pour les exercices qui l'utilisent.
      if ((data.test_code || "").includes("numpy")) await pyodide.loadPackage("numpy");
    } catch (e) {
      showMessage("Erreur de chargement de Python.", true);
      return;
    }
    fillCases();
    await trace();
  }

  caseSel.addEventListener("change", trace); // autre test choisi : on retrace depuis le début
  nextBtn.addEventListener("click", function () {
    if (index < steps.length - 1) { index++; render(); }
  });
  prevBtn.addEventListener("click", function () {
    if (index > 0) { index--; render(); }
  });
  init();
})();
