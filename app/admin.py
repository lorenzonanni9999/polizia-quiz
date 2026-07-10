from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .auth import admin_required
from .db import get_db

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def home():
    db = get_db()
    users = db.execute(
        "SELECT id, username, is_admin FROM users ORDER BY username"
    ).fetchall()

    stats = db.execute(
        """
        SELECT a.user_id,
               COUNT(*) AS total_attempts,
               SUM(CASE WHEN a.status != 'in_progress' THEN 1 ELSE 0 END) AS completed_attempts,
               SUM(a.correct_count) AS total_correct,
               SUM(CASE WHEN a.status != 'in_progress' THEN a.total_questions ELSE 0 END) AS total_questions_answered,
               MAX(a.started_at) AS last_activity
        FROM attempts a
        GROUP BY a.user_id
        """
    ).fetchall()
    stats_by_user = {s["user_id"]: s for s in stats}

    user_rows = []
    for u in users:
        s = stats_by_user.get(u["id"])
        avg_score = None
        if s and s["total_questions_answered"]:
            avg_score = round((s["total_correct"] or 0) / s["total_questions_answered"] * 100, 1)
        user_rows.append({
            "id": u["id"],
            "username": u["username"],
            "is_admin": u["is_admin"],
            "completed_attempts": (s["completed_attempts"] if s else 0) or 0,
            "avg_score": avg_score,
            "last_activity": s["last_activity"] if s else None,
        })

    return render_template("admin_dashboard.html", user_rows=user_rows)


@bp.route("/users/new", methods=("POST",))
@admin_required
def new_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Nome utente e password sono obbligatori.")
    elif len(password) < 4:
        flash("La password deve avere almeno 4 caratteri.")
    else:
        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            flash("Esiste già un utente con questo nome.")
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                (username, generate_password_hash(password)),
            )
            db.commit()
            flash(f"Utente '{username}' creato.")

    return redirect(url_for("admin.home"))


@bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)

    attempts = db.execute(
        """
        SELECT a.id, a.started_at, a.finished_at, a.status, a.total_questions,
               a.correct_count, a.duration_seconds, a.paused_at,
               COUNT(DISTINCT aa.subject) AS subject_count,
               MIN(aa.subject) AS only_subject
        FROM attempts a
        JOIN attempt_answers aa ON aa.attempt_id = a.id
        WHERE a.user_id = ?
        GROUP BY a.id
        ORDER BY a.started_at DESC
        """,
        (user_id,),
    ).fetchall()

    completed = [a for a in attempts if a["status"] != "in_progress"]
    in_progress = [a for a in attempts if a["status"] == "in_progress"]

    avg_score = None
    if completed:
        pct_sum = sum(
            (a["correct_count"] or 0) / a["total_questions"] * 100 for a in completed
        )
        avg_score = round(pct_sum / len(completed), 1)

    subject_stats = db.execute(
        """
        SELECT subject,
               COUNT(*) AS total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM attempt_answers aa
        JOIN attempts a ON a.id = aa.attempt_id
        WHERE a.user_id = ? AND a.status != 'in_progress'
        GROUP BY subject
        """,
        (user_id,),
    ).fetchall()

    return render_template(
        "admin_user_detail.html",
        user=user,
        completed=completed,
        in_progress=in_progress,
        avg_score=avg_score,
        subject_stats=subject_stats,
    )
