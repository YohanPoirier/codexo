// Worker de vérification des exercices : Pyodide tourne ici, hors de la page, pour qu'un
// programme qui ne se termine pas (boucle infinie, dans le code de l'étudiant ou dans un cas
// de test) ne fige pas la page. La page surveille la durée et, au-delà de la limite, appelle
// worker.terminate() puis relance un worker tout neuf (voir exercise.js).
// Même principe que sandbox-worker.js (le bac à sable).
//
// Messages envoyés à la page :
//   {type: "ready"}                       Python est chargé, on peut vérifier
//   {type: "fatal", message}              Python n'a pas pu être chargé
//   {type: "start", call}                 un test va démarrer ; call = appel testé, ex.
//                                         "nombre_de_lettres('a')" (absent si non identifiable)
//   {type: "result", ok, msg, printed}    résultat d'UN test, envoyé dès qu'il est connu
//   {type: "done", runtimeError, results} fin de la vérification : runtimeError (texte, ou
//                                         null) et la liste complète des résultats
// Messages reçus de la page :
//   {type: "init", numpy, sqlite}        charger Python (et numpy / sqlite3 si l'exercice en a besoin)
//   {type: "run", kind, code, testCode}   vérifier ce code (kind : "python" ou "sql")

importScripts("https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js");

let pyodide = null;

// __EXEC_NS__ : espace de noms FRAÎCHEMENT créé à CHAQUE vérification (ce texte est ré-exécuté
// en entier à chaque appel de runPythonAsync). Sans ça, exec(..., globals()) exécuterait dans
// les globals persistants de pyodide : une fonction définie par une ANCIENNE version du code de
// l'étudiant pourrait y rester et être utilisée par erreur, donnant l'impression que « Vérifier »
// teste un code qui n'est plus celui affiché à l'écran.
//
// __StreamList__ : liste qui prévient la page à chaque append(), donc dès qu'un test a son
// résultat, sans attendre la fin de tous les tests. Le code de test commence par
// « __RESULTS__ = [] » : on remplace cette ligne (voir patchTestCode) pour que la liste créée
// soit une __StreamList__. Si le remplacement échouait, les résultats arriveraient seulement
// à la fin, dans le message « done » (rien ne casse).
const PY_PREAMBLE = `
import sys, io, traceback

class __StreamList__(list):
    def append(self, item):
        list.append(self, item)
        __EMIT__(bool(item[0]), str(item[1]), str(item[2]) if len(item) > 2 else "")

def __START__(args_repr):
    __EMIT_START__(args_repr)

__stdout_capture__ = io.StringIO()
__RUNTIME_ERROR__ = None
`;

const PY_POSTAMBLE = `
_old_stdout = sys.stdout
sys.stdout = __stdout_capture__
try:
__BODY__
except Exception:
    __RUNTIME_ERROR__ = traceback.format_exc()
finally:
    sys.stdout = _old_stdout
__RESULTS__ = [tuple(r) for r in __EXEC_NS__["__RESULTS__"]]
`;

// En SQL, le texte de l'étudiant est une REQUÊTE, pas du code Python à exécuter : le code de
// test (généré côté serveur) l'exécute via sqlite3 et compare au résultat de la requête de correction.
const RUNNER_SQL =
  PY_PREAMBLE +
  `__EXEC_NS__ = {"__RESULTS__": [], "__StreamList__": __StreamList__, "__START__": __START__, "__STUDENT_SQL__": __STUDENT_SQL__}
` +
  PY_POSTAMBLE.replace("__BODY__", "    exec(__TEST_CODE__, __EXEC_NS__)");

// __STUDENT_CODE__ doit aussi exister DANS l'espace de noms de test : les contrôles statiques
// (récursivité exigée, opérateur « in » interdit) font ast.parse(__STUDENT_CODE__).
const RUNNER_PYTHON =
  PY_PREAMBLE +
  `__EXEC_NS__ = {"__RESULTS__": [], "__StreamList__": __StreamList__, "__START__": __START__, "__STUDENT_CODE__": __STUDENT_CODE__}
` +
  PY_POSTAMBLE.replace(
    "__BODY__",
    "    exec(__STUDENT_CODE__, __EXEC_NS__)\n    exec(__TEST_CODE__, __EXEC_NS__)"
  );

// Deux retouches du code de test (généré côté serveur, voir Exercise._build_python_test_code),
// faites ici pour ne rien changer côté Django :
//  1. « __RESULTS__ = [] » devient « __RESULTS__ = __StreamList__() » (résultats au fil de l'eau) ;
//  2. juste après la ligne « _args_repr = ... », on annonce le test qui démarre : si la
//     vérification est coupée, la page peut dire QUEL appel ne se termine pas.
// Si une retouche ne trouve pas son motif (code de test modifié, exercice SQL...), rien ne casse :
// on perd seulement la fonctionnalité correspondante.
let currentFn = null;

function patchTestCode(testCode) {
  const m = testCode.match(/_solution_ns\['(\w+)'\]/);
  currentFn = m ? m[1] : null;
  let code = testCode.replace(/^__RESULTS__ = \[\]/m, "__RESULTS__ = __StreamList__()");
  if (currentFn) {
    code = code.replace(/^([ \t]*)_args_repr = .*$/m, "$&\n$1__START__(_args_repr)");
  }
  return code;
}

async function init(useNumpy, useSqlite) {
  try {
    pyodide = await loadPyodide();
    if (useNumpy) await pyodide.loadPackage("numpy");
    // sqlite3 n'est pas chargé d'office par Pyodide : les exercices SQL en ont besoin (le code de
    // test fait « import sqlite3 »).
    if (useSqlite) await pyodide.loadPackage("sqlite3");
    pyodide.globals.set("__EMIT__", function (ok, msg, printed) {
      postMessage({ type: "result", ok: ok, msg: msg, printed: printed });
    });
    pyodide.globals.set("__EMIT_START__", function (argsRepr) {
      postMessage({ type: "start", call: currentFn + "(" + argsRepr + ")" });
    });
    postMessage({ type: "ready" });
  } catch (e) {
    postMessage({ type: "fatal", message: String(e) });
  }
}

async function run(kind, code, testCode) {
  let runtimeError = null;
  let results = [];
  try {
    pyodide.globals.set("__TEST_CODE__", patchTestCode(testCode));
    if (kind === "sql") pyodide.globals.set("__STUDENT_SQL__", code);
    else pyodide.globals.set("__STUDENT_CODE__", code);

    await pyodide.runPythonAsync(kind === "sql" ? RUNNER_SQL : RUNNER_PYTHON);

    runtimeError = pyodide.globals.get("__RUNTIME_ERROR__") || null;
    if (!runtimeError) {
      const proxy = pyodide.globals.get("__RESULTS__");
      results = proxy ? proxy.toJs() : [];
      if (proxy) proxy.destroy();
    }
  } catch (e) {
    runtimeError = "Erreur inattendue : " + (e && e.message ? e.message : String(e));
  }
  postMessage({ type: "done", runtimeError: runtimeError, results: results });
}

onmessage = function (ev) {
  const msg = ev.data;
  if (msg.type === "init") init(!!msg.numpy, !!msg.sqlite);
  else if (msg.type === "run") run(msg.kind, msg.code, msg.testCode);
};
