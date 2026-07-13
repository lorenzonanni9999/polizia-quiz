from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod
from .quiz import create_attempt, MIN_MINUTES, MAX_MINUTES
from .review import wrong_question_ids

bp = Blueprint("practice", __name__, url_prefix="/practice")

STUDY_DURATION_SECONDS = 24 * 60 * 60  # study mode has no real timer


@bp.route("/")
@login_required
def hub():
    db = get_db()
    review_count = len(wrong_question_ids(db, g.user["id"]))
    bookmark_count = db.execute(
        "SELECT COUNT(*) AS n FROM bookmarks WHERE user_id = ?", (g.user["id"],)
    ).fetchone()["n"]
    return render_template("practice_hub.html", review_count=review_count, bookmark_count=bookmark_count)


@bp.route("/subject")
@login_required
def form():
    subjects = [
        {"subject": s, "available": qmod.subject_question_count(s)}
        for s in qmod.get_subjects()
    ]
    return render_template("practice.html", subjects=subjects)


@bp.route("/subject/new", methods=("POST",))
@login_required
def new_practice():
    subject = request.form.get("subject", "")
    available = qmod.subject_question_count(subject)
    if available == 0:
        flash("Materia non valida.")
        return redirect(url_for("practice.form"))

    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    try:
        minutes = int(request.form.get("minutes", "0"))
    except ValueError:
        minutes = 0

    count = max(1, min(count, available))
    minutes = max(MIN_MINUTES, min(minutes, MAX_MINUTES))

    db = get_db()
    selected = qmod.build_single_subject_quiz(subject, count)
    attempt_id = create_attempt(db, g.user["id"], selected, minutes * 60, mode="practice")
    return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))


@bp.route("/study")
@login_required
def study_form():
    subjects = [
        {"subject": s, "available": qmod.subject_question_count(s)}
        for s in qmod.get_subjects()
    ]
    return render_template("study_form.html", subjects=subjects)


@bp.route("/study/new", methods=("POST",))
@login_required
def new_study():
    subject = request.form.get("subject", "")
    available = qmod.subject_question_count(subject)
    if available == 0:
        flash("Materia non valida.")
        return redirect(url_for("practice.study_form"))

    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    count = max(1, min(count, available))

    db = get_db()
    selected = qmod.build_single_subject_quiz(subject, count)
    attempt_id = create_attempt(db, g.user["id"], selected, STUDY_DURATION_SECONDS, mode="study")
    return redirect(url_for("study.view_current", attempt_id=attempt_id))
