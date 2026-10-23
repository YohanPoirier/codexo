(function () {
  "use strict";

  // Page du mode pas à pas (superusers, ou tout le monde si PAS_A_PAS_ELEVES : voir views.pas_a_pas_autorise).
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
    # Dernier « return » enregistré : (indice de son étape, id du cadre appelant, ligne de
    # l'appel). Si la ligne appelante se termine juste après, les deux étapes n'en font
    # qu'une (voir add_step).
    last_return = [None]
    unwinding = set()  # cadres que traverse une exception (leur ligne en cours n'a pas abouti)
    pos_cache = {}
    events = 0
    truncated = False
    lines = source.split("\\n")
    # Avec un test, le code de l'élève s'arrête avant la ligne d'appel ajoutée à la fin.
    code_end = len(source.rstrip("\\n").split("\\n")) - 1 if not trace_module else len(lines)

    rep = reprlib.Repr()
    rep.maxlist = rep.maxtuple = rep.maxset = rep.maxfrozenset = rep.maxdeque = rep.maxarray = 20
    rep.maxdict = 12
    rep.maxstring = rep.maxother = 80
    rep.maxlevel = 3

    try:
        code = compile(source, FILENAME, "exec")
    except SyntaxError as e:
        return json.dumps({"steps": [], "truncated": False,
                           "error": "%s: %s (ligne %s)" % (type(e).__name__, e.msg, e.lineno)})

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
        # Les appels de fonction en cours, le plus récent en premier, puis le programme
        # principal (niveau global) tout en bas. Les lambda / générateurs d'expression ne
        # sont pas affichés.
        stack = []
        while frame is not None and frame.f_code.co_filename == FILENAME:
            name = frame.f_code.co_name
            if name == "<module>":
                stack.append({"scope": "programme principal", "vars": snap_vars(frame.f_globals)})
            elif not name.startswith("<"):
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

    def add_step(step, caller_key):
        # Fusion « return + ligne qui récupère la valeur » : si l'étape précédente est le
        # return d'une fonction appelée depuis cette ligne, et que cette ligne se termine
        # juste après (rien entre les deux), une seule étape surligne les deux lignes, montre
        # l'appelant après réception de la valeur, et garde le cadre de la fonction appelée,
        # grisé (« done »). Renvoie True si l'étape a été fusionnée.
        lr = last_return[0]
        last_return[0] = None
        if lr is not None and lr[0] == len(steps) - 1 and lr[1] == caller_key and lr[2] == step["line"]:
            previous = steps[-1]
            ghost = dict(previous["stack"][0])
            ghost["done"] = True
            step["ret"] = previous["line"]
            if previous.get("fin"):
                step["fin"] = True   # fin de fonction sans return : le message reste affiché
            step["stack"] = [ghost] + step["stack"]
            steps[-1] = step
            return True
        steps.append(step)
        return False

    def finish(frame):
        # La ligne en cours de ce cadre est terminée : on enregistre l'état qui la suit.
        line = pending.pop(id(frame), None)
        if line is None:
            return None   # rien à enregistrer
        return add_step({"line": line, "stack": snap_stack(frame), "out": out.size}, id(frame))

    def is_return_line(line_no):
        # La ligne contient-elle une instruction return (aussi « if x: return y ») ?
        text = lines[line_no - 1].split("#")[0].replace(":", " ").replace(";", " ")
        return "return" in text.split()

    def end_step(frame, last_line):
        # Fonction terminée SANS return (oubli fréquent) : étape de plus sur la ligne vide qui
        # suit la fonction, pour montrer qu'on en sort (elle renvoie alors None). Seulement si
        # cette ligne existe dans le code de l'élève et qu'elle est vide.
        nonlocal truncated
        if last_line is None or is_return_line(last_line):
            return False
        numbers = [l for _, _, l in frame.f_code.co_lines() if l is not None]
        if not numbers:
            return False
        target = max(numbers) + 1
        if target > code_end or lines[target - 1].strip() != "":
            return False
        if len(steps) >= max_steps:
            truncated = True
            raise _Stop()
        steps.append({"line": target, "stack": snap_stack(frame), "out": out.size, "fin": True})
        return True

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
                last_line = pending.get(key)
                appended = finish(frame) is False   # nouvelle étape (ni fusionnée, ni absente)
                if (arg is None and not is_module and not (code.co_flags & CO_GENERATORS)
                        and end_step(frame, last_line)):
                    appended = True
                caller = frame.f_back
                if (appended and not is_module and not (code.co_flags & CO_GENERATORS)
                        and caller is not None and caller.f_code.co_filename == FILENAME):
                    # Le return vient d'être enregistré : à fusionner avec la ligne appelante
                    # si elle se termine juste après. Appelant = programme principal non tracé
                    # (test) : la ligne d'appel se termine avec l'étape finale « res ».
                    caller_key = "module" if caller.f_code.co_name == "<module>" and not trace_module else id(caller)
                    last_return[0] = (len(steps) - 1, caller_key, caller.f_lineno)
                    # Si la fusion n'a pas lieu (la ligne appelante n'est pas finie, ex :
                    # f(a) + f(b)), l'étape du return surligne aussi l'appel concerné.
                    pos = call_position(caller)
                    if pos is not None:
                        steps[-1]["call"] = pos
        return tracer

    ns = {"__name__": "__main__"}
    error = None
    old_stdout = sys.stdout
    sys.stdout = out
    sys.settrace(tracer)
    try:
        exec(code, ns)
        if not trace_module and not truncated:
            # Avec un test : les lignes du programme principal ne sont pas des étapes. On en
            # ajoute une, finale, pour montrer « res » reçu dans le programme principal.
            add_step({"line": len(source.rstrip("\\n").split("\\n")), "stack": [{"scope": "programme principal", "vars": snap_vars(ns)}],
                      "out": out.size}, "module")
    except _Stop:
        pass
    except BaseException as e:
        error = "%s: %s" % (type(e).__name__, e) if str(e) else type(e).__name__   # format de Python
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

  // Ordre des tests dans le menu, pour un exercice récursif (mesuré sur le corrigé) : un
  // exemple pas trop long, puis les cas de base (sans appel récursif), puis les autres tests
  // du moins au plus profond.
  // Renvoie, pour chaque appel, [profondeur de récursion maximale, nombre d'appels].
  const PY_MESURE = `
import sys, json

def __mesure_tests__(solution, calls, max_calls):
    ns = {"__name__": "__main__"}
    try:
        exec(solution, ns)
    except BaseException:
        return json.dumps(None)

    class _Stop(BaseException):
        pass

    out = []
    for call in calls:
        depth, best, count = {}, [0], [0]

        def prof(frame, event, arg):
            code = frame.f_code
            if code.co_filename != "<string>" or code.co_name.startswith("<"):
                return
            if event == "call":
                count[0] += 1
                if count[0] > max_calls:
                    raise _Stop()
                depth[code.co_name] = depth.get(code.co_name, 0) + 1
                best[0] = max(best[0], depth[code.co_name])
            elif event == "return":
                depth[code.co_name] = depth.get(code.co_name, 1) - 1

        sys.setprofile(prof)
        try:
            eval(call, dict(ns))
        except BaseException:
            pass
        finally:
            sys.setprofile(None)
        out.append([best[0], count[0]])
    return json.dumps(out)

__mesure_tests__(__MESURE_SOLUTION__, __MESURE_CALLS__, 20000)
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
  const callBtn = document.getElementById("stepper-call-btn");
  const caseList = document.getElementById("stepper-case-list");
  const editorBox = document.getElementById("stepper-editor");
  const rerunBtn = document.getElementById("stepper-rerun");
  const codeArea = document.getElementById("stepper-code");
  if (!prevBtn || !nextBtn || !msgEl || !codeArea) return;

  // « Étape » et « 3 / 12 » dans deux spans : sur téléphone, ils passent sur deux lignes
  // entre les boutons Reculer et Avancer (cf. stepper.css).
  function afficherPosition(numero, total) {
    const mot = document.createElement("span");
    mot.textContent = "Étape ";
    const valeur = document.createElement("span");
    valeur.textContent = numero + " / " + total;
    posEl.replaceChildren(mot, valeur);
    ajusterBoutons();
  }

  // Si « Reculer » / « Avancer » ne tiennent pas en entier (écran étroit), on ne garde
  // que les flèches. Mesuré pour de vrai plutôt que deviné d'après la largeur d'écran.
  const controles = prevBtn.parentElement;
  function ajusterBoutons() {
    controles.classList.remove("stepper-controls--compact");
    const deborde = [prevBtn, nextBtn].some(
      (b) => !b.hidden && b.offsetParent !== null && b.scrollWidth > b.clientWidth + 1
    );
    controles.classList.toggle("stepper-controls--compact", deborde);
  }
  window.addEventListener("resize", ajusterBoutons);
  ajusterBoutons();

  // --- Téléphone : panneau des variables fixé en bas, repliable ---------------------------
  // Les boutons Reculer / Avancer passent dans le panneau (sous le pouce) ; sur grand écran
  // ils reviennent sous l'éditeur. L'état ouvert / replié est mémorisé sur l'appareil.
  const side = document.getElementById("stepper-side");
  const sheetHeader = document.getElementById("stepper-feuille-entete");
  const summaryEl = document.getElementById("stepper-resume");
  const mobileSlot = document.getElementById("stepper-controls-mobile");
  const pageEl = document.querySelector(".stepper-page");
  const mainEl = controles.parentElement;                 // colonne principale (grand écran)
  const outputEl = document.getElementById("stepper-output");
  const affichageSlot = document.getElementById("stepper-affichage-mobile");
  const sheetDot = document.getElementById("stepper-feuille-point");
  const ongletBoutons = side ? side.querySelectorAll(".stepper-onglet") : [];
  let ongletActif = "variables";
  let affichageVu = "";   // texte de « Output » au dernier passage sur l'onglet Affichage
  const mobileQuery = window.matchMedia("(max-width: 760px)");
  const SHEET_KEY = "codexo-pas-a-pas-variables-ouvert";

  function readSheetState() {
    try { return window.localStorage.getItem(SHEET_KEY) === "1"; } catch (e) { return false; }
  }
  function setSheetOpen(open) {
    side.classList.toggle("ouvert", open);
    sheetHeader.setAttribute("aria-expanded", open ? "true" : "false");
    try { window.localStorage.setItem(SHEET_KEY, open ? "1" : "0"); } catch (e) { /* navigation privée */ }
  }
  function placeControls() {
    if (mobileQuery.matches) {
      if (controles.parentElement !== mobileSlot) mobileSlot.appendChild(controles);
      if (outputEl && affichageSlot && outputEl.parentElement !== affichageSlot) affichageSlot.appendChild(outputEl);
    } else if (controles.parentElement === mobileSlot) {
      // Retour sous l'éditeur, dans l'ordre d'origine : boutons puis « Output ».
      mainEl.appendChild(controles);
      if (outputEl) mainEl.appendChild(outputEl);
    }
    ajusterBoutons();
    adjustPagePadding();
  }
  // Le panneau replié recouvre le bas de la page : on réserve sa hauteur pour pouvoir faire
  // défiler tout le contenu au-dessus.
  function adjustPagePadding() {
    if (!pageEl || !side) return;
    pageEl.style.paddingBottom = mobileQuery.matches && !side.classList.contains("ouvert")
      ? side.offsetHeight + 12 + "px"
      : mobileQuery.matches ? "45vh" : "";
  }
  // Onglets du panneau (téléphone) : Variables / Affichage. Un point orange signale un
  // affichage nouveau (print, message, erreur) pas encore vu.
  function contenuAffichage() {
    return (printEl ? printEl.textContent : "") + "\n" + msgEl.textContent;
  }
  function choisirOnglet(nom) {
    ongletActif = nom;
    if (side) side.classList.toggle("onglet-affichage", nom === "affichage");
    ongletBoutons.forEach(function (b) {
      const actif = b.dataset.onglet === nom;
      b.classList.toggle("actif", actif);
      b.setAttribute("aria-selected", actif ? "true" : "false");
    });
    if (nom === "affichage") affichageVu = contenuAffichage();
    majPointAffichage();
  }
  function majPointAffichage() {
    const nouveau = contenuAffichage() !== affichageVu && contenuAffichage().trim() !== "";
    const montrer = nouveau && !(ongletActif === "affichage" && side && side.classList.contains("ouvert"));
    side && side.querySelectorAll(".stepper-onglet-point").forEach(function (p) { p.hidden = !montrer; });
    if (sheetDot) sheetDot.hidden = !montrer;
  }
  ongletBoutons.forEach(function (b) {
    b.addEventListener("click", function () { choisirOnglet(b.dataset.onglet); adjustPagePadding(); });
  });

  if (side && sheetHeader && mobileSlot) {
    sheetHeader.addEventListener("click", function () {
      setSheetOpen(!side.classList.contains("ouvert"));
      if (ongletActif === "affichage" && side.classList.contains("ouvert")) affichageVu = contenuAffichage();
      majPointAffichage();
      adjustPagePadding();
    });
    setSheetOpen(readSheetState());
    if (mobileQuery.addEventListener) mobileQuery.addEventListener("change", placeControls);
    else if (mobileQuery.addListener) mobileQuery.addListener(placeControls);
    placeControls();
  }

  // Résumé de l'en-tête du panneau : nombre de variables de la fonction en cours et
  // variables créées / modifiées par l'étape qui vient de s'exécuter.
  function updateSummary(stack, marks) {
    if (!summaryEl) return;
    summaryEl.textContent = "";
    const label = document.createElement("strong");
    label.textContent = "Variables";
    summaryEl.appendChild(label);
    // Détail (nombre, variables modifiées) : masqué quand le panneau est ouvert (stepper.css).
    const detail = document.createElement("span");
    detail.className = "stepper-resume-detail";
    summaryEl.appendChild(detail);
    if (!stack || stack.length === 0) {
      detail.appendChild(document.createTextNode(" · aucune pour l'instant"));
      return;
    }
    const ordered = stack.slice().reverse();
    let current = ordered.length - 1;
    while (current > 0 && ordered[current].done) current--;
    const vars = ordered[current].vars || [];
    const count = document.createElement("small");
    count.textContent = " (" + vars.length + ")";
    detail.appendChild(count);
    const currentMarks = (marks && marks[current]) || {};
    const names = Object.keys(currentMarks);
    if (names.length === 0) return;
    detail.appendChild(document.createTextNode(" · "));
    names.slice(0, 2).forEach(function (name, i) {
      if (i > 0) detail.appendChild(document.createTextNode(", "));
      const code = document.createElement("code");
      code.className = "stepper-resume-nom";
      code.textContent = name;
      detail.appendChild(code);
    });
    const allNew = names.every(function (n) { return currentMarks[n] === "nouvelle"; });
    const plural = names.length > 1;
    const word = document.createElement("small");
    word.textContent = (names.length > 2 ? "…" : "") + " " +
      (allNew ? "créée" : "modifiée") + (plural ? "s" : "");
    detail.appendChild(word);
  }

  let cm = null;
  let pyodide = null;
  let calls = [];
  let steps = [];
  let truncated = false;
  let dirty = false; // code modifié depuis le dernier tracé
  let unsentClicks = 0; // clics Avancer/Reculer pas encore envoyés (page Trafic)
  let output = []; // sortie des print(), en caractères (comme les longueurs comptées côté Python)
  let index = 0;
  let currentLine = null; // ligne CodeMirror (base 0) actuellement surlignée en entier
  let callMark = null; // surlignage de l'expression d'appel (CodeMirror TextMarker)
  let retLine = null; // ligne CodeMirror (base 0) du return surligné en même temps que la ligne appelante
  const MAX_VISIBLE_FRAMES = 3; // cadres de variables affichés au plus (les plus récents)
  const RESULT_VAR = "res"; // le test est lancé par « res = appel » dans le programme principal
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
    if (cm && retLine !== null) cm.removeLineClass(retLine, "background", LINE_CLASS);
    retLine = null;
    if (callMark) callMark.clear();
    callMark = null;
    if (callEl) callEl.classList.remove("active", "full");
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

  // Panneau des variables à hauteur limitée (téléphone) : on garde la position de défilement
  // d'une étape à l'autre, et on fait défiler jusqu'à la variable créée ou modifiée si elle est
  // hors de vue. Sur ordinateur, la zone ne défile pas : rien ne bouge.
  function montrerVariableModifiee(ancienDefilement) {
    varsBox.scrollTop = ancienDefilement;
    if (varsBox.scrollHeight <= varsBox.clientHeight) return;
    // Toutes les variables modifiées de la fonction en cours, de la première à la dernière :
    // si le bloc tient dans le panneau, il est entièrement visible ; sinon la première
    // variable modifiée est placée en haut, les suivantes en dessous.
    const lignes = varsBox.querySelectorAll(".stepper-scope.current tr.stepper-changed");
    if (!lignes.length) return;
    const zone = varsBox.getBoundingClientRect();
    // Première variable du cadre (entrée dans une fonction) : on montre aussi son nom.
    const premiere = lignes[0];
    const titre = premiere === premiere.parentElement.firstElementChild
      ? premiere.closest(".stepper-scope").querySelector(".stepper-scope-title") : null;
    const haut = (titre || premiere).getBoundingClientRect().top - 8;
    const bas = lignes[lignes.length - 1].getBoundingClientRect().bottom + 8;
    if (bas - haut > zone.height || haut < zone.top) varsBox.scrollTop += haut - zone.top;
    else if (bas > zone.bottom) varsBox.scrollTop += bas - zone.bottom;
  }

  function renderVars(stack, marks) {
    const ancienDefilement = varsBox.scrollTop;
    renderVarsContenu(stack, marks);
    montrerVariableModifiee(ancienDefilement);
  }

  function renderVarsContenu(stack, marks) {
    varsBox.textContent = "";
    if (!stack || stack.length === 0) return; // niveau global uniquement : rien à montrer
    // L'appelant en haut, la fonction appelée en dessous (la plus récente = la dernière).
    const heading = document.createElement("h2");
    heading.className = "stepper-vars-title visually-hidden"; // pour les lecteurs d'écran seulement
    heading.textContent = "État des variables";
    varsBox.appendChild(heading);
    const ordered = stack.slice().reverse();
    // Cadre en cours : le dernier qui n'est pas celui, grisé, d'une fonction qui vient de se terminer.
    let currentIndex = ordered.length - 1;
    while (currentIndex > 0 && ordered[currentIndex].done) currentIndex--;
    // Au plus MAX_VISIBLE_FRAMES cadres affichés : les plus anciens (en haut) sont masqués,
    // et une ligne indique combien (utile en récursion, où la pile peut être profonde).
    const firstVisible = Math.max(0, ordered.length - MAX_VISIBLE_FRAMES);
    if (firstVisible > 0) {
      const hidden = document.createElement("div");
      hidden.className = "stepper-hidden-frames";
      hidden.textContent = "… " + firstVisible + " cadre" + (firstVisible > 1 ? "s" : "") +
        " précédent" + (firstVisible > 1 ? "s" : "") + " masqué" + (firstVisible > 1 ? "s" : "");
      varsBox.appendChild(hidden);
    }
    ordered.forEach(function (scope, i) {
      if (i < firstVisible) return;
      if (i > 0) {
        // Petit triangle entre deux cadres : la fonction du dessus appelle celle du dessous.
        const arrow = document.createElement("div");
        arrow.className = "stepper-call-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "▼";
        varsBox.appendChild(arrow);
      }
      const section = document.createElement("div");
      section.className = "stepper-scope" + (scope.done ? " done" : i === currentIndex ? " current" : "");
      section.style.setProperty("--profondeur", i - firstVisible); // décalage sur téléphone
      const title = document.createElement("div");
      title.className = "stepper-scope-title";
      // Le grand titre « État des variables » est au-dessus ; chaque cadre porte le nom de sa fonction.
      title.textContent = scope.scope.indexOf(TITLE_PREFIX) === 0
        ? scope.scope.slice(TITLE_PREFIX.length)
        : scope.scope;
      section.appendChild(title);

      if (scope.vars !== null) {
        if (scope.vars.length > 0) { // sans variable : le bandeau seul
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

  // Lignes surlignées à l'étape affichée (base 0), pour defilerVersEtape().
  let lignesSurlignees = [];

  // Après « Avancer » / « Reculer » : si ce qui est surligné (lignes du code, ou appel du test
  // sous l'éditeur) n'est pas entièrement visible entre la barre du haut et le panneau des
  // variables (téléphone), la PAGE défile en douceur juste ce qu'il faut. Déjà visible : rien
  // ne bouge.
  function defilerVersEtape() {
    const boites = lignesSurlignees.map(function (l) {
      const c = cm.charCoords({ line: l, ch: 0 }, "window");
      const fin = cm.charCoords({ line: l, ch: cm.getLine(l) ? cm.getLine(l).length : 0 }, "window");
      return { top: c.top, bottom: Math.max(c.bottom, fin.bottom) };
    });
    if (callEl && (callEl.classList.contains("active") || callEl.classList.contains("full"))) {
      boites.push(callEl.getBoundingClientRect());
    }
    if (!boites.length) return;
    const haut = Math.min.apply(null, boites.map(function (b) { return b.top; }));
    const bas = Math.max.apply(null, boites.map(function (b) { return b.bottom; }));

    const marge = 16;
    const entete = document.querySelector("header.site");
    let zoneHaut = (entete ? entete.getBoundingClientRect().bottom : 0) + marge;
    let zoneBas = window.innerHeight - marge;
    if (side && mobileQuery.matches && !side.classList.contains("chargement")) {
      zoneBas = Math.min(zoneBas, side.getBoundingClientRect().top - marge);
    }
    let decalage = 0;
    if (bas - haut > zoneBas - zoneHaut || haut < zoneHaut) decalage = haut - zoneHaut;
    else if (bas > zoneBas) decalage = bas - zoneBas;
    if (decalage) window.scrollBy({ top: decalage, behavior: "smooth" });
  }

  function render() {
    clearHighlight();

    const step = steps[index];
    const isLast = index === steps.length - 1;

    // Une erreur sur la ligne d'appel du test (ex : fonction mal nommée) n'a pas de ligne dans le code.
    const showLine = step.line >= 1 && step.line !== callLine;
    const showCall = !!step.call && step.call.line !== callLine;
    // Return + ligne qui récupère la valeur, fusionnés en une étape : le return aussi est surligné.
    const showRet = step.ret >= 1 && step.ret !== step.line;
    // Entrée dans la fonction testée (ou erreur sur l'appel lui-même) : on surligne l'appel
    // dans la ligne de console sous l'éditeur.
    if (callEl && callLine !== null) {
      // Entrée dans la fonction testée : seul l'appel est surligné. Fin du test (res reçu)
      // ou erreur sur cette ligne : toute l'instruction « res = appel ».
      callEl.classList.toggle("active", !!step.call && step.call.line === callLine);
      callEl.classList.toggle("full", step.line === callLine);
    }
    lignesSurlignees = [];
    if (cm) {
      if (showLine) {
        currentLine = step.line - 1;
        cm.addLineClass(currentLine, "background", LINE_CLASS);
      }
      if (showRet) {
        retLine = step.ret - 1;
        cm.addLineClass(retLine, "background", LINE_CLASS);
      }
      if (showCall) {
        callMark = cm.markText(
          { line: step.call.line - 1, ch: step.call.col },
          { line: step.call.endLine - 1, ch: step.call.endCol },
          { className: CALL_CLASS }
        );
      }
      if (showLine || showCall || showRet) {
        const where = [];
        if (showLine) where.push(step.line - 1);
        if (showRet) where.push(step.ret - 1);
        if (showCall) where.push(step.call.line - 1);
        lignesSurlignees = where;
        cm.scrollIntoView(
          { from: { line: Math.min.apply(null, where), ch: 0 }, to: { line: Math.max.apply(null, where), ch: 0 } },
          60
        );
      }
    }

    const changed = diffStacks(index > 0 ? steps[index - 1].stack : null, step.stack);

    afficherPosition(index + 1, steps.length);
    prevBtn.disabled = index === 0;
    nextBtn.disabled = isLast;

    if (printEl) printEl.textContent = output.slice(0, step.out || 0).join("");

    if (step.error) {
      showMessage(step.error, true);
    } else {
      const parts = [];
      if (step.fin) parts.push("Fin de la fonction sans return : elle renvoie None.");
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
    updateSummary(step.stack, changed);
    if (step.error && mobileQuery.matches && side) {
      setSheetOpen(true);
      choisirOnglet("affichage");
    } else if (ongletActif === "affichage" && side && side.classList.contains("ouvert")) {
      affichageVu = contenuAffichage();
    }
    majPointAffichage();
    adjustPagePadding();
  }

  // Réordonne les appels (voir PY_MESURE). Exercice non récursif, ou mesure impossible : ordre
  // d'origine.
  async function orderCalls(list, solution) {
    if (list.length < 2 || !solution) return list;
    let mesures;
    try {
      pyodide.globals.set("__MESURE_SOLUTION__", solution);
      pyodide.globals.set("__MESURE_CALLS__", pyodide.toPy(list));
      mesures = JSON.parse(await pyodide.runPythonAsync(PY_MESURE));
    } catch (e) {
      return list;
    }
    if (!mesures || mesures.length !== list.length) return list;
    const items = list.map(function (call, i) {
      return { call: call, depth: mesures[i][0], count: mesures[i][1], i: i };
    });
    const recursifs = items.filter(function (it) { return it.depth >= 2; });
    if (recursifs.length === 0) return list;
    recursifs.sort(function (a, b) { return a.depth - b.depth || a.count - b.count || a.i - b.i; });
    const casDeBase = items.filter(function (it) { return it.depth < 2; });
    // D'abord un exemple « normal » pas trop long (le moins profond d'au moins 3 niveaux), puis
    // les cas de base, puis les autres tests récursifs du moins au plus profond.
    const premier = recursifs.find(function (it) { return it.depth >= 3; }) || recursifs[0];
    const autres = recursifs.filter(function (it) { return it !== premier; });
    return [premier].concat(casDeBase, autres).map(function (it) { return it.call; });
  }

  // Remplit le menu avec un appel par cas de test (le premier est choisi d'office).
  // Masqué s'il n'y a aucun cas de test : le code est alors tracé seul.
  function fillCases() {
    caseSel.textContent = "";
    calls.forEach(function (call, i) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = RESULT_VAR + " = " + call + "  # test " + (i + 1);
      caseSel.appendChild(opt);
    });
    if (calls.length) caseSel.value = "0";
    caseRow.hidden = calls.length === 0;
    // Liste déroulante (faite maison, pour garder la coloration et le style de l'éditeur).
    caseList.textContent = "";
    calls.forEach(function (call, i) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.tabIndex = -1;
      li.dataset.index = String(i);
      fillCall(li, i);
      caseList.appendChild(li);
    });
    caseRow.classList.toggle("single", calls.length < 2); // un seul test : rien à choisir
    if (editorBox) editorBox.classList.toggle("with-call", calls.length > 0);
    renderCallLine();
  }

  // Affiche « res = appel  # test n » avec une coloration simple (comme dans l'éditeur).
  function addSpan(parent, cls, text) {
    const span = document.createElement("span");
    if (cls) span.className = cls;
    span.textContent = text;
    parent.appendChild(span);
    return span;
  }
  function renderCallLine() {
    if (!callEl) return;
    callEl.classList.remove("active", "full");
    fillCall(callEl, Number(caseSel.value));
  }
  function fillCall(el, i) {
    el.textContent = "";
    const call = calls[i];
    if (call === undefined) return;
    const stmt = addSpan(el, "stepper-call-stmt", ""); // toute l'instruction « res = appel »
    addSpan(stmt, "", RESULT_VAR + " = ");
    const expr = addSpan(stmt, "stepper-call-expr", "");
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
    addSpan(el, "c", "  # test " + (i + 1));
  }

  // Ouverture / fermeture de la liste des tests, à la souris et au clavier.
  function openList() {
    if (calls.length < 2 || callBtn.disabled) return;
    const current = Number(caseSel.value);
    Array.prototype.forEach.call(caseList.children, function (li, i) {
      li.setAttribute("aria-selected", i === current ? "true" : "false");
    });
    caseList.hidden = false;
    callBtn.setAttribute("aria-expanded", "true");
    const selected = caseList.children[current];
    if (selected) selected.focus();
  }
  function closeList(refocus) {
    if (caseList.hidden) return;
    caseList.hidden = true;
    callBtn.setAttribute("aria-expanded", "false");
    if (refocus) callBtn.focus();
  }
  function chooseCase(i) {
    closeList(true);
    if (String(i) === caseSel.value) return;
    caseSel.value = String(i);
    caseSel.dispatchEvent(new Event("change"));
  }
  callBtn.addEventListener("click", function () {
    if (caseList.hidden) openList();
    else closeList(false);
  });
  callBtn.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      openList();
    }
  });
  caseList.addEventListener("click", function (event) {
    const li = event.target.closest("li");
    if (li) chooseCase(Number(li.dataset.index));
  });
  caseList.addEventListener("keydown", function (event) {
    const li = event.target.closest("li");
    if (!li) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = event.key === "ArrowDown" ? li.nextElementSibling : li.previousElementSibling;
      if (next) next.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      chooseCase(Number(li.dataset.index));
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeList(true);
    } else if (event.key === "Tab") {
      closeList(false);
    }
  });
  document.addEventListener("click", function (event) {
    if (!caseRow.contains(event.target)) closeList(false);
  });

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
      source = code + "\n" + RESULT_VAR + " = " + callText + "\n";
      callLine = code.split("\n").length + 1;
    }

    caseSel.disabled = true;
    callBtn.disabled = true;
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
    callBtn.disabled = false;

    clearHighlight();
    steps = result.steps;
    truncated = !!result.truncated;
    output = Array.from(result.output || "");
    index = 0;
    varsBox.textContent = "";
    updateSummary(null);
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
      if (/(import|from)\s+numpy\b/.test(data.test_code || "")) await pyodide.loadPackage("numpy");
      calls = await orderCalls(calls, data.solution_code || "");
    } catch (e) {
      showMessage("Erreur de chargement de Python.", true);
      return;
    }
    fillCases();
    await trace();
    // Python prêt : le panneau du bas (téléphone) retrouve variables et boutons.
    if (side) side.classList.remove("chargement");
    ajusterBoutons();
    adjustPagePadding();
  }

  // Code modifié : la trace enregistrée ne correspond plus. On efface le surlignage AVANT la
  // modification (les numéros de ligne peuvent bouger), et « Relancer » remplace les boutons.
  function onBeforeChange(editor, change) {
    if (change.origin === "setValue" || dirty) return;
    dirty = true;
    clearHighlight();
    steps = [];
    varsBox.textContent = "";
    updateSummary(null);
    posEl.textContent = "";
    if (printEl) printEl.textContent = "";
    prevBtn.hidden = true;
    nextBtn.hidden = true;
    rerunBtn.hidden = false;
    showMessage("Code modifié : cliquer sur « Relancer » pour le parcourir à nouveau.", false);
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
    if (index < steps.length - 1) { index++; unsentClicks++; render(); defilerVersEtape(); }
  });
  prevBtn.addEventListener("click", function () {
    if (index > 0) { index--; unsentClicks++; render(); defilerVersEtape(); }
  });

  // Envoi du nombre de clics au serveur quand on quitte la page ou qu'elle passe en
  // arrière-plan (même principe que la sauvegarde du code dans exercise.js).
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : "";
  }
  function sendUsage() {
    if (!unsentClicks || typeof STEP_USAGE_URL === "undefined" || !navigator.sendBeacon) return;
    const payload = new URLSearchParams();
    payload.set("steps", String(unsentClicks));
    payload.set("csrfmiddlewaretoken", getCookie("csrftoken"));
    if (navigator.sendBeacon(STEP_USAGE_URL, payload)) unsentClicks = 0;
  }
  window.addEventListener("pagehide", sendUsage);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") sendUsage();
  });
  init();
})();
