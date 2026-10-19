import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MAX_PASSWORD_LENGTH = 128
MAX_REACTION_MS = 10_000

app = Flask(__name__, static_folder=None)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", f"sqlite:///{BASE_DIR / 'reactiontime.db'}"
)
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config[
        "SQLALCHEMY_DATABASE_URI"
    ].replace("postgres://", "postgresql+psycopg://", 1)
elif app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config[
        "SQLALCHEMY_DATABASE_URI"
    ].replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "").lower() == "true"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

db = SQLAlchemy(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), nullable=False)
    username_key = db.Column(db.String(20), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)


class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    reaction_ms = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


with app.app_context():
    db.create_all()


@app.before_request
def require_same_origin_for_mutations():
    if request.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        expected_origin = request.host_url.rstrip("/")
        if origin != expected_origin:
            return jsonify(error="This request did not come from this website."), 403
    return None


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return response


@app.errorhandler(RateLimitExceeded)
def rate_limit_exceeded(_error):
    return jsonify(error="Too many attempts. Please wait a bit and try again."), 429


def get_json_body():
    if not request.is_json:
        return None
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def authenticated_user():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    return db.session.get(User, user_id)


def user_response(user):
    return {"id": user.id, "username": user.username}


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.post("/api/register")
@limiter.limit("5 per hour")
def register():
    body = get_json_body()
    if body is None:
        return jsonify(error="Send a JSON username and password."), 400

    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        return jsonify(error="Usernames must be 3-20 letters, numbers, or underscores."), 400
    if not isinstance(password, str) or not 8 <= len(password) <= MAX_PASSWORD_LENGTH:
        return jsonify(error="Passwords must be 8-128 characters long."), 400

    user = User(
        username=username,
        username_key=username.lower(),
        password_hash=generate_password_hash(password, method="scrypt"),
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="That username is already taken."), 409

    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    return jsonify(user=user_response(user)), 201


@app.post("/api/login")
@limiter.limit("10 per minute")
def login():
    body = get_json_body()
    if body is None:
        return jsonify(error="Send a JSON username and password."), 400

    username = body.get("username")
    password = body.get("password")
    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or not 1 <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        return jsonify(error="Username or password is incorrect."), 401

    user = db.session.scalar(
        db.select(User).where(User.username_key == username.lower())
    )
    if user is None or not check_password_hash(user.password_hash, password):
        return jsonify(error="Username or password is incorrect."), 401

    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    return jsonify(user=user_response(user))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    user = authenticated_user()
    return jsonify(user=user_response(user) if user else None)


@app.get("/api/leaderboard")
def leaderboard():
    best_scores = db.session.execute(
        db.select(
            User.username,
            func.min(Score.reaction_ms).label("best_ms"),
        )
        .join(Score, Score.user_id == User.id)
        .group_by(User.id, User.username)
        .order_by(func.min(Score.reaction_ms), User.username_key)
        .limit(10)
    ).all()
    return jsonify(
        scores=[
            {"username": username, "best_ms": best_ms}
            for username, best_ms in best_scores
        ]
    )


@app.route("/api/scores", methods=["GET", "POST"])
def scores():
    user = authenticated_user()
    if user is None:
        return jsonify(error="Log in to view or save your times."), 401

    if request.method == "GET":
        history = db.session.scalars(
            db.select(Score)
            .where(Score.user_id == user.id)
            .order_by(Score.created_at.desc(), Score.id.desc())
            .limit(20)
        ).all()
        return jsonify(
            scores=[
                {"reaction_ms": score.reaction_ms, "created_at": score.created_at.isoformat()}
                for score in history
            ]
        )

    body = get_json_body()
    reaction_ms = body.get("reaction_ms") if body else None
    if (
        isinstance(reaction_ms, bool)
        or not isinstance(reaction_ms, int)
        or not 1 <= reaction_ms <= MAX_REACTION_MS
    ):
        return jsonify(error="Reaction time must be a whole number from 1 to 10000 ms."), 400

    score = Score(user_id=user.id, reaction_ms=reaction_ms)
    db.session.add(score)
    db.session.commit()
    best_ms = db.session.scalar(
        db.select(func.min(Score.reaction_ms)).where(Score.user_id == user.id)
    )
    return jsonify(
        score={"reaction_ms": score.reaction_ms},
        best_ms=best_ms,
    ), 201


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
