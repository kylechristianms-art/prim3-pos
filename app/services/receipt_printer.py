from database import db, ReceiptCounter

# ── Optional win32print — Windows only ───────────────────────────
try:
    import win32print
    _WIN32 = True
except ImportError:
    _WIN32 = False


# ── Public helper used by print_routes.py ─────────────────────────
def get_available_printers():
    """Return list of system printers. Empty list on non-Windows."""
    if not _WIN32:
        return []
    try:
        raw = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )
        return [{"port": p[2], "name": p[2]} for p in raw]
    except Exception:
        return []


def get_next_receipt_number():
    counter = ReceiptCounter.query.first()
    if not counter:
        counter = ReceiptCounter(current_number=1)
        db.session.add(counter)
        db.session.commit()
    number = counter.current_number
    counter.current_number += 1
    db.session.commit()
    return number


# ── Low-level send ────────────────────────────────────────────────
def _send(printer_name: str, data: bytes):
    if not _WIN32:
        raise RuntimeError(
            "Thermal printing requires Windows and the pywin32 package. "
            "Use 'Save PDF' instead on this machine."
        )
    h = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(h, 1, ("Receipt", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


# ── Receipt text builder ──────────────────────────────────────────
def _build_receipt_text(data: dict) -> str:
    lines = [
        f"SALE #{data.get('sale_id', 'N/A')}",
        "=" * 32,
        f"Cashier : {data.get('cashier', '')}",
        f"Date    : {data.get('timestamp', '')}",
        "-" * 32,
    ]

    for item in data.get("items", []):
        qty   = int(item.get("qty", 1))
        price = float(item.get("price", 0))
        disc  = float(item.get("discount", 0))
        total = price * qty - disc
        lines.append(f"{item.get('name')} x{qty}  P{total:.2f}")
        for addon in item.get("addons", []):
            aqty = int(addon.get("qty", 1))
            lines.append(f"  + {addon.get('name')} x{aqty}  P{float(addon.get('price', 0)):.2f}")
        if item.get("notes"):
            lines.append(f"  Note: {item['notes']}")

    lines.append("-" * 32)

    disc_amt = float(data.get("discount_amount", 0))
    if disc_amt:
        lines.append(f"Subtotal: P{float(data.get('subtotal', 0)):.2f}")
        lines.append(f"Discount: -P{disc_amt:.2f}")

    lines.append(f"TOTAL   : P{float(data.get('total', 0)):.2f}")
    lines.append(f"Payment : {data.get('payment_method', '').upper()}")

    if str(data.get("payment_method", "")).lower() == "cash":
        lines.append(f"Cash    : P{float(data.get('cash_received', 0)):.2f}")
        lines.append(f"Change  : P{float(data.get('change', 0)):.2f}")

    lines += ["=" * 32, "Thank you!", "\n\n\n"]
    return "\n".join(lines)


# ── Public print functions ────────────────────────────────────────
def print_receipt(data: dict, printer: str):
    try:
        text = _build_receipt_text(data)
        _send(printer, text.encode("utf-8"))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def print_kitchen(data: dict, printer: str):
    try:
        lines = [
            "*** KITCHEN ORDER ***",
            f"Order : {data.get('sale_id', 'N/A')}",
            f"Date  : {data.get('timestamp', '')}",
            "-" * 32,
        ]
        for item in data.get("items", []):
            qty = int(item.get("qty", 1))
            lines.append(f"{item.get('name')} x{qty}")
            for addon in item.get("addons", []):
                aqty = int(addon.get("qty", 1))
                lines.append(f"  + {addon.get('name')} x{aqty}")
            if item.get("notes"):
                lines.append(f"  NOTE: {item['notes']}")
        if data.get("kitchen_notes"):
            lines += ["-" * 32, f"NOTES: {data['kitchen_notes']}"]
        lines += ["=" * 32, "\n\n\n"]
        _send(printer, "\n".join(lines).encode("utf-8"))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}