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
import sys, json, types, reprlib

def __trace_student__(source, max_steps, trace_module):
    FILENAME = "<student>"
    MAX_FRAMES = 25
    MAX_EVENTS = 200000   # garde-fou sur TOUTES les lignes exécutées (même celles qui ne sont pas des étapes)
    CO_GENERATORS = 0x20 | 0x80 | 0x100 | 0x200   # générateur, coroutine, coroutine itérable, générateur asynchrone
    steps = []
    pending = {}       # id(cadre) -> ligne en cours d'exécution dans ce cadre
    unwinding = set()  # cadres que traverse une exception (leur ligne en cours n'a pas abouti)
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
    except SyntaxError as e:
        return json.dumps({"steps": [], "truncated": False,
                           "error": "SyntaxError (ligne %s) : %s" % (e.lineno, e.msg)})

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

    class _Capture:
        # Sortie des print() : on garde tout (jusqu'à MAX_OUT caractères) et chaque étape
        # note la longueur déjà écrite, pour n'afficher que ce qui a été imprimé jusque-là.
        MAX_OUT = 100000
        def __init__(self):
            self.parts = []
            self.size = 0
        def write(self, text):
            text = str(text)
            room = self.MAX_OUT - self.size
            if room > 0:
                text = text[:room]
                self.parts.append(text)
                self.size += len(text)
            return len(text)
        def flush(self):
            pass

    out = _Capture()

    def entry_step(frame):
        nonlocal truncated
        if len(steps) >= max_steps:
            truncated = True
            raise _Stop()
        code = frame.f_code
        step = {"line": code.co_firstlineno, "stack": snap_stack(frame), "out": out.size}
        pos = call_position(frame.f_back)
        if pos is not None:
            step["call"] = pos
        steps.append(step)

    def finish(frame, extra=None):
        # La ligne en cours de ce cadre est terminée : on enregistre l'état qui la suit.
        line = pending.pop(id(frame), None)
        if line is None:
            return
        step = {"line": line, "stack": snap_stack(frame), "out": out.size}
        if extra:
            step.update(extra)
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
            finish(frame)   # la ligne précédente de ce cadre vient de se terminer
            if len(steps) >= max_steps:
                truncated = True
                raise _Stop()
            pending[key] = frame.f_lineno
        elif event == "exception":
            unwinding.add(key)
        elif event == "return":
            if key in unwinding:
                # sortie par une exception : la ligne en cours n'a pas abouti, pas d'étape
                unwinding.discard(key)
                pending.pop(key, None)
            else:
                extra = None
                if not is_module and not (code.co_flags & CO_GENERATORS):
                    extra = {"renvoie": rep.repr(arg)}
                finish(frame, extra)
        return tracer

    ns = {"__name__": "__main__"}
    error = None
    old_stdout = sys.stdout
    sys.stdout = out
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
            steps.append({"line": last.tb_lineno, "stack": snap_stack(last.tb_frame), "error": error, "out": out.size})
        else:
            steps.append({"line": None, "stack": [], "error": error, "out": out.size})
    finally:
        sys.settrace(None)
        sys.stdout = old_stdout

    return json.dumps({"steps": steps, "truncated": truncated, "error": error, "output": "".join(out.parts)})

__trace_student__(__STEP_SOURCE__, __STEP_MAX__, __STEP_MODULE__)
`;

  const prevBtn = document.getElementById("stepper-prev");
  const nextBtn = document.getElementById("stepper-next");
  const posEl = document.getElementById("stepper-pos");
  const msgEl = document.getElementById("stepper-msg");
  const printEl = document.getElementById("stepper-print");
  const varsBox = document.getElementById("stepper-vars");
  const caseRow = document.getElementById("stepper-case-row");
  const caseSel = document.getElementById("stepper-case");
  const callEl = document.getElementById("stepper-call");
  const editorBox = document.getElementById("stepper-editor");
  const rerunBtn = document.getElementById("stepper-rerun");
  const codeArea = document.getElementById("stepper-code");
  if (!prevBtn || !nextBtn || !msgEl || !codeArea) return;

  let cm = null;
  let pyodide = null;
  let calls = [];
  let steps = [];
  let truncated = false;
  let dirty = false; // code modifié depuis le dernier tracé
  let output = []; // sortie des print(), en caractères (comme les longueurs comptées côté Python)
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
    if (callEl) callEl.classList.remove("active");
  }

  function showMessage(text, isError) {
    msgEl.textContent = text || "";
    msgEl.classList.toggle("error", !!isError);
  }

  // Compare l'état avant/après : pour chaque cadre (même fonction, même profondeur),
  // les variables créées ou modifiées. Un cadre qui vient d'apparaître (entrée dans une
  // fonction) a toutes ses variables — ses paramètres — marquées « créées ».
  // Renvoie une liste (de l'appelant vers l'appelé) de { nom: "nouvelle" | "modifiee" }.
  function diffStacks(prevStack, stack) {
    const out = [];
    if (!stack) return out;
    const before = (prevStack || []).slice().reverse();
    const after = stack.slice().reverse();
    after.forEach(function (scope, i) {
      const marks = {};
      out.push(marks);
      if (!scope.vars) return;
      const old = before[i];
      const fresh = !old || old.scope !== scope.scope || !old.vars;
      const oldVars = {};
      if (!fresh) old.vars.forEach(function (pair) { oldVars[pair[0]] = pair[1]; });
      scope.vars.forEach(function (pair) {
        const name = pair[0];
        if (fresh || !(name in oldVars)) marks[name] = "nouvelle";
        else if (oldVars[name] !== pair[1]) marks[name] = "modifiee";
      });
    });
    return out;
  }

  const TITLE_PREFIX = "État des variables dans ";

  function renderVars(stack, marks) {
    varsBox.textContent = "";
    if (!stack || stack.length === 0) return; // niveau global uniquement : rien à montrer
    // L'appelant en haut, la fonction appelée en dessous (la plus récente = la dernière).
    const heading = document.createElement("h2");
    heading.className = "stepper-vars-title visually-hidden"; // pour les lecteurs d'écran seulement
    heading.textContent = "État des variables";
    varsBox.appendChild(heading);
    const ordered = stack.slice().reverse();
    ordered.forEach(function (scope, i) {
      if (i > 0) {
        // Petit triangle entre deux cadres : la fonction du dessus appelle celle du dessous.
        const arrow = document.createElement("div");
        arrow.className = "stepper-call-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "▼";
        varsBox.appendChild(arrow);
      }
      const section = document.createElement("div");
      section.className = "stepper-scope" + (i === ordered.length - 1 ? " current" : "");
      const title = document.createElement("div");
      title.className = "stepper-scope-title";
      // Le grand titre « État des variables » est au-dessus ; chaque cadre porte le nom de sa fonction.
      title.textContent = scope.scope.indexOf(TITLE_PREFIX) === 0
        ? scope.scope.slice(TITLE_PREFIX.length)
        : scope.scope;
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
    // Entrée dans la fonction testée (ou erreur sur l'appel lui-même) : on surligne l'appel
    // dans la ligne de console sous l'éditeur.
    if (callEl && callLine !== null) {
      const onCallLine = (!!step.call && step.call.line === callLine) || step.line === callLine;
      callEl.classList.toggle("active", onCallLine);
    }
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

    if (printEl) printEl.textContent = output.slice(0, step.out || 0).join("");

    if (step.error) {
      showMessage("Erreur : " + step.error, true);
    } else {
      const parts = [];
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
    renderVars(step.stack, changed);
  }

  // Remplit le menu avec un appel par cas de test (le premier est choisi d'office).
  // Masqué s'il n'y a aucun cas de test : le code est alors tracé seul.
  function fillCases() {
    caseSel.textContent = "";
    calls.forEach(function (call, i) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = call + "  # test " + (i + 1);
      caseSel.appendChild(opt);
    });
    if (calls.length) caseSel.value = "0";
    caseRow.hidden = calls.length === 0;
    if (editorBox) editorBox.classList.toggle("with-call", calls.length > 0);
    renderCallLine();
  }

  // Affiche « >>> appel  # test n » avec une coloration simple (comme dans l'éditeur).
  function addSpan(parent, cls, text) {
    const span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text;
    parent.appendChild(span);
    return span;
  }
  function renderCallLine() {
    if (!callEl) return;
    callEl.textContent = "";
    callEl.classList.remove("active");
    const i = Number(caseSel.value);
    const call = calls[i];
    if (call === undefined) return;
    addSpan(callEl, "p", ">>> ");
    const expr = addSpan(callEl, "stepper-call-expr", "");
    const open = call.indexOf("(");
    addSpan(expr, "f", open > 0 ? call.slice(0, open) : call);
    const rest = open > 0 ? call.slice(open) : "";
    const token = /('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|\b(True|False|None)\b/g;
    let last = 0, m;
    while ((m = token.exec(rest)) !== null) {
      if (m.index > last) addSpan(expr, "", rest.slice(last, m.index));
      addSpan(expr, m[1] ? "s" : m[2] ? "n" : "k", m[0]);
      last = token.lastIndex;
    }
    if (last < rest.length) addSpan(expr, "", rest.slice(last));
    addSpan(callEl, "c", "  # test " + (i + 1));
  }

  // Trace le code suivi de l'appel choisi dans le menu, puis affiche l'étape 1.
  async function trace() {
    dirty = false;
    rerunBtn.hidden = true;
    prevBtn.hidden = false;
    nextBtn.hidden = false;
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
    output = Array.from(result.output || "");
    index = 0;
    varsBox.textContent = "";
    if (printEl) printEl.textContent = "";

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
      extraKeys: {
        // Tabulation = 4 espaces (ou indentation de la sélection), comme sur la page de l'exercice
        Tab: function (editor) {
          if (editor.somethingSelected()) editor.indentSelection("add");
          else editor.replaceSelection("    ");
        },
        "Shift-Tab": "indentLess",
      },
      lineWrapping: true,
      viewportMargin: Infinity,
    });
    cm.setValue(initialCode());
    cm.on("beforeChange", onBeforeChange);
    cm.on("change", onChange);

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

  // Code modifié : la trace enregistrée ne correspond plus. On efface le surlignage AVANT la
  // modification (les numéros de ligne peuvent bouger), et « Relancer » remplace les boutons.
  function onBeforeChange(editor, change) {
    if (change.origin === "setValue" || dirty) return;
    dirty = true;
    clearHighlight();
    steps = [];
    varsBox.textContent = "";
    posEl.textContent = "";
    if (printEl) printEl.textContent = "";
    prevBtn.hidden = true;
    nextBtn.hidden = true;
    rerunBtn.hidden = false;
    showMessage("Code modifié : clique sur « Relancer » pour le parcourir à nouveau.", false);
  }
  // Le code modifié est renvoyé à la page de l'exercice, qui le reprendra à son prochain chargement.
  function onChange(editor, change) {
    if (change.origin === "setValue") return;
    try {
      localStorage.setItem("codexo-stepper-back-" + EXERCISE_ID, editor.getValue());
    } catch (e) {
      /* stockage indisponible : la modification reste dans cette page */
    }
  }

  caseSel.addEventListener("change", function () { renderCallLine(); trace(); }); // autre test : on retrace depuis le début
  rerunBtn.addEventListener("click", trace);
  nextBtn.addEventListener("click", function () {
    if (index < steps.length - 1) { index++; render(); }
  });
  prevBtn.addEventListener("click", function () {
    if (index > 0) { index--; render(); }
  });
  init();
})();
