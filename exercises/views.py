import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_protect

from .models import Theme, Exercise, Result


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
    exercises = theme.exercises.all()
    return render(
        request,
        "exercises/exercise_list.html",
        {"theme": theme, "exercises": exercises, "solved_ids": solved_ids},
    )


@login_required
def exercise_detail(request, theme_slug, exercise_slug):
    theme = get_object_or_404(Theme, slug=theme_slug)
    exercise = get_object_or_404(Exercise, theme=theme, slug=exercise_slug)
    last_result = (
        Result.objects.filter(user=request.user, exercise=exercise).order_by("-created_at").first()
    )
    hints = list(exercise.hints.all())
    return render(
        request,
        "exercises/exercise_detail.html",
        {"theme": theme, "exercise": exercise, "last_result": last_result, "hints": hints},
    )


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
    payload = json.loads(request.body.decode("utf-8"))
    submitted_code = payload.get("code", "")
    success = bool(payload.get("success", False))
    Result.objects.create(
        user=request.user,
        exercise=exercise,
        submitted_code=submitted_code,
        success=success,
    )
    return JsonResponse({"ok": True})
