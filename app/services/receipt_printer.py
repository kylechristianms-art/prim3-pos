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


# ── Shared word-wrap utility ──────────────────────────────────────
def _word_wrap(text: str, width: int, indent: int = 0) -> list[str]:
    """
    Wrap `text` to `width` characters, breaking only on word boundaries.
    The first line uses `width` chars; continuation lines are indented
    by `indent` spaces and use `width - indent` chars.
    Returns a list of lines (no trailing newline on each).
    """
    words = text.split()
    if not words:
        return [""]

    lines = []
    current = ""
    first_line = True

    for word in words:
        avail = width if first_line else width - indent
        prefix = "" if first_line else " " * indent

        if not current:
            # Start of a new line — if the single word is longer than
            # the available width, force-break it (last resort).
            if len(word) > avail:
                while len(word) > avail:
                    lines.append(prefix + word[:avail])
                    word = word[avail:]
                    first_line = False
                    prefix = " " * indent
                    avail = width - indent
                current = word
            else:
                current = word
        else:
            test = current + " " + word
            if len(test) <= avail:
                current = test
            else:
                lines.append(("" if first_line else " " * indent) + current)
                first_line = False
                # Start fresh continuation line; same word-too-long guard
                avail = width - indent
                prefix = " " * indent
                if len(word) > avail:
                    while len(word) > avail:
                        lines.append(prefix + word[:avail])
                        word = word[avail:]
                    current = word
                else:
                    current = word

    if current:
        lines.append(("" if first_line else " " * indent) + current)

    return lines


def _build_receipt_text(data: dict) -> bytes:
    W = 32  # 58mm thermal = 31 chars

    # ── ESC/POS commands ───────────────────────────────────────────
    ESC          = "\x1b"
    GS           = "\x1d"
    BOLD_ON      = ESC + "\x45\x01"
    BOLD_OFF     = ESC + "\x45\x00"
    WIDE_ON      = ESC + "\x21\x30"
    WIDE_OFF     = ESC + "\x21\x00"
    ALIGN_LEFT   = ESC + "\x61\x00"
    ALIGN_CENTER = ESC + "\x61\x01"
    FEED_AND_CUT = GS  + "\x56\x41\x50"

    # ── Column widths: ITEM=20 | QTY=3 | PRICE=8 → sum=31 ─────────
    COL_ITEM  = 20
    COL_QTY   = 3
    COL_PRICE = W - COL_ITEM - COL_QTY  # = 8

    def word_wrap_center(text):
        words = text.split()
        lines_out, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            if len(test) <= W:
                current = test
            else:
                if current:
                    lines_out.append(current.center(W))
                current = word
        if current:
            lines_out.append(current.center(W))
        return "\n".join(lines_out)

    def divider(char="-"):
        return char * W

    def rjust_row(label, value):
        max_lw = W - len(value)
        return f"{label[:max_lw]:<{max_lw}}{value}"

    def item_row(name, qty, price_str, indent=0):
        """
        Render an item row with proper word-wrapping.
        First line: name (COL_ITEM chars) | qty (COL_QTY) | price (COL_PRICE)
        Continuation lines: indented name overflow only.
        """
        avail_name = COL_ITEM - indent
        prefix     = " " * indent

        # Word-wrap the name into avail_name-wide chunks
        name_lines = _word_wrap(name, avail_name)

        out_lines = []
        for idx, chunk in enumerate(name_lines):
            if idx == 0:
                name_col  = f"{prefix}{chunk:<{avail_name}}"
                qty_col   = f"{qty:^{COL_QTY}}"
                price_col = f"{price_str:>{COL_PRICE}}"
                out_lines.append(name_col + qty_col + price_col)
            else:
                # Continuation: pad full COL_ITEM + COL_QTY + COL_PRICE to keep alignment
                out_lines.append(f"{prefix}{chunk}")
        return "\n".join(out_lines)

    # ── Logo (ESC/POS raster bit-image) ───────────────────────────
    def _logo_bytes() -> bytes:
        import os
        logo_path = os.path.join(
            os.path.dirname(__file__),
            "..", "static", "logo.bmp"
        )
        logo_path = os.path.normpath(logo_path)
        if not os.path.exists(logo_path):
            return b""
        try:
            from PIL import Image
            img = Image.open(logo_path).convert("1")
            img_width, img_height = img.size
            row_bytes = (img_width + 7) // 8
            header = (
                b"\x1d\x76\x30\x00"
                + bytes([row_bytes & 0xFF, (row_bytes >> 8) & 0xFF])
                + bytes([img_height & 0xFF, (img_height >> 8) & 0xFF])
            )
            pixels = img.load()
            raster = bytearray()
            for y in range(img_height):
                for byte_x in range(row_bytes):
                    byte = 0
                    for bit in range(8):
                        x = byte_x * 8 + bit
                        if x < img_width:
                            if pixels[x, y] == 0:
                                byte |= (0x80 >> bit)
                    raster.append(byte)
            return header + bytes(raster)
        except Exception:
            return b""

    # ── Build receipt as bytes ─────────────────────────────────────
    parts = []

    def t(text):
        parts.append(text.encode("utf-8"))

    def b(raw_bytes):
        parts.append(raw_bytes)

    # ── Header ────────────────────────────────────────────────────
    logo_data = _logo_bytes()
    if logo_data:
        b(ALIGN_CENTER.encode("utf-8"))
        b(logo_data)
        t("\n")
    else:
        t(ALIGN_CENTER + "[LOGO]\n")

    t(ALIGN_CENTER)
    t(BOLD_ON)
    t("SALES INVOICE")
    t(BOLD_OFF)
    t("\n\n")

    t(ALIGN_LEFT + divider("=") + "\n")
    t(f"Sale    : #{data.get('sale_id', 'N/A')}\n")
    t(f"Cashier : {data.get('cashier', '')}\n")
    t(f"Date    : {data.get('timestamp', '')}\n")
    t(divider() + "\n")

    # ── Column headers ─────────────────────────────────────────────
    item_h  = f"{'ITEM':^{COL_ITEM}}"
    qty_h   = f"{'QTY':^{COL_QTY}}"
    price_h = f"{'PRICE':>{COL_PRICE}}"
    t(item_h + qty_h + price_h + "\n")
    t(divider() + "\n")

    # ── Items ──────────────────────────────────────────────────────
    for item in data.get("items", []):
        name  = item.get("name", "")
        qty   = int(item.get("qty", 1))
        price = float(item.get("price", 0))

        item_disc = float(
            item.get("discount") or
            item.get("discount_amount") or
            item.get("item_discount") or
            0
        )

        t(item_row(name, qty, f"P{price:.2f}") + "\n")

        for addon in item.get("addons", []):
            aname  = f"+ {addon.get('name', '')}"
            aqty   = int(addon.get("qty", 1))
            aprice = float(addon.get("price", 0))
            t(item_row(aname, aqty, f"P{aprice:.2f}", indent=2) + "\n")

        if item_disc > 0:
            disc_label = (
                item.get("discount_type") or
                item.get("discount_label") or
                data.get("discount_type") or
                "Discount"
            )
            t(rjust_row(f"  {disc_label}:", f"-P{item_disc:.2f}") + "\n")

        if item.get("notes"):
            # Word-wrap notes too, indented by 2
            note_text = f"Note: {item['notes']}"
            for line in _word_wrap(note_text, W - 2):
                t("  " + line + "\n")

    t(divider() + "\n")

    # ── Totals ─────────────────────────────────────────────────────
    order_disc = float(data.get("discount_amount") or 0)
    order_disc_label = (
        data.get("discount_type") or
        data.get("discount_label") or
        "Discount"
    )

    if order_disc > 0:
        subtotal = float(data.get("subtotal") or 0)
        t(rjust_row("Subtotal:", f"P{subtotal:.2f}") + "\n")
        t(rjust_row(f"{order_disc_label}:", f"-P{order_disc:.2f}") + "\n")

    total = float(data.get("total") or 0)
    t(BOLD_ON + rjust_row("TOTAL:", f"P{total:.2f}") + BOLD_OFF + "\n")
    t(divider() + "\n")

    # ── Payment ────────────────────────────────────────────────────
    method = data.get("payment_method", "").upper()
    t(rjust_row("Payment:", method) + "\n")

    if str(data.get("payment_method", "")).lower() == "cash":
        cash   = float(data.get("cash_received") or 0)
        change = float(data.get("change") or 0)
        t(rjust_row("Cash:", f"P{cash:.2f}") + "\n")
        t(rjust_row("Change:", f"P{change:.2f}") + "\n")

    # ── Footer ─────────────────────────────────────────────────────
    t(divider("=") + "\n")
    t(ALIGN_CENTER + "\n")
    t(word_wrap_center("Thank you for your purchase!") + "\n")
    t(word_wrap_center("Please keep this receipt for your records.") + "\n")
    t(word_wrap_center("Receipts over P100.00 can redeem a loyalty card.") + "\n")
    t(divider() + "\n")
    t(word_wrap_center("Powered by Prim3 Technologies") + "\n")
    t(ALIGN_LEFT + "\n")

    # ── Feed & cut ─────────────────────────────────────────────────
    t("\n" * 6)
    b(FEED_AND_CUT.encode("utf-8"))

    return b"".join(parts)


# ── Public print functions ────────────────────────────────────────
def print_receipt(data: dict, printer: str):
    try:
        raw = _build_receipt_text(data)
        _send(printer, raw)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def print_kitchen(data: dict, printer: str):
    try:
        W = 32

        ESC           = "\x1b"
        GS            = "\x1d"
        BOLD_ON       = ESC + "\x45\x01"
        BOLD_OFF      = ESC + "\x45\x00"
        ALIGN_LEFT    = ESC + "\x61\x00"
        ALIGN_CENTER  = ESC + "\x61\x01"

        # Bold + double-height (0x08 + 0x10 = 0x18)
        ITEM_ON  = ESC + "\x21\x18"
        ITEM_OFF = ESC + "\x21\x00"

        COL_ITEM = 24
        COL_QTY  = W - COL_ITEM  # = 8

        def divider(char="-"):
            return char * W

        parts = []
        def t(text):
            parts.append(text.encode("utf-8"))
        def b(raw_bytes):
            parts.append(raw_bytes)

        import re
        def sort_key(item):
            name = item.get("name", "")
            cleaned = re.sub(r"^\d+\s*oz\s*[-–]?\s*", "", name, flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"^(XL|[SML])\s+", "", cleaned, flags=re.IGNORECASE).strip()
            return cleaned.lower()

        order_notes = str(data.get("kitchen_notes") or "").strip()

        # ── Header ────────────────────────────────────────────────
        t(ALIGN_CENTER)
        t(BOLD_ON + "*** KITCHEN ORDER ***" + BOLD_OFF + "\n")
        t("\n")
        t(ALIGN_LEFT)
        t(f"Cashier: {data.get('cashier', '')}\n")
        t(f"Order  : #{data.get('sale_id', 'N/A')}\n")
        t(f"Date   : {data.get('timestamp', '')}\n")
        t(divider() + "\n")

        # ── Column Headers ────────────────────────────────────────
        t(BOLD_ON + "ITEM".center(COL_ITEM) + "QTY".center(COL_QTY) + "\n" + BOLD_OFF)
        t(divider() + "\n")

        # ── Items (sorted) ────────────────────────────────────────
        sorted_items = sorted(data.get("items", []), key=sort_key)

        for item in sorted_items:
            name = item.get("name", "")
            qty  = int(item.get("qty", 1))

            # Word-wrap name to COL_ITEM width
            name_lines = _word_wrap(name, COL_ITEM)

            for idx, chunk in enumerate(name_lines):
                if idx == 0:
                    qty_str = ("x" + str(qty)).center(COL_QTY)
                    t(ITEM_ON + f"{chunk:<{COL_ITEM}}{qty_str}" + ITEM_OFF + "\n")
                else:
                    # Continuation lines: pad to full width so printer doesn't mis-align
                    t(ITEM_ON + f"{chunk:<{COL_ITEM}}{' ' * COL_QTY}" + ITEM_OFF + "\n")

            # Per-item note — immediately under item; word-wrap indented
            if item.get("notes"):
                note_text = f"NOTE: {item['notes']}"
                for line in _word_wrap(note_text, W - 2):
                    t("  " + line + "\n")

            # Add-ons — immediately under note; word-wrap indented by 4
            for addon in item.get("addons", []):
                aname = f"+ {addon.get('name', '')}"
                aqty  = int(addon.get("qty", 1))
                addon_avail = COL_ITEM - 4  # 4-char indent: "  + "
                addon_lines = _word_wrap(aname, addon_avail)
                for idx, chunk in enumerate(addon_lines):
                    if idx == 0:
                        aqty_str = ("x" + str(aqty)).center(COL_QTY)
                        # indent=2 spaces before the "+ name" block
                        t(f"  {chunk:<{addon_avail}}{' ' * 2}{aqty_str}\n")
                    else:
                        t(f"  {chunk}\n")

            # Single blank line after full item block
            t("\n")

        # ── Order-level kitchen notes ─────────────────────────────
        if order_notes:
            t(divider() + "\n")
            t(BOLD_ON + "ORDER NOTES:\n" + BOLD_OFF)
            for line in _word_wrap(order_notes, W - 2):
                t("  " + line + "\n")

        # ── Footer ────────────────────────────────────────────────
        t(divider("=") + "\n")
        t(ALIGN_CENTER)
        t(BOLD_ON + "*** END OF ORDER ***" + BOLD_OFF + "\n")
        t(ALIGN_LEFT)

        t("\n" * 8)
        b(b"\x1d\x56\x00")   # GS V 0 — full cut, raw bytes, no encoding

        _send(printer, b"".join(parts))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}