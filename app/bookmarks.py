from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod
from .quiz import create_attempt, MIN_MINUTES, MAX_MINUTES

bp = Blueprint("bookmarks", __name__, url_prefix="/bookmarks")


@bp.route("/toggle", methods=("POST",))
@login_required
def toggle():
    db = get_db()
    question_id = request.form.get("question_id", type=int)
    if question_id is None:
        return jsonify({"error": "missing question_id"}), 400

    existing = db.execute(
        "SELECT id FROM bookmarks WHERE user_id = ? AND question_id = ?",
        (g.user["id"], question_id),
    ).fetchone()

    if existing:
        db.execute("DELETE FROM bookmarks WHERE id = ?", (existing["id"],))
        db.commit()
        bookmarked = False
    else:
        db.execute(
            "INSERT INTO bookmarks (user_id, question_id, created_at) VALUES (?, ?, ?)",
            (g.user["id"], question_id, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()
        bookmarked = True

    return jsonify({"bookmarked": bookmarked})


@bp.route("/")
@login_required
def list_bookmarks():
    db = get_db()
    rows = db.execute(
        "SELECT question_id FROM bookmarks WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()
    questions = [qmod.get_question(r["question_id"]) for r in rows]
    return render_template("bookmarks.html", questions=questions)


@bp.route("/new", methods=("POST",))
@login_required
def new_bookmarks_quiz():
    db = get_db()
    rows = db.execute(
        "SELECT question_id FROM bookmarks WHERE user_id = ?", (g.user["id"],)
    ).fetchall()
    question_ids = [r["question_id"] for r in rows]
    if not question_ids:
        return redirect(url_for("bookmarks.list_bookmarks"))

    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    try:
        minutes = int(request.form.get("minutes", "0"))
    except ValueError:
        minutes = 0
    count = max(1, min(count, len(question_ids)))
    minutes = max(MIN_MINUTES, min(minutes, MAX_MINUTES))

    selected = qmod.build_quiz_from_ids(question_ids, count=count)
    attempt_id = create_attempt(db, g.user["id"], selected, minutes * 60, mode="bookmarks")
    return redirect(url_for("quiz.view_attempt", attempt_id=attempt_id))
