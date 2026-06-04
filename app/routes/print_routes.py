import os
import win32print
from flask import Blueprint, request, jsonify, make_response, current_app
from flask_login import login_required
from database import db, SavedPrinter
from app.services.print_service import print_receipt_service, print_kitchen_service

print_bp = Blueprint("print", __name__)


# ── Receipt / Kitchen print (old paths kept + new /print/* aliases) ──
@print_bp.route("/print_receipt", methods=["POST"])
@print_bp.route("/print/print_receipt", methods=["POST"])
@login_required
def print_receipt():
    data = request.get_json()
    return jsonify(print_receipt_service(data, data.get("port")))


@print_bp.route("/open_drawer", methods=["POST"])
@print_bp.route("/print/open_drawer", methods=["POST"])
@login_required
def open_drawer():
    data = request.get_json()
    port = data.get("port")
    try:
        # ESC/POS cash drawer pulse: ESC p 0 25 250
        drawer_cmd = b"\x1b\x70\x00\x19\xfa"
        hPrinter = win32print.OpenPrinter(port)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("Cash Drawer", None, "RAW"))
            win32print.StartPagePrinter(hPrinter)
            win32print.WritePrinter(hPrinter, drawer_cmd)
            win32print.EndPagePrinter(hPrinter)
            win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e))


@print_bp.route("/print_kitchen", methods=["POST"])
@print_bp.route("/print/print_kitchen", methods=["POST"])
@login_required
def print_kitchen():
    data = request.get_json()
    return jsonify(print_kitchen_service(data, data.get("port")))


# ── Download receipt as plain-text file ──────────────────────────
@print_bp.route("/download_receipt", methods=["POST"])
@print_bp.route("/print/download_receipt", methods=["POST"])
@login_required
def download_receipt():
    import io
    data = request.get_json()

    lines = [
        f"RECEIPT #{data.get('sale_id', 'N/A')}",
        "=" * 36,
        f"Cashier : {data.get('cashier', 'Unknown')}",
        f"Date    : {data.get('timestamp', '')}",
        "-" * 36,
        "ITEMS:",
    ]

    for item in data.get("items", []):
        qty   = int(item.get("qty", 1))
        price = float(item.get("price", 0))
        disc  = float(item.get("discount", 0))
        total = price * qty - disc
        lines.append(f"  {item.get('name')} x{qty} @ P{price:.2f}  =  P{total:.2f}")
        if disc:
            lines.append(f"    Discount   : -P{disc:.2f}")
        for addon in item.get("addons", []):
            aqty = int(addon.get("qty", 1))
            lines.append(f"    + {addon.get('name')} x{aqty}  P{float(addon.get('price', 0)):.2f}")
        if item.get("notes"):
            lines.append(f"    Note: {item['notes']}")

    lines.append("-" * 36)
    subtotal = float(data.get("subtotal", 0))
    discount = float(data.get("discount_amount", 0))
    total    = float(data.get("total", 0))

    if discount:
        lines.append(f"Subtotal : P{subtotal:.2f}")
        lines.append(f"Discount : -P{discount:.2f}")

    lines.append(f"TOTAL    : P{total:.2f}")
    lines.append(f"Payment  : {data.get('payment_method', 'cash').upper()}")

    if str(data.get("payment_method", "")).lower() == "cash":
        lines.append(f"Cash     : P{float(data.get('cash_received', 0)):.2f}")
        lines.append(f"Change   : P{float(data.get('change', 0)):.2f}")

    lines += ["=" * 36, "Thank you for your purchase!", "Powered by prim3-POS"]

    content  = "\n".join(lines)
    buf      = io.BytesIO(content.encode("utf-8"))
    sale_id  = data.get("sale_id", "unknown")

    response = make_response(buf.getvalue())
    response.headers["Content-Type"]        = "text/plain; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename=receipt_{sale_id}.txt"
    return response


# ── Saved Printers CRUD ───────────────────────────────────────────
@print_bp.route("/print/printers")
@login_required
def list_printers():
    printers = SavedPrinter.query.all()
    return jsonify({
        "printers": [
            {
                "id":           p.id,
                "name":         p.name,
                "port":         p.port,
                "printer_type": p.printer_type,
            }
            for p in printers
        ]
    })


@print_bp.route("/print/printers/add", methods=["POST"])
@login_required
def add_printer():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    port = (data.get("port") or "").strip()
    if not name or not port:
        return jsonify({"success": False, "error": "Name and printer port are required"})
    printer = SavedPrinter(
        name=name,
        port=port,
        printer_type=data.get("printer_type", "receipt"),
    )
    db.session.add(printer)
    db.session.commit()
    return jsonify({"success": True, "message": f"Printer '{name}' saved.", "id": printer.id})


@print_bp.route("/print/printers/delete", methods=["POST"])
@login_required
def delete_printer():
    data    = request.get_json()
    printer = db.session.get(SavedPrinter, data.get("id"))
    if not printer:
        return jsonify({"success": False, "error": "Printer not found"})
    db.session.delete(printer)
    db.session.commit()
    return jsonify({"success": True, "message": "Printer removed."})


# ── Available system printers (Windows) / empty list elsewhere ────
@print_bp.route("/print/ports")
@login_required
def list_ports():
    from app.services.receipt_printer import get_available_printers
    printers = get_available_printers()
    return jsonify({"ports": printers})