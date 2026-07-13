import json
import math
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db, QUIZ_DURATION_SECONDS, CORRECT_POINTS, WRONG_POINTS, PASS_THRESHOLD
from . import questions as qmod

bp = Blueprint("quiz", __name__, url_prefix="/quiz")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    return datetime.fromisoformat(value)


def _get_owned_attempt(db, attempt_id):
    attempt = db.execute(
        "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
    ).fetchone()
    if attempt is None or attempt["user_id"] != g.user["id"]:
        abort(404)
    return attempt


def _effective_elapsed(attempt, now=None):
    """Seconds actually counted against the timer, excluding any paused time."""
    now = now or datetime.now(timezone.utc)
    started = _parse_iso(attempt["started_at"])
    total_paused = attempt["paused_seconds"] or 0
    if attempt["paused_at"]:
        total_paused += (now - _parse_iso(attempt["paused_at"])).total_seconds()
    return max(0.0, (now - started).total_seconds() - total_paused)


def _remaining_seconds(attempt, now=None):
    return attempt["duration_seconds"] - _effective_elapsed(attempt, now=now)


def _resume_if_paused(db, attempt):
    """If the attempt is currently paused, fold the paused duration into
    paused_seconds and clear paused_at. Returns a fresh copy of the row."""
    if attempt["paused_at"]:
        delta = (datetime.now(timezone.utc) - _parse_iso(attempt["paused_at"])).total_seconds()
        new_total = int((attempt["paused_seconds"] or 0) + delta)
        db.execute(
            "UPDATE attempts SET paused_at = NULL, paused_seconds = ? WHERE id = ?",
            (new_total, attempt["id"]),
        )
        db.commit()
        return _get_owned_attempt(db, attempt["id"])
    return attempt


def _pause_now(db, attempt):
    if not attempt["paused_at"]:
        db.execute(
            "UPDATE attempts SET paused_at = ? WHERE id = ?",
            (_now_iso(), attempt["id"]),
        )
        db.commit()


def _save_answers_from_form(db, attempt_id, form):
    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ?", (attempt_id,)
    ).fetchall()
    for row in answer_rows:
        field = f"answer_{row['position']}"
        if field not in form:
            # radio not submitted (e.g. disabled while paused) - leave any
            # previously saved answer untouched instead of wiping it
            continue
        raw = form.get(field)
        selected_position = int(raw) if raw not in (None, "") else None
        is_correct = None
        if selected_position is not None:
            order = json.loads(row["option_order"])
            is_correct = 1 if order[selected_position] == 0 else 0
        db.execute(
            "UPDATE attempt_answers SET selected_position = ?, is_correct = ? WHERE id = ?",
            (selected_position, is_correct, row["id"]),
        )
    db.commit()


def _grade_and_close(db, attempt, status):
    answers = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ?", (attempt["id"],)
    ).fetchall()
    correct_count = sum(1 for a in answers if a["is_correct"] == 1)

    weighted_score = None
    if attempt["mode"] == "full":
        wrong_count = sum(
            1 for a in answers if a["selected_position"] is not None and a["is_correct"] == 0
        )
        weighted_score = round(correct_count * CORRECT_POINTS + wrong_count * WRONG_POINTS, 2)

    db.execute(
        """UPDATE attempts SET status = ?, finished_at = ?, correct_count = ?, weighted_score = ?
           WHERE id = ?""",
        (status, _now_iso(), correct_count, weighted_score, attempt["id"]),
    )
    db.commit()


def create_attempt(db, user_id, selected, duration_seconds, mode="practice"):
    """Persist a new attempt (and its question snapshot) and return its id."""
    cur = db.execute(
        """INSERT INTO attempts (user_id, started_at, duration_seconds, status, total_questions, mode)
           VALUES (?, ?, ?, 'in_progress', ?, ?)""",
        (user_id, _now_iso(), duration_seconds, len(selected), mode),
    )
    attempt_id = cur.lastrowid

    for position, item in enumerate(selected):
        db.execute(
            """INSERT INTO attempt_answers (attempt_id, position, question_id, subject, option_order)
               VALUES (?, ?, ?, ?, ?)""",
            (attempt_id, position, item["question_id"], item["subject"],
             json.dumps(item["option_order"])),
        )
    db.commit()
    return attempt_id


@bp.route("/new", methods=("POST",))
@login_required
def new_attempt():
    db = get_db()
    rows = db.execute("SELECT subject, quota FROM subject_quota").fetchall()
    subject_quota = {r["subject"]: r["quota"] for r in rows}

    selected = qmod.build_quiz(subject_quota)
    if not selected:
        return redirect(url_for("dashboard.settings"))

    attempt_id = create_attempt(db, g.user["id"], selected, QUIZ_DURATION_SECONDS, mode="full")
    return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))


@bp.route("/<int:attempt_id>")
@login_required
def view_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    # coming back to the page always resumes the clock
    attempt = _resume_if_paused(db, attempt)

    remaining = _remaining_seconds(attempt)
    if remaining <= 0:
        _grade_and_close(db, attempt, "expired")
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ? ORDER BY position",
        (attempt_id,),
    ).fetchall()

    items = []
    for row in answer_rows:
        q = qmod.get_question(row["question_id"])
        order = json.loads(row["option_order"])
        display_options = [q["options"][i] for i in order]
        items.append({
            "position": row["position"],
            "subject": row["subject"],
            "question": q["question"],
            "options": display_options,
            "selected_position": row["selected_position"],
        })

    subjects_in_order = []
    for item in items:
        if item["subject"] not in subjects_in_order:
            subjects_in_order.append(item["subject"])
    grouped = [
        {"subject": s, "questions": [it for it in items if it["subject"] == s]}
        for s in subjects_in_order
    ]

    return render_template(
        "quiz.html",
        attempt=attempt,
        grouped=grouped,
        remaining_seconds=int(remaining),
    )


@bp.route("/<int:attempt_id>/pause", methods=("POST",))
@login_required
def pause_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)
    if attempt["status"] != "in_progress":
        return jsonify({"error": "not in progress"}), 400

    _save_answers_from_form(db, attempt_id, request.form)
    _pause_now(db, attempt)
    return jsonify({"status": "paused"})


@bp.route("/<int:attempt_id>/resume", methods=("POST",))
@login_required
def resume_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)
    if attempt["status"] != "in_progress":
        return jsonify({"error": "not in progress"}), 400

    attempt = _resume_if_paused(db, attempt)
    remaining = max(0, int(_remaining_seconds(attempt)))
    return jsonify({"remaining_seconds": remaining})


@bp.route("/<int:attempt_id>/save_and_exit", methods=("POST",))
@login_required
def save_and_exit(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)
    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    _save_answers_from_form(db, attempt_id, request.form)
    _pause_now(db, attempt)
    flash("Simulazione salvata e messa in pausa: la trovi tra quelle \"in corso\" nella dashboard.")
    return redirect(url_for("dashboard.home"))


@bp.route("/<int:attempt_id>/submit", methods=("POST",))
@login_required
def submit_attempt(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] != "in_progress":
        return redirect(url_for("quiz.results", attempt_id=attempt_id))

    elapsed = _effective_elapsed(attempt)
    status = "expired" if elapsed > attempt["duration_seconds"] + 5 else "completed"

    _save_answers_from_form(db, attempt_id, request.form)
    _grade_and_close(db, attempt, status)
    return redirect(url_for("quiz.results", attempt_id=attempt_id))


@bp.route("/<int:attempt_id>/results")
@login_required
def results(attempt_id):
    db = get_db()
    attempt = _get_owned_attempt(db, attempt_id)

    if attempt["status"] == "in_progress":
        return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))

    answer_rows = db.execute(
        "SELECT * FROM attempt_answers WHERE attempt_id = ? ORDER BY position",
        (attempt_id,),
    ).fetchall()

    items = []
    subject_totals = {}
    for row in answer_rows:
        q = qmod.get_question(row["question_id"])
        order = json.loads(row["option_order"])
        display_options = [q["options"][i] for i in order]
        correct_position = order.index(0)
        items.append({
            "subject": row["subject"],
            "question": q["question"],
            "options": display_options,
            "selected_position": row["selected_position"],
            "correct_position": correct_position,
            "is_correct": row["is_correct"],
        })
        st = subject_totals.setdefault(row["subject"], {"total": 0, "correct": 0, "answered": 0})
        st["total"] += 1
        st["answered"] += 1 if row["selected_position"] is not None else 0
        st["correct"] += 1 if row["is_correct"] == 1 else 0

    subjects_in_order = []
    for item in items:
        if item["subject"] not in subjects_in_order:
            subjects_in_order.append(item["subject"])

    subject_rows = [
        {"subject": s, **subject_totals[s]} for s in subjects_in_order
    ]

    pct = round((attempt["correct_count"] or 0) / attempt["total_questions"] * 100, 1)

    max_score = None
    is_pass = None
    if attempt["mode"] == "full":
        max_score = round(attempt["total_questions"] * CORRECT_POINTS, 2)
        is_pass = (attempt["weighted_score"] or 0) >= PASS_THRESHOLD

    # the gauge always mirrors the same "corrette" percentage shown in text,
    # so the two numbers next to each other never disagree; colour alone
    # carries the idoneo/non idoneo signal for full simulations
    gauge_circumference = round(2 * math.pi * 54, 2)
    gauge_offset = round(gauge_circumference * (1 - pct / 100), 2)

    return render_template(
        "results.html",
        attempt=attempt,
        items=items,
        subject_rows=subject_rows,
        pct=pct,
        gauge_pct=round(pct),
        gauge_circumference=gauge_circumference,
        gauge_offset=gauge_offset,
        max_score=max_score,
        is_pass=is_pass,
        pass_threshold=PASS_THRESHOLD,
    )
