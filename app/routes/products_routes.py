import os
from flask import Blueprint, request, jsonify, current_app, send_file, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from database import db, Product, Category, Addon
from app.services.product_service import get_low_stock

products_bp = Blueprint("products", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Product Photo ─────────────────────────────────────────────────
@products_bp.route("/products/<int:product_id>/photo")
@login_required
def product_photo(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.photo:
        abort(404)
    photo_path = os.path.abspath(
        os.path.join(current_app.root_path, "static", "product_photos", product.photo)
    )
    if not os.path.exists(photo_path):
        abort(404)
    return send_file(photo_path)


# ── Products ──────────────────────────────────────────────────────
@products_bp.route("/api/products")
@login_required
def get_products():
    products = Product.query.all()
    return jsonify({
        "products": [
            {"id": p.id, "name": p.name, "price": p.price, "quantity": p.quantity}
            for p in products
        ]
    })


@products_bp.route("/api/products/low_stock")
@login_required
def low_stock():
    return jsonify({"products": get_low_stock()})


@products_bp.route("/products/add", methods=["POST"])
@login_required
def add_product():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"success": False, "error": "Name is required"})
    product = Product(
        name=data["name"].strip(),
        price=float(data.get("price", 0)),
        quantity=int(data.get("quantity", 0)),
        category_id=int(data["category_id"]) if data.get("category_id") else None,
    )
    db.session.add(product)
    db.session.commit()
    return jsonify({"success": True, "message": f"Product '{product.name}' added."})


@products_bp.route("/products/edit", methods=["POST"])
@login_required
def edit_product():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    # ── Multipart (photo upload) ──────────────────────────────────
    if request.content_type and "multipart/form-data" in request.content_type:
        pid = request.form.get("id")
        product = db.session.get(Product, int(pid)) if pid else None
        if not product:
            return jsonify({"success": False, "error": "Product not found"})

        product.name     = request.form.get("name", product.name).strip()
        product.price    = float(request.form.get("price", product.price))
        product.quantity = int(request.form.get("quantity", product.quantity))
        cat_id = request.form.get("category_id")
        product.category_id = int(cat_id) if cat_id else None

        photo = request.files.get("photo")
        if photo and photo.filename and allowed_file(photo.filename):
            filename     = secure_filename(f"product_{product.id}_{photo.filename}")
            upload_folder = os.path.abspath(
                os.path.join(current_app.root_path, "static", "product_photos")
            )
            os.makedirs(upload_folder, exist_ok=True)
            photo.save(os.path.join(upload_folder, filename))
            product.photo = filename

        db.session.commit()
        return jsonify({"success": True, "message": f"Product '{product.name}' updated."})

    # ── JSON (no photo) ───────────────────────────────────────────
    data = request.get_json()
    product = db.session.get(Product, data.get("id"))
    if not product:
        return jsonify({"success": False, "error": "Product not found"})

    product.name     = data.get("name", product.name).strip()
    product.price    = float(data.get("price", product.price))
    product.quantity = int(data.get("quantity", product.quantity))
    cat_id = data.get("category_id")
    product.category_id = int(cat_id) if cat_id else None

    if data.get("remove_photo"):
        product.photo = None

    db.session.commit()
    return jsonify({"success": True, "message": f"Product '{product.name}' updated."})


@products_bp.route("/products/delete", methods=["POST"])
@login_required
def delete_product():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data    = request.get_json()
    product = db.session.get(Product, data.get("id"))
    if not product:
        return jsonify({"success": False, "error": "Product not found"})
    name = product.name
    db.session.delete(product)
    db.session.commit()
    return jsonify({"success": True, "message": f"Product '{name}' deleted."})


@products_bp.route("/products/void", methods=["POST"])
@login_required
def void_product():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data    = request.get_json()
    product = db.session.get(Product, data.get("id"))
    if not product:
        return jsonify({"success": False, "error": "Product not found"})
    product.quantity = 0
    db.session.commit()
    return jsonify({"success": True, "message": f"Product '{product.name}' voided — stock set to 0."})


# ── Categories ────────────────────────────────────────────────────
@products_bp.route("/categories")
@login_required
def get_categories():
    categories = Category.query.all()
    return jsonify({
        "success": True,
        "categories": [
            {"id": c.id, "name": c.name, "color": c.color, "parent_id": c.parent_id}
            for c in categories
        ],
    })


@products_bp.route("/categories/add", methods=["POST"])
@login_required
def add_category():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Name is required"})
    cat = Category(
        name=name,
        color=data.get("color", "#f5c518"),
        parent_id=int(data["parent_id"]) if data.get("parent_id") else None,
    )
    db.session.add(cat)
    db.session.commit()
    return jsonify({"success": True, "message": f"Category '{name}' added.", "id": cat.id})


@products_bp.route("/categories/delete", methods=["POST"])
@login_required
def delete_category():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data = request.get_json()
    cat  = db.session.get(Category, data.get("id"))
    if not cat:
        return jsonify({"success": False, "error": "Category not found"})
    # Promote sub-categories to top-level
    Category.query.filter_by(parent_id=cat.id).update({"parent_id": None})
    # Uncategorize affected products
    Product.query.filter_by(category_id=cat.id).update({"category_id": None})
    db.session.delete(cat)
    db.session.commit()
    return jsonify({"success": True, "message": "Category deleted."})


# ── Add-Ons ───────────────────────────────────────────────────────
# Both URLs resolve to the same handler so pos.html and products.html both work
@products_bp.route("/get_addons")
@products_bp.route("/products/addons")
@login_required
def get_addons():
    addons = Addon.query.all()
    return jsonify({
        "addons": [
            {"id": a.id, "name": a.name, "price": a.price, "category_id": a.category_id}
            for a in addons
        ]
    })


@products_bp.route("/addons/add", methods=["POST"])
@login_required
def add_addon():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Name is required"})
    addon = Addon(
        name=name,
        price=float(data.get("price", 0)),
        category_id=int(data["category_id"]) if data.get("category_id") else None,
    )
    db.session.add(addon)
    db.session.commit()
    return jsonify({"success": True, "message": f"Add-on '{name}' added.", "id": addon.id})


@products_bp.route("/addons/delete", methods=["POST"])
@login_required
def delete_addon():
    if current_user.role not in ["admin", "manager"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    data  = request.get_json()
    addon = db.session.get(Addon, data.get("id"))
    if not addon:
        return jsonify({"success": False, "error": "Add-on not found"})
    name = addon.name
    db.session.delete(addon)
    db.session.commit()
    return jsonify({"success": True, "message": f"Add-on '{name}' deleted."})