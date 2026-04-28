from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from database import db, User
from werkzeug.security import generate_password_hash

users_bp = Blueprint("users", __name__)


@users_bp.route("/users/list")
@login_required
def list_users():
    users = User.query.all()
    return jsonify({
        "success": True,
        "users": [
            {
                "id":      u.id,
                "name":    u.name,
                "username":u.username,
                "role":    u.role,
                "has_pin": u.pin is not None,
            }
            for u in users
        ]
    })


@users_bp.route("/users/add", methods=["POST"])
@login_required
def add_user():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    user = User(
        name=data["name"],
        username=data["username"],
        password=generate_password_hash(data["password"]),
        role=data.get("role", "cashier"),
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"success": True, "message": "User created."})


@users_bp.route("/users/edit", methods=["POST"])
@login_required
def edit_user():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    user = db.session.get(User, data.get("id"))
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    user.name     = data.get("name", user.name)
    user.username = data.get("username", user.username)
    if data.get("password"):
        user.password = generate_password_hash(data["password"])
    if current_user.role == "admin" and data.get("role"):
        user.role = data["role"]

    db.session.commit()
    return jsonify({"success": True, "message": "User updated."})


@users_bp.route("/users/delete", methods=["POST"])
@login_required
def delete_user():
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    user = db.session.get(User, data.get("id"))
    if not user:
        return jsonify({"success": False, "error": "User not found"})
    if user.id == current_user.id:
        return jsonify({"success": False, "error": "Cannot delete yourself"})

    db.session.delete(user)
    db.session.commit()
    return jsonify({"success": True, "message": "User deleted."})


@users_bp.route("/users/set_pin", methods=["POST"])
@login_required
def set_pin():
    data = request.get_json()
    user = db.session.get(User, data.get("user_id"))
    if not user:
        return jsonify({"success": False, "error": "User not found"})
    user.pin = data.get("pin")
    db.session.commit()
    return jsonify({"success": True, "message": "PIN set."})