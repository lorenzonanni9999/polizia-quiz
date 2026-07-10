from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod
from .quiz import create_attempt

bp = Blueprint("practice", __name__, url_prefix="/practice")

MIN_MINUTES = 1
MAX_MINUTES = 240


@bp.route("/")
@login_required
def form():
    subjects = [
        {"subject": s, "available": qmod.subject_question_count(s)}
        for s in qmod.get_subjects()
    ]
    return render_template("practice.html", subjects=subjects)


@bp.route("/new", methods=("POST",))
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
