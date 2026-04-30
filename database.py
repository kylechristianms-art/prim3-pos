from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100))
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role     = db.Column(db.String(20), default="cashier")
    pin      = db.Column(db.String(10), nullable=True)


class Category(db.Model):
    __tablename__ = "categories"
    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String(100), nullable=False)
    color     = db.Column(db.String(20), nullable=True, default="#f5c518")
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    parent    = db.relationship("Category", remote_side=[id], backref="children", foreign_keys=[parent_id])


class SavedPrinter(db.Model):
    __tablename__ = "saved_printers"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100))
    port         = db.Column(db.String(100))
    printer_type = db.Column(db.String(20), default="receipt")


# ── NEW: Custom Units of Measure ──────────────────────────────────
class CustomUnit(db.Model):
    __tablename__ = "custom_units"
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


# ── Inventory: Ingredients ────────────────────────────────────────
class Ingredient(db.Model):
    __tablename__ = "ingredients"
    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(100), nullable=False)
    unit                = db.Column(db.String(20), default="pieces")
    quantity            = db.Column(db.Float, default=0.0)
    low_stock_threshold = db.Column(db.Float, default=10.0)
    cost_per_unit       = db.Column(db.Float, default=0.0)


# ── Inventory: Product ↔ Ingredient links ─────────────────────────
class ProductIngredient(db.Model):
    __tablename__   = "product_ingredients"
    id              = db.Column(db.Integer, primary_key=True)
    product_id      = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    ingredient_id   = db.Column(db.Integer, db.ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    quantity_needed = db.Column(db.Float, nullable=False, default=1.0)
    ingredient      = db.relationship("Ingredient", foreign_keys=[ingredient_id])


# ── Inventory: Activity Logs ──────────────────────────────────────
class InventoryLog(db.Model):
    __tablename__   = "inventory_logs"
    id              = db.Column(db.Integer, primary_key=True)
    ingredient_id   = db.Column(db.Integer, db.ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    action          = db.Column(db.String(30))   # restock | adjustment | wastage | sale_deduction | override
    quantity_change = db.Column(db.Float, default=0.0)
    notes           = db.Column(db.Text)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    ingredient      = db.relationship("Ingredient", foreign_keys=[ingredient_id])


class Product(db.Model):
    __tablename__ = "products"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    price       = db.Column(db.Float, nullable=False)
    quantity    = db.Column(db.Integer, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    photo       = db.Column(db.String(200), nullable=True)
    category    = db.relationship("Category", foreign_keys=[category_id])
    ingredients = db.relationship(
        "ProductIngredient", backref="product",
        lazy=True, cascade="all, delete-orphan"
    )


class Addon(db.Model):
    __tablename__ = "addons"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    price       = db.Column(db.Float, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)


class Sale(db.Model):
    __tablename__   = "sales"
    id              = db.Column(db.Integer, primary_key=True)
    total           = db.Column(db.Float)
    discount_amount = db.Column(db.Float, default=0)
    final_total     = db.Column(db.Float)
    payment_method  = db.Column(db.String(20))
    cashier_id      = db.Column(db.Integer, db.ForeignKey("users.id"))
    timestamp       = db.Column(db.DateTime, default=datetime.utcnow)
    is_void         = db.Column(db.Boolean, default=False)
    items           = db.relationship("SaleItem", backref="sale", lazy=True)


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id           = db.Column(db.Integer, primary_key=True)
    sale_id      = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    product_id   = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    quantity     = db.Column(db.Integer)
    price        = db.Column(db.Float)


class SavedOrder(db.Model):
    __tablename__   = "saved_orders"
    id              = db.Column(db.Integer, primary_key=True)
    label           = db.Column(db.String(100))
    cart_json       = db.Column(db.Text)
    discount_amount = db.Column(db.Float, default=0)
    cashier_id      = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    is_void         = db.Column(db.Boolean, default=False)
    is_completed    = db.Column(db.Boolean, default=False)
    order_type      = db.Column(db.String(20), default="dine_in")
    payment_method  = db.Column(db.String(20), default="cash")
    kitchen_notes   = db.Column(db.Text)
    void_reason     = db.Column(db.Text)
    void_resolution = db.Column(db.Text)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id         = db.Column(db.Integer, primary_key=True)
    action     = db.Column(db.String(50))
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    details    = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ReceiptCounter(db.Model):
    __tablename__  = "receipt_counter"
    id             = db.Column(db.Integer, primary_key=True)
    current_number = db.Column(db.Integer, default=1)