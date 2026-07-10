from functools import wraps

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Credenziali non valide.")
        else:
            session.clear()
            session["user_id"] = user["id"]
            next_url = request.args.get("next") or url_for("dashboard.home")
            return redirect(next_url)

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=("GET", "POST"))
def account():
    if g.user is None:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if not check_password_hash(g.user["password_hash"], current):
            flash("Password attuale errata.")
        elif len(new_password) < 4:
            flash("La nuova password deve avere almeno 4 caratteri.")
        elif new_password != confirm:
            flash("Le due password non coincidono.")
        else:
            db = get_db()
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_password), g.user["id"]),
            )
            db.commit()
            flash("Password aggiornata.")

    return render_template("account.html")
