import json


def calculate_total(cart, discount_amount):
    subtotal       = 0
    item_pwd_disc  = 0
    item_flat_disc = 0

    for item in cart:
        price = float(item.get("price", 0))
        qty   = int(item.get("qty", 1))

        addon_cost = sum(
            float(a.get("price", 0)) * int(a.get("qty", 1))
            for a in item.get("addons", [])
        ) * qty

        subtotal += price * qty + addon_cost

        if item.get("pwdDiscount"):
            item_pwd_disc += price * qty * 0.20

        item_flat_disc += float(item.get("discount", 0))

    total_discount = discount_amount + item_pwd_disc + item_flat_disc
    total          = subtotal - total_discount

    return round(subtotal, 2), round(total_discount, 2), round(total, 2)


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
    """Return a dict with ALL fields that orders.html and pos.html need."""
    try:
        cart = json.loads(order.cart_json)
    except Exception:
        cart = []

    subtotal, discount, total = calculate_total(cart, order.discount_amount)

    try:
        created_at_str = order.created_at.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        created_at_str = ""

    return {
        # Core identifiers
        "id":              order.id,
        "label":           order.label or "",
        # Cart data
        "cart":            cart,
        "subtotal":        subtotal,
        "discount_amount": round(float(order.discount_amount or 0), 2),
        "total":           total,
        # Status flags
        "is_void":         bool(order.is_void),
        "is_completed":    bool(order.is_completed),
        # Order metadata — all required by orders.html card renderer
        "order_type":      order.order_type      or "dine_in",
        "payment_method":  order.payment_method  or "cash",
        "kitchen_notes":   order.kitchen_notes   or "",
        # Void details
        "void_reason":     order.void_reason     or "",
        "void_resolution": order.void_resolution or "",
        # Timestamps
        "created_at":      created_at_str,
    }