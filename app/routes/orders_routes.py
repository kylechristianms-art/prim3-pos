import csv
import io
import json
import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from database import db, Sale, SaleItem, Product, SavedOrder, User
from app.services.order_service import calculate_total, normalize_cart, serialize_order, calculate_cart_with_item_discounts
from app.services.payment_service import calculate_change
from app.services.audit_service import log_action
from app.services.inventory_service import deduct_for_sale

# Philippines Standard Time — UTC+8, no DST
_PH_TZ = timezone(timedelta(hours=8))


# ── ReportLab imports for PDF receipt generation ──────────────────
from reportlab.lib.pagesizes import A7
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

orders_bp = Blueprint("orders", __name__)


# ── Download Receipt as PDF ────────────────────────────────────────
@orders_bp.route("/download_receipt", methods=["POST"])
@login_required
def download_receipt():
    """
    Accepts a JSON payload describing a completed sale or saved order
    and returns a thermal-style PDF receipt as a file download.

    Expected payload fields:
        sale_id, cashier, timestamp, items, subtotal,
        discount_amount, total, payment_method,
        cash_received, change, kitchen_notes (optional)
    """
    try:
        data = request.get_json(force=True) or {}

        sale_id         = data.get("sale_id", "—")
        cashier         = data.get("cashier", "—")
        timestamp       = data.get("timestamp", "")
        items           = data.get("items", [])
        subtotal        = float(data.get("subtotal", 0))
        discount_amount = float(data.get("discount_amount", 0))
        total           = float(data.get("total", 0))
        payment_method  = str(data.get("payment_method", "cash")).upper()
        cash_received   = float(data.get("cash_received", 0))
        change          = float(data.get("change", 0))
        kitchen_notes   = data.get("kitchen_notes", "")

        # ── Build PDF in memory ──────────────────────────────────
        buf = io.BytesIO()

        # Thermal receipt width: 58 mm wide, dynamic height
        page_w = 58 * mm

        # Estimate page height: header ~45mm + per-item ~7mm + footer ~50mm
        page_h = (45 + len(items) * 7 + 50) * mm
        page_h = max(page_h, 120 * mm)

        c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
        c.setTitle(f"Receipt {sale_id}")

        y = page_h - 6 * mm  # cursor starts near top

        def line_sep(dotted=False):
            """Draw a separator line and advance cursor."""
            nonlocal y
            y -= 2 * mm
            if dotted:
                c.setDash(2, 2)
            c.line(4 * mm, y, page_w - 4 * mm, y)
            c.setDash()  # reset dash
            y -= 3 * mm

        def text_row(left, right=None, font="Helvetica", size=7, bold=False):
            """Print a single row; optionally right-aligned value."""
            nonlocal y
            fname = "Helvetica-Bold" if bold else font
            c.setFont(fname, size)
            c.drawString(4 * mm, y, str(left))
            if right is not None:
                c.drawRightString(page_w - 4 * mm, y, str(right))
            y -= 4.5 * mm

        # ── Header ───────────────────────────────────────────────
        logo_path = None
        _static_dirs = [
            current_app.static_folder,
            os.path.join(current_app.root_path, "static"),
            os.path.join(os.path.dirname(current_app.root_path), "static"),
            os.path.join(os.path.dirname(current_app.instance_path), "static"),
        ]
        for _dir in _static_dirs:
            if not _dir:
                continue
            for _fname in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.bmp"):
                _candidate = os.path.join(_dir, _fname)
                if os.path.isfile(_candidate):
                    logo_path = _candidate
                    break
            if logo_path:
                break

        if logo_path:
            logo_w, logo_h = 58 * mm, 20 * mm
            c.drawImage(
                logo_path,
                (page_w - logo_w) / 2, y - logo_h,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True, mask="auto",
            )
            y -= logo_h + 2 * mm

        c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(page_w / 2, y, "Sales Invoice")
        y -= 4 * mm
        c.drawCentredString(page_w / 2, y, timestamp)
        y -= 4 * mm
        c.drawCentredString(page_w / 2, y, f"Sales Invoice: {sale_id}")
        y -= 4 * mm
        c.drawCentredString(page_w / 2, y, f"Cashier: {cashier}")
        y -= 4 * mm

        line_sep(dotted=True)

        # ── Items ─────────────────────────────────────────────────
        c.setFont("Helvetica-Bold", 7)
        c.drawString(4 * mm, y, "ITEM")
        c.drawRightString(page_w - 4 * mm, y, "AMOUNT")
        y -= 5 * mm

        for item in items:
            name     = str(item.get("name", "Item"))
            qty      = int(item.get("qty", 1))
            price    = float(item.get("price", 0))
            discount = float(item.get("discount", 0))
            notes    = str(item.get("notes", "")).strip()

            line_total = price * qty - discount

            # Item name + qty
            c.setFont("Helvetica-Bold", 7)
            c.drawString(4 * mm, y, f"{name}")
            y -= 4 * mm

            # qty × price line
            c.setFont("Helvetica", 6.5)
            qty_line = f"  {qty} x P{price:.2f}"
            if discount > 0:
                qty_line += f"  (disc: -P{discount:.2f})"
            c.drawString(4 * mm, y, qty_line)
            c.drawRightString(page_w - 4 * mm, y, f"P{line_total:.2f}")
            y -= 4.5 * mm

            if notes:
                c.setFont("Helvetica-Oblique", 6)
                c.drawString(6 * mm, y, f"  Note: {notes}")
                y -= 4 * mm

        line_sep(dotted=True)

        # ── Totals ────────────────────────────────────────────────
        text_row(f"Subtotal", f"P{subtotal:.2f}", size=7)
        if discount_amount > 0:
            text_row(f"Discount", f"-P{discount_amount:.2f}", size=7)

        y -= 1 * mm
        line_sep()

        # Grand total – bigger font
        c.setFont("Helvetica-Bold", 9)
        c.drawString(4 * mm, y, "TOTAL")
        c.drawRightString(page_w - 4 * mm, y, f"P{total:.2f}")
        y -= 6 * mm

        line_sep(dotted=True)

        # ── Payment ───────────────────────────────────────────────
        text_row("Payment", payment_method, size=7)
        if payment_method == "CASH":
            text_row("Cash Received", f"P{cash_received:.2f}", size=7)
            text_row("Change", f"P{change:.2f}", size=7, bold=True)

        if kitchen_notes:
            y -= 2 * mm
            line_sep(dotted=True)
            c.setFont("Helvetica-Oblique", 6.5)
            c.drawString(4 * mm, y, f"Notes: {kitchen_notes}")
            y -= 4 * mm

        line_sep(dotted=True)

        # ── Footer ────────────────────────────────────────────────
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(page_w / 2, y, "Thank you for your purchase!")
        y -= 4 * mm
        c.drawCentredString(page_w / 2, y, "Please come again.")

        c.save()
        buf.seek(0)

        filename = f"receipt_{sale_id}.pdf"
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Checkout ──────────────────────────────────────────────────────────
@orders_bp.route("/orders/checkout", methods=["POST"])
@login_required
def checkout():
    try:
        data   = request.get_json()
        cart   = data.get("cart", [])
        if not cart:
            return jsonify({"success": False, "error": "Cart is empty"})

        editing_order_id = data.get("order_id")        # int if editing a SavedOrder, else None
        discount_amount  = float(data.get("discount_amount", 0))
        discount_type    = data.get("discount_type", "")
        payment_method   = data.get("payment_method", "cash")
        cash_received    = float(data.get("cash_received", 0))

        enriched_cart = calculate_cart_with_item_discounts(cart, discount_amount)
        subtotal, total_discount, total = calculate_total(enriched_cart, discount_amount)
        change = calculate_change(total, cash_received, payment_method)

        # ── Create Sale record ────────────────────────────────────────
        sale = Sale(
            total=subtotal,
            discount_amount=total_discount,
            final_total=total,
            payment_method=payment_method,
        )
        db.session.add(sale)
        db.session.flush()          # get sale.id before SavedOrder references it

        for item in enriched_cart:
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

        # ── Create or update the linked SavedOrder (not yet completed) ─
        order_id = None
        if editing_order_id:
            order = db.session.get(SavedOrder, editing_order_id)
            if order and not order.is_completed and not order.is_void:
                order.label           = f"Sale #{sale.id}"
                order.cart_json       = json.dumps(normalize_cart(enriched_cart))
                order.discount_amount = total_discount
                order.payment_method  = payment_method
                order.kitchen_notes   = data.get("kitchen_notes", order.kitchen_notes or "")
                order.order_type      = data.get("order_type", order.order_type or "dine_in")
                try:
                    order.sale_id = sale.id
                except AttributeError:
                    pass
                order_id = order.id
        
        if order_id is None:
            # New sale — create a pending SavedOrder so kitchen prints have an ID
            saved = SavedOrder(
                label=f"Sale #{sale.id}",
                cart_json=json.dumps(normalize_cart(enriched_cart)),
                discount_amount=total_discount,
                payment_method=payment_method,
                kitchen_notes=data.get("kitchen_notes", ""),
                order_type=data.get("order_type", "dine_in"),
                cashier_id=current_user.id,
            )
            try:
                saved.sale_id = sale.id
            except AttributeError:
                pass
            db.session.add(saved)
            db.session.flush()
            order_id = saved.id

        db.session.commit()

        deduct_for_sale(cart, current_user.id)
        log_action(current_user.id, "CHECKOUT", f"Sale #{sale.id} Order #{order_id} total P{total}")

        now = datetime.now(tz=_PH_TZ)
        return jsonify({
            "success":         True,
            "sale_id":         sale.id,
            "order_id":        order_id,     # SavedOrder.id — used by completeSale() / confirmSaveOrder()
            "subtotal":        subtotal,
            "discount_amount": total_discount,
            "discount_type":   discount_type,
            "total":           total,
            "change":          change,
            "cash_received":   cash_received,
            "payment_method":  payment_method,
            "cashier":         current_user.name,
            "timestamp":       now.strftime("%b %d, %Y %I:%M %p"),
            "items":           enriched_cart,
            "kitchen_notes":   data.get("kitchen_notes", ""),
            "order_type":      data.get("order_type", "dine_in"),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})



# ── Cancel a pending checkout (Edit Sale) ─────────────────────────
@orders_bp.route("/orders/checkout/cancel", methods=["POST"])
@login_required
def cancel_checkout():
    """
    Voids a pending (not completed, not voided) Sale + SavedOrder so the
    cashier can go back and edit the cart.  Inventory is NOT restored here;
    void the order from the Orders page if a full reversal is needed.
    """
    data     = request.get_json() or {}
    order_id = data.get("order_id")
    sale_id  = data.get("sale_id")
    try:
        if order_id:
            order = db.session.get(SavedOrder, order_id)
            if order and not order.is_completed and not order.is_void:
                db.session.delete(order)

        if sale_id:
            sale = db.session.get(Sale, sale_id)
            if sale and not getattr(sale, "is_void", False):
                SaleItem.query.filter_by(sale_id=sale.id).delete(synchronize_session=False)
                db.session.delete(sale)

        db.session.commit()
        log_action(current_user.id, "CANCEL_CHECKOUT",
                   f"Cancelled Sale #{sale_id} / Order #{order_id}")
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": True})


# ── Complete direct sale ───────────────────────────────────────────
@orders_bp.route("/orders/complete_sale", methods=["POST"])
@login_required
def complete_sale():
    try:
        data    = request.get_json() or {}
        sale_id = data.get("sale_id")
        if sale_id:
            sale = db.session.get(Sale, sale_id)
            if sale:
                log_action(current_user.id, "COMPLETE_SALE", f"Sale #{sale.id}")
        return jsonify({"success": True})
    except Exception:
        return jsonify({"success": True})


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


# ── List all saved orders ──────────────────────────────────────────
@orders_bp.route("/saved_orders")
@orders_bp.route("/orders/saved")
@login_required
def saved_orders():
    orders = SavedOrder.query.order_by(SavedOrder.created_at.desc()).all()

    # Build a cashier lookup so we don't query the DB per-row
    cashier_ids = {o.cashier_id for o in orders if getattr(o, "cashier_id", None)}
    cashier_map = {}
    if cashier_ids:
        users = User.query.filter(User.id.in_(cashier_ids)).all()
        cashier_map = {u.id: u.name for u in users}

    result = []
    for o in orders:
        s = serialize_order(o)
        cid = getattr(o, "cashier_id", None)

        # Always resolve the full display name from the DB lookup when
        # cashier_id is present — this prevents serialize_order from
        # leaking a username, PIN, or abbreviated code (e.g. "FCG") into
        # both the cashier_name and cashier fields used by print templates.
        if cid:
            resolved_name = cashier_map.get(cid)
            if resolved_name:
                s["cashier_name"] = resolved_name
                s["cashier"]      = resolved_name  # cover both field names
            s["cashier_id"] = cid

        result.append(s)

    return jsonify({"success": True, "orders": result})


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

        # Preserve the real Sale FK when provided (e.g. from confirmSaveOrder after
        # checkout renamed the label to the user's custom label).  Without this,
        # serialize_order() Priority-1 would fall through to the label-parse or the
        # order.id fallback once the label is no longer "Sale #<n>".
        raw_sale_id = data.get("sale_id")
        if raw_sale_id:
            try:
                order.sale_id = int(raw_sale_id)
            except (AttributeError, ValueError, TypeError):
                pass

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
    if not getattr(order, "cashier_id", None):
        order.cashier_id = current_user.id
    db.session.commit()
    log_action(current_user.id, "COMPLETE_ORDER", f"Order #{order.id}")
    return jsonify({"success": True})


# ── [TEST] Full-delete a completed order (SavedOrder + Sale + SaleItems) ──
# Wipes every DB record created by this order so it never appears in
# sales totals, reports, or transaction history.
# Intended for development/testing only. Remove before production.
@orders_bp.route("/orders/saved/delete", methods=["POST"])
@login_required
def delete_order():
    data  = request.get_json() or {}
    order = db.session.get(SavedOrder, data.get("id"))
    if not order:
        return jsonify({"success": False, "error": "Order not found"})
    if not order.is_completed:
        return jsonify({"success": False, "error": "Only completed orders can be deleted this way"})

    deleted_sale_id = None
    order_id_log    = order.id
    order_label_log = order.label

    try:
        # Resolve the linked Sale from the label before touching the session.
        linked_sale = None
        label = (order.label or "").strip()
        if label.lower().startswith("sale #"):
            try:
                linked_sale = db.session.get(Sale, int(label.split("#", 1)[1].strip()))
            except (ValueError, IndexError):
                pass

        # ── Delete SavedOrder FIRST and flush it out of the DB ──────────────
        # SavedOrder.sale_id is a FK → Sale.id.  If we delete Sale first the
        # DB rejects it (FK constraint).  Flushing the SavedOrder delete within
        # the same transaction clears the reference before Sale is removed.
        db.session.delete(order)
        db.session.flush()

        # ── Now safe to remove Sale and its line items ───────────────────────
        if linked_sale:
            SaleItem.query.filter_by(sale_id=linked_sale.id).delete(synchronize_session=False)
            db.session.delete(linked_sale)
            deleted_sale_id = linked_sale.id

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})

    log_action(
        current_user.id,
        "DELETE_ORDER_TEST",
        f"Full-delete completed order #{order_id_log} '{order_label_log}'"
        + (f" + Sale #{deleted_sale_id} + SaleItems" if deleted_sale_id else ""),
    )
    return jsonify({
        "success":          True,
        "deleted_order_id": order_id_log,
        "deleted_sale_id":  deleted_sale_id,
    })


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


# ── Export to CSV then clear completed/voided orders ──────────────
@orders_bp.route("/saved_orders/clear", methods=["POST"])
@login_required
def clear_orders():
    orders_to_clear = SavedOrder.query.filter(
        (SavedOrder.is_completed == True) | (SavedOrder.is_void == True)
    ).all()

    if not orders_to_clear:
        return jsonify({"success": True, "message": "No completed or voided orders to clear.", "deleted": 0})

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
            o.id, o.label,
            f"{subtotal:.2f}", f"{disc:.2f}", f"{total:.2f}",
            o.payment_method or "cash", o.order_type or "dine_in",
            status, o.created_at.strftime("%Y-%m-%d %H:%M"),
            o.void_reason or "", o.void_resolution or "",
        ])

    filename   = f"orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    export_dir = os.path.join(current_app.root_path, "static", "exports")
    os.makedirs(export_dir, exist_ok=True)
    with open(os.path.join(export_dir, filename), "w", newline="", encoding="utf-8") as f:
        f.write(output.getvalue())

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