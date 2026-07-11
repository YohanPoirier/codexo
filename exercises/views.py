import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect

from .models import Theme, Exercise, Result, Abandonment

# Durée pendant laquelle un exercice est verrouillé après un abandon (voir abandon_exercise
# ci-dessous). Passé ce délai, l'étudiant peut retenter l'exercice normalement.
ABANDON_LOCK_DURATION = timedelta(hours=48)


@login_required
def theme_list(request):
    themes = Theme.objects.all()
    data = []
    for theme in themes:
        total = theme.exercises.count()
        done = (
            Result.objects.filter(user=request.user, exercise__theme=theme, success=True)
            .values("exercise_id")
            .distinct()
            .count()
        )
        data.append({"theme": theme, "total": total, "done": done})
    return render(request, "exercises/theme_list.html", {"themes_data": data})


@login_required
def exercise_list(request, theme_slug):
    theme = get_object_or_404(Theme, slug=theme_slug)
    solved_ids = set(
        Result.objects.filter(user=request.user, exercise__theme=theme, success=True)
        .values_list("exercise_id", flat=True)
    )

    # Pour chaque exercice de ce thème, on ne garde que la date du DERNIER abandon (le plus
    # récent) : c'est lui qui détermine si l'exercice est encore verrouillé ou non.
    latest_abandon_at = {}
    for ab in Abandonment.objects.filter(user=request.user, exercise__theme=theme):
        current = latest_abandon_at.get(ab.exercise_id)
        if current is None or ab.created_at > current:
            latest_abandon_at[ab.exercise_id] = ab.created_at
    now = timezone.now()
    locked_retry_at = {
        ex_id: ts + ABANDON_LOCK_DURATION
        for ex_id, ts in latest_abandon_at.items()
        if now < ts + ABANDON_LOCK_DURATION
    }
    locked_ids = set(locked_retry_at.keys())

    exercises = theme.exercises.all()
    return render(
        request,
        "exercises/exercise_list.html",
        {
            "theme": theme,
            "exercises": exercises,
            "solved_ids": solved_ids,
            "locked_ids": locked_ids,
            "locked_retry_at": locked_retry_at,
            "schema_summary": theme.schema_summary,
        },
    )


@login_required
def exercise_detail(request, theme_slug, exercise_slug):
    theme = get_object_or_404(Theme, slug=theme_slug)
    exercise = get_object_or_404(Exercise, theme=theme, slug=exercise_slug)

    last_abandonment = (
        Abandonment.objects.filter(user=request.user, exercise=exercise).order_by("-created_at").first()
    )
    retry_at = last_abandonment.created_at + ABANDON_LOCK_DURATION if last_abandonment else None
    locked = retry_at is not None and timezone.now() < retry_at

    # Juste après avoir confirmé un abandon (voir abandon_exercise), ce drapeau de session est
    # posé puis consommé ici via .pop() : la solution ne s'affiche donc qu'UNE SEULE FOIS, à
    # l'instant précis où l'étudiant vient de confirmer. À la moindre revisite de la page
    # pendant les 48h (retour arrière, favori...), l'exercice n'est plus consultable du tout.
    just_abandoned = request.session.pop("just_abandoned_exercise_id", None) == exercise.id

    if locked and not just_abandoned:
        messages.info(
            request,
            f"« {exercise.title} » est indisponible jusqu'au {retry_at:%d/%m/%Y à %H:%M} "
            f"(abandon récent). Reviens à ce moment-là pour le retenter.",
        )
        return redirect("exercise_list", theme_slug=theme.slug)

    last_result = (
        Result.objects.filter(user=request.user, exercise=exercise).order_by("-created_at").first()
    )
    hints = list(exercise.hints.all())
    return render(
        request,
        "exercises/exercise_detail.html",
        {
            "theme": theme,
            "exercise": exercise,
            "last_result": last_result,
            "hints": hints,
            "show_solution_once": locked and just_abandoned,
            "retry_at": retry_at,
        },
    )


@login_required
def abandon_exercise(request, exercise_id):
    """Enregistre l'abandon d'un exercice (l'étudiant a confirmé vouloir voir la solution).
    Verrouille l'exercice pendant ABANDON_LOCK_DURATION : il ne sera alors même plus
    consultable (voir exercise_detail), à l'exception de cet instant précis, où la solution
    s'affiche une seule fois (drapeau de session 'just_abandoned_exercise_id')."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    exercise = get_object_or_404(Exercise, id=exercise_id)
    Abandonment.objects.create(user=request.user, exercise=exercise)
    request.session["just_abandoned_exercise_id"] = exercise.id
    return redirect("exercise_detail", theme_slug=exercise.theme.slug, exercise_slug=exercise.slug)


@login_required
def profile(request):
    all_success = (
        Result.objects.filter(user=request.user, success=True)
        .select_related("exercise", "exercise__theme")
        .order_by("exercise__theme__order", "exercise__order", "-created_at")
    )
    seen = set()
    results = []
    for r in all_success:
        if r.exercise_id not in seen:
            seen.add(r.exercise_id)
            results.append(r)
    total_exercises = Exercise.objects.count()
    return render(
        request,
        "exercises/profile.html",
        {"results": results, "total_exercises": total_exercises},
    )


@login_required
def exercise_tests(request, exercise_id):
    """Renvoie le code de test associé à un exercice pour exécution côté navigateur (Pyodide)."""
    exercise = get_object_or_404(Exercise, id=exercise_id)
    return JsonResponse({
        "starter_code": exercise.starter_code,
        "test_code": exercise.build_test_code(),
    })


@login_required
@csrf_protect
def submit_result(request, exercise_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    exercise = get_object_or_404(Exercise, id=exercise_id)

    if request.content_type == "application/json":
        payload = json.loads(request.body.decode("utf-8"))
        submitted_code = payload.get("code", "")
        success = bool(payload.get("success", False))
    else:
        # navigator.sendBeacon() envoie les données au format formulaire classique
        # (application/x-www-form-urlencoded), pas en JSON — utilisé pour la sauvegarde
        # automatique au départ de la page (voir exercise.js), plus fiable que fetch
        # à ce moment précis car le navigateur garantit d'essayer d'envoyer la requête
        # même si la page se ferme juste après l'appel.
        submitted_code = request.POST.get("code", "")
        success = request.POST.get("success") in ("true", "1", "True")

    Result.objects.create(
        user=request.user,
        exercise=exercise,
        submitted_code=submitted_code,
        success=success,
    )
    return JsonResponse({"ok": True})
