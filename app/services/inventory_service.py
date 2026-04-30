"""
inventory_service.py
Handles all ingredient inventory business logic:
  - CRUD helpers (get, serialize)
  - Stock actions (restock, adjust, wastage, override)
  - Sale deductions
  - Activity log retrieval
  - Per-product ingredient status checks
  - Custom unit management
"""

from database import db, Ingredient, InventoryLog, ProductIngredient, CustomUnit

# ---------------------------------------------------------------------------
# Default built-in units
# ---------------------------------------------------------------------------

_DEFAULT_UNITS = ["pieces", "portions", "kg", "liters", "units"]

# UNITS is kept as a module-level name for backwards compatibility.
# Call get_all_units() at request time to include custom units.
UNITS = _DEFAULT_UNITS


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def get_all_units():
    """Return the merged list of built-in + custom units (sorted, deduplicated)."""
    custom = [u.name for u in CustomUnit.query.order_by(CustomUnit.name).all()]
    merged = list(dict.fromkeys(_DEFAULT_UNITS + custom))   # preserve order, remove dupes
    return merged


def add_custom_unit(name):
    """Add a new custom unit. Returns (success, message)."""
    name = (name or "").strip()
    if not name:
        return False, "Unit name is required."
    if name.lower() in [u.lower() for u in _DEFAULT_UNITS]:
        return False, f"'{name}' is already a built-in unit."
    existing = CustomUnit.query.filter(
        db.func.lower(CustomUnit.name) == name.lower()
    ).first()
    if existing:
        return False, f"'{name}' already exists."
    db.session.add(CustomUnit(name=name))
    db.session.commit()
    return True, f"Unit '{name}' added."


def delete_custom_unit(unit_id):
    """Delete a custom unit by id. Returns (success, message)."""
    unit = db.session.get(CustomUnit, unit_id)
    if not unit:
        return False, "Unit not found."
    name = unit.name
    db.session.delete(unit)
    db.session.commit()
    return True, f"Unit '{name}' deleted."


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_all_ingredients():
    """Return all Ingredient rows ordered by name."""
    return Ingredient.query.order_by(Ingredient.name).all()


def serialize_ingredient(ing):
    """Convert an Ingredient ORM object to a plain dict."""
    if ing.quantity <= 0:
        status = "out"
    elif ing.quantity <= ing.low_stock_threshold:
        status = "low"
    else:
        status = "ok"

    return {
        "id":                  ing.id,
        "name":                ing.name,
        "unit":                ing.unit,
        "quantity":            round(ing.quantity, 3),
        "low_stock_threshold": round(ing.low_stock_threshold, 3),
        "cost_per_unit":       round(ing.cost_per_unit, 2),
        "status":              status,
    }


# ---------------------------------------------------------------------------
# Stock actions
# ---------------------------------------------------------------------------

def restock_ingredient(ingredient_id, quantity, notes, user_id):
    """Add stock to an ingredient and log the action."""
    ing = db.session.get(Ingredient, ingredient_id)
    if not ing:
        return False
    ing.quantity += quantity
    _log(ing.id, "restock", quantity, notes, user_id)
    db.session.commit()
    return True


def adjust_ingredient(ingredient_id, new_quantity, notes, user_id):
    """Set an ingredient's stock to an exact quantity and log the delta."""
    ing = db.session.get(Ingredient, ingredient_id)
    if not ing:
        return False
    delta        = new_quantity - ing.quantity
    ing.quantity = new_quantity
    _log(ing.id, "adjustment", delta, notes, user_id)
    db.session.commit()
    return True


def log_wastage(ingredient_id, quantity, notes, user_id):
    """Deduct wasted stock from an ingredient and log it."""
    ing = db.session.get(Ingredient, ingredient_id)
    if not ing:
        return False
    ing.quantity = max(0.0, ing.quantity - quantity)
    _log(ing.id, "wastage", -quantity, notes, user_id)
    db.session.commit()
    return True


def log_override(product_id, product_name, reason, user_id):
    """Log a POS override event (cashier sold an out-of-stock product)."""
    note  = f"POS override: {product_name} (id={product_id}) — {reason}"
    links = ProductIngredient.query.filter_by(product_id=product_id).all()
    if links:
        for link in links:
            _log(link.ingredient_id, "override", 0.0, note, user_id)
    db.session.commit()


def deduct_for_sale(cart, user_id):
    """Deduct ingredient stock for every item sold."""
    for item in cart:
        product_id = item.get("id")
        qty_sold   = int(item.get("qty", 1))
        links      = ProductIngredient.query.filter_by(product_id=product_id).all()

        for link in links:
            ing = db.session.get(Ingredient, link.ingredient_id)
            if not ing:
                continue
            amount          = link.quantity_needed * qty_sold
            ing.quantity    = max(0.0, ing.quantity - amount)
            _log(
                ing.id,
                "sale_deduction",
                -amount,
                f"Auto-deducted for sale (product_id={product_id}, qty={qty_sold})",
                user_id,
            )

    db.session.commit()


# ---------------------------------------------------------------------------
# Status checks (used by POS)
# ---------------------------------------------------------------------------

def check_product_ingredients(product_id):
    """Return a list of status dicts for every ingredient linked to a product."""
    links  = ProductIngredient.query.filter_by(product_id=product_id).all()
    result = []

    for link in links:
        ing = db.session.get(Ingredient, link.ingredient_id)
        if not ing:
            continue

        if ing.quantity <= 0:
            status = "out"
        elif ing.quantity <= ing.low_stock_threshold:
            status = "low"
        else:
            status = "ok"

        result.append({
            "ingredient_id":   ing.id,
            "name":            ing.name,
            "unit":            ing.unit,
            "quantity_needed": link.quantity_needed,
            "current_qty":     round(ing.quantity, 3),
            "status":          status,
        })

    return result


def get_all_product_statuses():
    """Return a mapping of product_id → ingredient status summary."""
    from database import Product

    products = Product.query.all()
    statuses = {}

    for product in products:
        ings       = check_product_ingredients(product.id)
        has_issues = any(i["status"] in ("out", "low") for i in ings)
        worst      = "ok"
        if any(i["status"] == "out" for i in ings):
            worst = "out"
        elif any(i["status"] == "low" for i in ings):
            worst = "low"

        statuses[product.id] = {
            "product_id":  product.id,
            "ingredients": ings,
            "has_issues":  has_issues,
            "worst":       worst,
        }

    return statuses


# ---------------------------------------------------------------------------
# Activity log retrieval
# ---------------------------------------------------------------------------

def get_ingredient_logs(ingredient_id=None, limit=100):
    """Return recent InventoryLog rows as plain dicts."""
    query = InventoryLog.query

    if ingredient_id:
        query = query.filter_by(ingredient_id=int(ingredient_id))

    logs = query.order_by(InventoryLog.created_at.desc()).limit(limit).all()

    return [
        {
            "id":              log.id,
            "ingredient_id":   log.ingredient_id,
            "ingredient_name": log.ingredient.name if log.ingredient else "Unknown",
            "action":          log.action,
            "quantity_change": round(log.quantity_change, 3),
            "notes":           log.notes or "",
            "user_id":         log.user_id,
            "created_at":      log.created_at.strftime("%b %d, %Y %I:%M %p") if log.created_at else "",
        }
        for log in logs
    ]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _log(ingredient_id, action, quantity_change, notes, user_id):
    """Create an InventoryLog row. Does NOT commit — caller must commit."""
    db.session.add(InventoryLog(
        ingredient_id=ingredient_id,
        action=action,
        quantity_change=quantity_change,
        notes=notes,
        user_id=user_id,
    ))