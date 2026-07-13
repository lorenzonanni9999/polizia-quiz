from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db, CORRECT_POINTS, PASS_THRESHOLD
from . import questions as qmod

bp = Blueprint("dashboard", __name__)

CHART_WIDTH = 600
CHART_HEIGHT = 160
CHART_PAD_X = 16
CHART_PAD_Y = 14


def _score_history_chart(db, user_id):
    rows = db.execute(
        """
        SELECT started_at, weighted_score, total_questions
        FROM attempts
        WHERE user_id = ? AND mode = 'full' AND status != 'in_progress'
        ORDER BY started_at ASC
        """,
        (user_id,),
    ).fetchall()

    if len(rows) < 2:
        return None

    pass_pct = PASS_THRESHOLD / 30 * 100
    pcts = []
    for r in rows:
        max_score = (r["total_questions"] or 0) * CORRECT_POINTS
        pct = 0.0
        if max_score:
            pct = max(0.0, min(100.0, (r["weighted_score"] or 0) / max_score * 100))
        pcts.append(round(pct, 1))

    plot_w = CHART_WIDTH - 2 * CHART_PAD_X
    plot_h = CHART_HEIGHT - 2 * CHART_PAD_Y
    n = len(pcts)
    step = plot_w / (n - 1)

    def x_of(i):
        return round(CHART_PAD_X + i * step, 1)

    def y_of(pct):
        return round(CHART_PAD_Y + (1 - pct / 100) * plot_h, 1)

    points = [
        {"x": x_of(i), "y": y_of(pct), "pct": pct, "is_pass": pct >= pass_pct}
        for i, pct in enumerate(pcts)
    ]
    polyline = " ".join(f"{p['x']},{p['y']}" for p in points)

    return {
        "points": points,
        "polyline": polyline,
        "threshold_y": y_of(pass_pct),
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
    }


@bp.route("/")
@login_required
def home():
    db = get_db()
    attempts = db.execute(
        """
        SELECT a.id, a.started_at, a.finished_at, a.status, a.total_questions,
               a.correct_count, a.duration_seconds, a.paused_at, a.mode, a.weighted_score,
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

    chart = _score_history_chart(db, g.user["id"])

    return render_template(
        "dashboard.html",
        completed=completed,
        in_progress=in_progress,
        avg_score=avg_score,
        subject_stats=subject_stats,
        chart=chart,
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

        question_order = request.form.get("question_order", "grouped")
        if question_order not in ("grouped", "random"):
            question_order = "grouped"
        db.execute(
            "UPDATE app_settings SET value = ? WHERE key = 'question_order'",
            (question_order,),
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

    order_row = db.execute(
        "SELECT value FROM app_settings WHERE key = 'question_order'"
    ).fetchone()
    question_order = order_row["value"] if order_row else "grouped"

    return render_template(
        "settings.html",
        subject_info=subject_info,
        total_quota=total_quota,
        question_order=question_order,
    )
