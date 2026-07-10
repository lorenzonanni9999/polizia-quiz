from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db
from . import questions as qmod

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    db = get_db()
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
        (g.user["id"],),
    ).fetchall()

    completed = [a for a in attempts if a["status"] != "in_progress"]
    in_progress = [a for a in attempts if a["status"] == "in_progress"]

    avg_score = None
    if completed:
        pct_sum = sum(
            (a["correct_count"] or 0) / a["total_questions"] * 100
            for a in completed
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
        (g.user["id"],),
    ).fetchall()

    return render_template(
        "dashboard.html",
        completed=completed,
        in_progress=in_progress,
        avg_score=avg_score,
        subject_stats=subject_stats,
    )


@bp.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    db = get_db()
    subjects = qmod.get_subjects()

    if request.method == "POST":
        total = 0
        updates = []
        for subject in subjects:
            raw = request.form.get(f"quota_{subject}", "0")
            try:
                value = int(raw)
            except ValueError:
                value = 0
            max_available = qmod.subject_question_count(subject)
            value = max(0, min(value, max_available))
            updates.append((value, subject))
            total += value

        for value, subject in updates:
            db.execute(
                "UPDATE subject_quota SET quota = ? WHERE subject = ?",
                (value, subject),
            )
        db.commit()
        flash(f"Impostazioni salvate. Domande totali per simulazione: {total}.")

    rows = db.execute("SELECT subject, quota FROM subject_quota").fetchall()
    quota_map = {r["subject"]: r["quota"] for r in rows}
    subject_info = [
        {
            "subject": s,
            "quota": quota_map.get(s, 0),
            "available": qmod.subject_question_count(s),
        }
        for s in subjects
    ]
    total_quota = sum(info["quota"] for info in subject_info)

    return render_template(
        "settings.html", subject_info=subject_info, total_quota=total_quota
    )
