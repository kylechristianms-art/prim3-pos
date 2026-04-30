from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from database import db, Ingredient, ProductIngredient, CustomUnit
from app.services.inventory_service import (
    get_all_ingredients, serialize_ingredient, check_product_ingredients,
    get_all_product_statuses, get_ingredient_logs,
    restock_ingredient, adjust_ingredient, log_wastage,
    log_override, get_all_units,
    add_custom_unit, delete_custom_unit,
)

inventory_bp = Blueprint("inventory", __name__)


# ── Page ──────────────────────────────────────────────────────────
@inventory_bp.route("/inventory")
@login_required
def inventory_page():
    if current_user.role not in ["admin", "manager"]:
        from flask import redirect, url_for, flash
        flash("Access denied", "error")
        return redirect(url_for("pos.dashboard"))
    return render_template("inventory.html", current_user=current_user)


# ── Ingredients list ──────────────────────────────────────────────
@inventory_bp.route("/api/ingredients")
@login_required
def get_ingredients():
    return jsonify({
        "success":     True,
        "ingredients": [serialize_ingredient(i) for i in get_all_ingredients()],
        "units":       get_all_units(),
    })


# ── Add ingredient ────────────────────────────────────────────────
@inventory_bp.route("/ingredients/add", methods=["POST"])
@login_required
def add_ingredient():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Name is required"})

    ing = Ingredient(
        name=name,
        unit=data.get("unit", "pieces"),
        quantity=float(data.get("quantity", 0)),
        low_stock_threshold=float(data.get("low_stock_threshold", 10)),
        cost_per_unit=float(data.get("cost_per_unit", 0)),
    )
    db.session.add(ing)
    db.session.commit()
    return jsonify({
        "success":    True,
        "message":    f"'{name}' added.",
        "id":         ing.id,
        "ingredient": serialize_ingredient(ing),
    })


# ── Edit ingredient — FIX: quantity is now updated ────────────────
@inventory_bp.route("/ingredients/edit", methods=["POST"])
@login_required
def edit_ingredient():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    ing  = db.session.get(Ingredient, data.get("id"))
    if not ing:
        return jsonify({"success": False, "error": "Ingredient not found"})

    ing.name                = (data.get("name") or ing.name).strip()
    ing.unit                = data.get("unit", ing.unit)
    # BUG FIX: quantity was silently ignored — now properly updated
    ing.quantity            = float(data.get("quantity", ing.quantity))
    ing.low_stock_threshold = float(data.get("low_stock_threshold", ing.low_stock_threshold))
    ing.cost_per_unit       = float(data.get("cost_per_unit", ing.cost_per_unit))

    db.session.commit()
    return jsonify({
        "success":    True,
        "message":    f"'{ing.name}' updated.",
        "ingredient": serialize_ingredient(ing),
    })


# ── Delete ingredient ─────────────────────────────────────────────
@inventory_bp.route("/ingredients/delete", methods=["POST"])
@login_required
def delete_ingredient():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    data = request.get_json()
    ing  = db.session.get(Ingredient, data.get("id"))
    if not ing:
        return jsonify({"success": False, "error": "Ingredient not found"})

    name = ing.name
    db.session.delete(ing)
    db.session.commit()
    return jsonify({"success": True, "message": f"'{name}' deleted."})


# ── Stock Actions ─────────────────────────────────────────────────
@inventory_bp.route("/ingredients/restock", methods=["POST"])
@login_required
def restock():
    data = request.get_json()
    qty  = float(data.get("quantity", 0))
    if qty <= 0:
        return jsonify({"success": False, "error": "Quantity must be > 0"})
    success = restock_ingredient(
        data.get("ingredient_id"), qty,
        data.get("notes", ""), current_user.id
    )
    return jsonify({"success": success})


@inventory_bp.route("/ingredients/adjust", methods=["POST"])
@login_required
def adjust():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data    = request.get_json()
    new_qty = float(data.get("new_quantity", 0))
    if new_qty < 0:
        return jsonify({"success": False, "error": "Quantity cannot be negative"})
    success = adjust_ingredient(
        data.get("ingredient_id"), new_qty,
        data.get("notes", ""), current_user.id
    )
    return jsonify({"success": success})


@inventory_bp.route("/ingredients/wastage", methods=["POST"])
@login_required
def wastage():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data = request.get_json()
    qty  = float(data.get("quantity", 0))
    if qty <= 0:
        return jsonify({"success": False, "error": "Quantity must be > 0"})
    success = log_wastage(
        data.get("ingredient_id"), qty,
        data.get("notes", ""), current_user.id
    )
    return jsonify({"success": success})


# ── POS Override Log ──────────────────────────────────────────────
@inventory_bp.route("/ingredients/override_log", methods=["POST"])
@login_required
def override_log():
    data = request.get_json()
    log_override(
        data.get("product_id"),
        data.get("product_name", ""),
        data.get("reason", ""),
        current_user.id,
    )
    return jsonify({"success": True})


# ── Activity Logs ─────────────────────────────────────────────────
@inventory_bp.route("/api/inventory/logs")
@login_required
def get_logs():
    ingredient_id = request.args.get("ingredient_id")
    limit         = int(request.args.get("limit", 100))
    return jsonify({"success": True, "logs": get_ingredient_logs(ingredient_id, limit)})


# ── POS: Product ingredient status (single) ───────────────────────
@inventory_bp.route("/products/<int:product_id>/ingredient_status")
@login_required
def ingredient_status(product_id):
    ings       = check_product_ingredients(product_id)
    has_issues = any(i["status"] in ("out", "low") for i in ings)
    return jsonify({
        "success":     True,
        "product_id":  product_id,
        "ingredients": ings,
        "has_issues":  has_issues,
    })


# ── POS: Bulk product ingredient statuses ─────────────────────────
@inventory_bp.route("/api/product_ingredient_statuses")
@login_required
def all_product_statuses():
    return jsonify({"success": True, "statuses": get_all_product_statuses()})


# ── Product ↔ Ingredient Links ────────────────────────────────────
@inventory_bp.route("/products/<int:product_id>/ingredients")
@login_required
def get_product_ingredients(product_id):
    links = ProductIngredient.query.filter_by(product_id=product_id).all()
    return jsonify({
        "success":     True,
        "ingredients": [
            {
                "ingredient_id":   l.ingredient_id,
                "name":            l.ingredient.name,
                "unit":            l.ingredient.unit,
                "quantity_needed": l.quantity_needed,
            }
            for l in links
        ],
    })


@inventory_bp.route("/products/<int:product_id>/ingredients/set", methods=["POST"])
@login_required
def set_product_ingredients(product_id):
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data        = request.get_json()
    ingredients = data.get("ingredients", [])
    ProductIngredient.query.filter_by(product_id=product_id).delete()
    for item in ingredients:
        db.session.add(ProductIngredient(
            product_id=product_id,
            ingredient_id=int(item["ingredient_id"]),
            quantity_needed=float(item["quantity_needed"]),
        ))
    db.session.commit()
    return jsonify({"success": True, "message": "Ingredients updated."})


# ── Custom Units CRUD ─────────────────────────────────────────────
@inventory_bp.route("/api/units")
@login_required
def list_units():
    custom = CustomUnit.query.order_by(CustomUnit.name).all()
    return jsonify({
        "success": True,
        "units":   get_all_units(),
        "custom":  [{"id": u.id, "name": u.name} for u in custom],
    })


@inventory_bp.route("/api/units/add", methods=["POST"])
@login_required
def add_unit():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data          = request.get_json()
    success, msg  = add_custom_unit(data.get("name", ""))
    return jsonify({"success": success, "message": msg, "units": get_all_units()})


@inventory_bp.route("/api/units/delete", methods=["POST"])
@login_required
def delete_unit():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data         = request.get_json()
    success, msg = delete_custom_unit(data.get("id"))
    return jsonify({"success": success, "message": msg, "units": get_all_units()})