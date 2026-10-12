// Worker du bac à sable : Pyodide tourne ici, hors de la page, pour que le bouton « Arrêter »
// puisse interrompre un programme qui ne se termine pas (boucle infinie) : la page appelle
// worker.terminate(), ce qui coupe net l'exécution, puis relance un worker tout neuf.
// Une exécution dans la page elle-même (thread principal) ne peut pas être interrompue.
//
// Messages envoyés à la page :
//   {type: "ready"}                  Python est chargé, on peut exécuter
//   {type: "stdout", text}           texte écrit avec print() (envoyé au fil de l'eau)
//   {type: "done", error}            fin de l'exécution (error = texte de l'erreur, ou null)
//   {type: "fatal", message}         Python n'a pas pu être chargé
// Message reçu de la page :
//   {type: "run", code}              exécuter ce code

importScripts("https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js");

let pyodide = null;

// Exécution dans un espace de noms frais à chaque fois (comme pour les exercices, voir
// __EXEC_NS__ dans exercise.js) : une variable définie lors d'une exécution précédente ne
// reste pas disponible par erreur. Les print() sont envoyés à la page par setStdout (voir
// plus bas) ; seule l'erreur éventuelle est renvoyée ici, sans les lignes internes du
// moteur dans le traceback.
const RUNNER = `
import sys, traceback

__sb_error__ = None
__sb_ns__ = {"__name__": "__main__"}

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
    sys.stdout.flush()
`;

async function init() {
  try {
    pyodide = await loadPyodide();
    // Texte brut envoyé au fil de l'eau (et non ligne par ligne, mode « batched ») : sinon un
    // print("...", end="") sans retour à la ligne resterait en attente et n'apparaîtrait pas.
    const decoder = new TextDecoder();
    pyodide.setStdout({
      write: function (buf) {
        postMessage({ type: "stdout", text: decoder.decode(buf, { stream: true }) });
        return buf.length;
      },
    });
    postMessage({ type: "ready" });
  } catch (e) {
    postMessage({ type: "fatal", message: String(e) });
  }
}

onmessage = async function (ev) {
  if (!pyodide || !ev.data || ev.data.type !== "run") return;
  const code = ev.data.code;
  try {
    if (/\bnumpy\b/.test(code)) {
      // Callbacks vides : par défaut, les messages de chargement (« Loading numpy »…)
      // passent par setStdout et apparaîtraient dans l'affichage de l'étudiant.
      await pyodide.loadPackage("numpy", {
        messageCallback: function () {},
        errorCallback: function () {},
      });
    }
    pyodide.globals.set("__SB_CODE__", code);
    await pyodide.runPythonAsync(RUNNER);
    const error = pyodide.globals.get("__sb_error__");
    postMessage({ type: "done", error: error || null });
  } catch (e) {
    postMessage({ type: "done", error: "Erreur inattendue : " + e.message });
  }
};

init();
