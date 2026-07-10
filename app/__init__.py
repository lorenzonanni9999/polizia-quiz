import os
import secrets
from pathlib import Path

from flask import Flask

from . import db as db_module
from . import questions as qmod

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_secret_key(instance_dir):
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    secret_path = instance_dir / "secret_key.txt"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding="utf-8")
    return secret_path.read_text(encoding="utf-8").strip()


def create_app():
    app = Flask(__name__)

    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(exist_ok=True)

    database_path = os.environ.get("DATABASE_PATH") or str(instance_dir / "polizia.sqlite3")
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    app.config.update(
        SECRET_KEY=_resolve_secret_key(instance_dir),
        DATABASE_PATH=database_path,
        QUESTIONS_PATH=str(BASE_DIR / "data" / "questions.json"),
    )

    qmod.load_questions(app.config["QUESTIONS_PATH"])
    db_module.register_db(app)
    db_module.init_db(app, qmod.get_subjects())

    from . import auth, dashboard, quiz, practice, admin
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(quiz.bp)
    app.register_blueprint(practice.bp)
    app.register_blueprint(admin.bp)

    return app
