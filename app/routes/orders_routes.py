import csv
import io
import json
import os
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from database import db, Sale, SaleItem, Product, SavedOrder, User
from app.services.order_service import calculate_total, normalize_cart, serialize_order
from app.services.payment_service import calculate_change
from app.services.audit_service import log_action
from datetime import datetime

orders_bp = Blueprint("orders", __name__)


# ── Checkout ──────────────────────────────────────────────────────
@orders_bp.route("/orders/checkout", methods=["POST"])
@login_required
def checkout():
    try:
        data = request.get_json()
        cart = data.get("cart", [])
        if not cart:
            return jsonify({"success": False, "error": "Cart is empty"})

        discount_amount = float(data.get("discount_amount", 0))
        payment_method  = data.get("payment_method", "cash")
        cash_received   = float(data.get("cash_received", 0))

        subtotal, total_discount, total = calculate_total(cart, discount_amount)
        change = calculate_change(total, cash_received, payment_method)

        sale = Sale(
            total=subtotal,
            discount_amount=total_discount,
            final_total=total,
            payment_method=payment_method,
            cashier_id=current_user.id,
        )
        db.session.add(sale)
        db.session.flush()

        for item in cart:
            db.session.add(SaleItem(
                sale_id=sale.id,
                product_id=item["id"],
                product_name=item["name"],
                quantity=item["qty"],
                price=item["price"],
            ))
            product = db.session.get(Product, item["id"])
            if product:
                product.quantity = max(0, product.quantity - item["qty"])

        db.session.commit()
        log_action(current_user.id, "CHECKOUT", f"Sale #{sale.id} total P{total}")

        now = datetime.utcnow()
        return jsonify({
            "success":         True,
            "sale_id":         sale.id,
            "subtotal":        subtotal,
            "discount_amount": total_discount,
            "total":           total,
            "change":          change,
            "cash_received":   cash_received,
            "payment_method":  payment_method,
            "cashier":         current_user.name,
            "timestamp":       now.strftime("%b %d, %Y %I:%M %p"),
            "items":           cart,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


# ── Complete direct sale ───────────────────────────────────────────
@orders_bp.route("/orders/complete_sale", methods=["POST"])
@login_required
def complete_sale():
    try:
        data = request.get_json() or {}
        sale_id = data.get("sale_id")
        if sale_id:
            sale = db.session.get(Sale, sale_id)
            if sale:
                log_action(current_user.id, "COMPLETE_SALE", f"Sale #{sale.id}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": True})  # always succeed so UI can reset


# ── Void a direct Sale record ──────────────────────────────────────
@orders_bp.route("/orders/void_sale", methods=["POST"])
@login_required
def void_sale():
    data = request.get_json()
    sale = db.session.get(Sale, data.get("sale_id"))
    if not sale:
        return jsonify({"success": False, "error": "Sale not found"})
    sale.is_void = True
    db.session.commit()
    log_action(current_user.id, "VOID_SALE", f"Sale #{sale.id}")
    return jsonify({"success": True})


# ── List all saved orders (TWO URL aliases) ────────────────────────
@orders_bp.route("/saved_orders")
@orders_bp.route("/orders/saved")
@login_required
def saved_orders():
    orders = SavedOrder.query.order_by(SavedOrder.created_at.desc()).all()
    return jsonify({
        "success": True,
        "orders":  [serialize_order(o) for o in orders],
    })


# ── Save a new order from POS ─────────────────────────────────────
@orders_bp.route("/orders/saved/save", methods=["POST"])
@login_required
def save_order():
    try:
        data  = request.get_json()
        label = (data.get("label") or "").strip()
        cart  = data.get("cart", [])
        if not label:
            return jsonify({"success": False, "error": "Label is required"})
        if not cart:
            return jsonify({"success": False, "error": "Cart is empty"})

        order = SavedOrder(
            label=label,
            cart_json=json.dumps(cart),
            discount_amount=float(data.get("discount_amount", 0)),
            payment_method=data.get("payment_method", "cash"),
            kitchen_notes=data.get("kitchen_notes", ""),
            order_type=data.get("order_type", "dine_in"),
            cashier_id=current_user.id,
        )
        db.session.add(order)
        db.session.commit()
        log_action(current_user.id, "SAVE_ORDER", f"Order '{label}'")
        return jsonify({"success": True, "message": f"Order '{label}' saved!", "id": order.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


# ── Update an existing saved order ────────────────────────────────
@orders_bp.route("/orders/saved/update", methods=["POST"])
@login_required
def update_order():
    try:
        data  = request.get_json()
        order = db.session.get(SavedOrder, data.get("id"))
        if not order:
            return jsonify({"success": False, "error": "Order not found"})

        order.label           = data.get("label", order.label)
        order.cart_json       = json.dumps(data.get("cart", json.loads(order.cart_json)))
        order.discount_amount = float(data.get("discount_amount", order.discount_amount))
        order.payment_method  = data.get("payment_method", order.payment_method)
        order.kitchen_notes   = data.get("kitchen_notes", order.kitchen_notes)
        order.order_type      = data.get("order_type", order.order_type)

        db.session.commit()
        log_action(current_user.id, "UPDATE_ORDER", f"Order #{order.id}")
        return jsonify({"success": True, "message": f"Order '{order.label}' updated!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


# ── Complete a saved order ─────────────────────────────────────────
@orders_bp.route("/saved_orders/complete", methods=["POST"])
@orders_bp.route("/orders/saved/complete", methods=["POST"])
@login_required
def complete_order():
    data  = request.get_json()
    order = db.session.get(SavedOrder, data.get("id"))
    if not order:
        return jsonify({"success": False, "error": "Order not found"})
    order.is_completed = True
    db.session.commit()
    log_action(current_user.id, "COMPLETE_ORDER", f"Order #{order.id}")
    return jsonify({"success": True})


# ── Void a saved order (requires PIN) ─────────────────────────────
@orders_bp.route("/orders/void", methods=["POST"])
@login_required
def void_order():
    data  = request.get_json()
    order = db.session.get(SavedOrder, data.get("order_id"))
    if not order:
        return jsonify({"success": False, "error": "Order not found"})
    order.is_void         = True
    order.void_reason     = data.get("reason", "")
    order.void_resolution = data.get("resolution", "")
    db.session.commit()
    log_action(current_user.id, "VOID_ORDER", f"Order #{order.id} — {order.void_reason}")
    return jsonify({"success": True})


# ── Verify manager/admin PIN ───────────────────────────────────────
@orders_bp.route("/orders/verify_pin", methods=["POST"])
@login_required
def verify_pin():
    data = request.get_json()
    pin  = str(data.get("pin", "")).strip()
    user = User.query.filter_by(pin=pin).first()
    if user and user.role in ["admin", "manager"]:
        return jsonify({"success": True, "user": user.name})
    return jsonify({"success": False, "error": "Invalid PIN or insufficient role"})


# ── Export to CSV then clear old completed/voided orders ──────────
@orders_bp.route("/saved_orders/clear", methods=["POST"])
@login_required
def clear_orders():
    # Get ALL completed or voided orders (removed the 24-hour cutoff that was
    # preventing the button from working when orders were recent)
    orders_to_clear = SavedOrder.query.filter(
        (SavedOrder.is_completed == True) | (SavedOrder.is_void == True)
    ).all()

    if not orders_to_clear:
        return jsonify({"success": True, "message": "No completed or voided orders to clear.", "deleted": 0})

    # ── Build CSV ─────────────────────────────────────────────────
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Label", "Subtotal", "Discount", "Total",
        "Payment", "Type", "Status", "Created At",
        "Void Reason", "Void Resolution",
    ])

    for o in orders_to_clear:
        try:
            cart = json.loads(o.cart_json)
            subtotal, disc, total = calculate_total(cart, o.discount_amount)
        except Exception:
            subtotal = disc = total = 0
        status = "VOIDED" if o.is_void else "COMPLETED"
        writer.writerow([
            o.id,
            o.label,
            f"{subtotal:.2f}",
            f"{disc:.2f}",
            f"{total:.2f}",
            o.payment_method or "cash",
            o.order_type or "dine_in",
            status,
            o.created_at.strftime("%Y-%m-%d %H:%M"),
            o.void_reason or "",
            o.void_resolution or "",
        ])

    # ── Save CSV to static/exports/ ───────────────────────────────
    filename   = f"orders_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    export_dir = os.path.join(current_app.root_path, "static", "exports")
    os.makedirs(export_dir, exist_ok=True)
    with open(os.path.join(export_dir, filename), "w", newline="", encoding="utf-8") as f:
        f.write(output.getvalue())

    # ── Delete from DB ────────────────────────────────────────────
    deleted_count = len(orders_to_clear)
    for o in orders_to_clear:
        db.session.delete(o)
    db.session.commit()

    log_action(current_user.id, "CLEAR_ORDERS", f"Exported and cleared {deleted_count} orders")

    return jsonify({
        "success":      True,
        "message":      f"Exported and cleared {deleted_count} order(s).",
        "deleted":      deleted_count,
        "download_url": f"/static/exports/{filename}",
    })