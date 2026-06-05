import json
from datetime import timezone, timedelta

# Philippines Standard Time — UTC+8 (no DST)
_PH_TZ = timezone(timedelta(hours=8))


def calculate_total(cart, discount_amount):
    """
    discount_amount = order-level PWD/Senior discount already computed by frontend.
    Per-item item["discount"] on PWD items is for receipt display only — skip it
    here to avoid double-counting. Only sum flat discounts on non-PWD items.
    """
    subtotal       = 0
    item_flat_disc = 0

    for item in cart:
        price = float(item.get("price", 0))
        qty   = int(item.get("qty", 1))

        addon_cost = sum(
            float(a.get("price", 0)) * int(a.get("qty", 1))
            for a in item.get("addons", [])
        ) * qty

        subtotal += price * qty + addon_cost

        # Skip PWD items — their discount is already in discount_amount (order-level)
        # Only add truly separate flat discounts on non-PWD items
        if not item.get("pwdDiscount"):
            item_flat_disc += float(item.get("discount", 0))

    total_discount = discount_amount + item_flat_disc
    total          = subtotal - total_discount

    return round(subtotal, 2), round(total_discount, 2), round(total, 2)


def calculate_cart_with_item_discounts(cart, discount_amount):
    """
    Returns an enriched copy of cart where each item with pwdDiscount=True
    has its computed discount amount written into item['discount'] and
    item['discount_type'] — for receipt display only, not for total calculation.
    """
    enriched = []
    for item in cart:
        it = dict(item)
        if it.get("pwdDiscount"):
            price    = float(it.get("price", 0))
            qty      = int(it.get("qty", 1))
            pwd_disc = round(price * qty * 0.20, 2)
            it["discount"]      = pwd_disc
            it["discount_type"] = "PWD/Senior (20%)"
        enriched.append(it)
    return enriched


def normalize_cart(cart):
    return [
        {
            "id":          item.get("id"),
            "name":        item.get("name"),
            "price":       float(item.get("price", 0)),
            "qty":         int(item.get("qty", 1)),
            "discount":    float(item.get("discount", 0)),
            "pwdDiscount": bool(item.get("pwdDiscount", False)),
            "notes":       item.get("notes", ""),
            "addons":      item.get("addons", []),
        }
        for item in cart
    ]


def serialize_order(order):
    try:
        cart = json.loads(order.cart_json)
    except Exception:
        cart = []

    # Enrich cart so PWD items carry their per-line discount for the PDF
    enriched_cart = calculate_cart_with_item_discounts(cart, float(order.discount_amount or 0))

    subtotal, total_discount, total = calculate_total(cart, float(order.discount_amount or 0))

    # Convert created_at to PH time (UTC+8) before formatting.
    try:
        dt = order.created_at.replace(tzinfo=timezone.utc).astimezone(_PH_TZ)
        created_at_str = dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        created_at_str = ""

    cashier_name = "—"

    try:
        if order.cashier and order.cashier.name:
            cashier_name = order.cashier.name
    except Exception:
        pass

    # ── Resolve sale_id with three-priority fallback ──────────────────────────
    # Priority 1: SavedOrder.sale_id FK column (assigned by checkout() when the
    #             column exists on the model; guarded by try/except AttributeError).
    sale_id = getattr(order, "sale_id", None)

    # Priority 2: Parse from label "Sale #<n>".
    #   checkout() always sets label = f"Sale #{sale.id}", so this extracts the
    #   correct Sale PK even when the FK column hasn't been migrated yet.
    if not sale_id:
        _label = (getattr(order, "label", "") or "").strip()
        if _label.lower().startswith("sale #"):
            try:
                sale_id = int(_label.split("#", 1)[1].strip())
            except (ValueError, IndexError):
                pass

    # Priority 3: Final fallback — use SavedOrder.id so the field is never null.
    #   Applies to orders saved without checkout (no Sale record exists).
    if not sale_id:
        sale_id = order.id

    cash_received = round(float(getattr(order, "cash_received", 0) or 0), 2)
    change = round(max(0.0, cash_received - total), 2) if (order.payment_method or "").lower() == "cash" else 0.0

    return {
        "id":              order.id,
        "sale_id":         sale_id,
        "label":           order.label or "",
        # Return enriched cart so per-item PWD discounts are present for PDF rendering
        "cart":            enriched_cart,
        "subtotal":        subtotal,
        # Expose the FULL total discount (order-level + item flat discounts)
        "discount_amount": round(total_discount, 2),
        "total":           total,
        "cash_received":   cash_received,
        "change":          change,
        "is_void":         bool(order.is_void),
        "is_completed":    bool(order.is_completed),
        "order_type":      order.order_type      or "dine_in",
        "payment_method":  order.payment_method  or "cash",
        "kitchen_notes":   order.kitchen_notes   or "",
        "void_reason":     order.void_reason     or "",
        "void_resolution": order.void_resolution or "",
        "created_at":      created_at_str,
        # Cashier name resolved via ORM relationship
        "cashier_name":    cashier_name,
    }