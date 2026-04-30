from flask import Blueprint, jsonify, request
from flask_login import login_required
from datetime import date
from app.services.report_service import (
    _parse_date,
    get_summary, get_sales_over_time, get_top_products,
    get_payment_breakdown, get_cashier_performance,
    get_hourly_breakdown, get_category_sales,
    get_void_analysis, get_transactions, get_inventory_status,
    daily_sales, top_products,
)

reports_bp = Blueprint("reports", __name__)


def _dates():
    """Parse ?from= and ?to= query params, defaulting to today."""
    today = date.today()
    df    = _parse_date(request.args.get("from"), today)
    dt    = _parse_date(request.args.get("to"),   today)
    if df > dt:
        df = dt
    return df, dt


# ── KPI Summary ───────────────────────────────────────────────────
@reports_bp.route("/reports/summary")
@login_required
def summary():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_summary(df, dt)})


# ── Sales Over Time ───────────────────────────────────────────────
@reports_bp.route("/reports/sales_over_time")
@login_required
def sales_over_time():
    df, dt   = _dates()
    group_by = request.args.get("group", "day")
    return jsonify({"success": True, "data": get_sales_over_time(df, dt, group_by)})


# ── Top Products ──────────────────────────────────────────────────
@reports_bp.route("/reports/top_products")
@login_required
def top_products_route():
    df, dt = _dates()
    limit  = int(request.args.get("limit", 10))
    return jsonify({"success": True, "data": get_top_products(df, dt, limit)})


# ── Payment Breakdown ─────────────────────────────────────────────
@reports_bp.route("/reports/payment_breakdown")
@login_required
def payment_breakdown():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_payment_breakdown(df, dt)})


# ── Cashier Performance ───────────────────────────────────────────
@reports_bp.route("/reports/cashier_performance")
@login_required
def cashier_performance():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_cashier_performance(df, dt)})


# ── Hourly Breakdown ──────────────────────────────────────────────
@reports_bp.route("/reports/hourly")
@login_required
def hourly():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_hourly_breakdown(df, dt)})


# ── Category Sales ────────────────────────────────────────────────
@reports_bp.route("/reports/category_sales")
@login_required
def category_sales():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_category_sales(df, dt)})


# ── Void Analysis ─────────────────────────────────────────────────
@reports_bp.route("/reports/void_analysis")
@login_required
def void_analysis():
    df, dt = _dates()
    return jsonify({"success": True, "data": get_void_analysis(df, dt)})


# ── Transaction Log ───────────────────────────────────────────────
@reports_bp.route("/reports/transactions")
@login_required
def transactions():
    df, dt   = _dates()
    page     = max(1, int(request.args.get("page",     1)))
    per_page = max(1, int(request.args.get("per_page", 50)))
    return jsonify({"success": True, "data": get_transactions(df, dt, page, per_page)})


# ── Inventory Status ──────────────────────────────────────────────
@reports_bp.route("/reports/inventory_status")
@login_required
def inventory_status():
    return jsonify({"success": True, "data": get_inventory_status()})


# ── Legacy endpoint (kept for any existing callers) ───────────────
@reports_bp.route("/reports/legacy_summary")
@login_required
def legacy_summary():
    return jsonify({"daily": daily_sales(), "top_products": top_products()})