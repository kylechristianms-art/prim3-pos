from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from database import db, Product, Category, SavedPrinter, Sale, SavedOrder
from app.services.product_service import get_low_stock
from app.services.report_service import daily_sales
from sqlalchemy import func
from datetime import date

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/dashboard")
@login_required
def dashboard():
    today = date.today()

    daily              = daily_sales()
    today_sales        = daily.get("total_sales", 0)
    today_transactions = daily.get("transactions", 0)

    total_products      = Product.query.count()
    low_stock_count     = len(get_low_stock())
    active_orders_count = SavedOrder.query.filter_by(
        is_void=False, is_completed=False
    ).count()

    recent_sales = Sale.query.filter(
        func.date(Sale.timestamp) == today
    ).order_by(Sale.timestamp.desc()).limit(10).all()

    return render_template(
        "dashboard.html",
        current_user=current_user,
        today_sales=today_sales,
        today_transactions=today_transactions,
        total_products=total_products,
        low_stock=low_stock_count,
        active_orders_count=active_orders_count,
        recent_sales=recent_sales,
    )


@pos_bp.route("/pos")
@login_required
def pos():
    products   = Product.query.order_by(Product.name).all()
    categories = Category.query.all()
    printers   = SavedPrinter.query.all()

    load_order_id = None
    try:
        from flask import request
        oid = request.args.get("order_id")
        if oid:
            load_order_id = int(oid)
    except Exception:
        pass

    return render_template(
        "pos.html",
        products=products,
        categories=categories,
        saved_printers=printers,
        current_user=current_user,
        load_order_id=load_order_id,
    )


# ── Page routes (sidebar navigation) ─────────────────────────────
@pos_bp.route("/orders")
@login_required
def orders_page():
    return render_template("orders.html", current_user=current_user)


@pos_bp.route("/products")
@login_required
def products_page():
    if current_user.role not in ["admin", "manager"]:
        flash("Access denied", "error")
        return redirect(url_for("pos.dashboard"))
    products   = Product.query.order_by(Product.name).all()
    categories = Category.query.all()
    return render_template(
        "products.html",
        current_user=current_user,
        products=products,
        categories=categories,
    )


@pos_bp.route("/reports")
@login_required
def reports_page():
    if current_user.role not in ["admin", "manager"]:
        flash("Access denied", "error")
        return redirect(url_for("pos.dashboard"))
    return render_template("reports.html", current_user=current_user)


@pos_bp.route("/users")
@login_required
def users_page():
    if current_user.role not in ["admin", "manager"]:
        flash("Access denied", "error")
        return redirect(url_for("pos.dashboard"))
    return render_template("users.html", current_user=current_user)

# NOTE: product_photo was intentionally removed from this file.
# It now lives in products_routes.py as url_for('products.product_photo', ...)
# which matches the call in pos.html.