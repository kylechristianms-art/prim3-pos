from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash
from database import db, User, AuditLog
from datetime import datetime

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password, password):
            error = "Invalid username or password."
        else:
            login_user(user)
            _log(user.id, "LOGIN", f"{user.username} logged in")
            return redirect(url_for("pos.dashboard"))

    return render_template("login.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    from flask_login import current_user
    _log(current_user.id, "LOGOUT", f"{current_user.username} logged out")
    logout_user()
    return redirect(url_for("auth.login"))


def _log(user_id, action, details):
    try:
        log = AuditLog(user_id=user_id, action=action,
                       details=details, created_at=datetime.utcnow())
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass