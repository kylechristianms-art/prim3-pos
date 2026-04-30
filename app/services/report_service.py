"""
report_service.py
Full analytics service for prim3-POS.
Backward-compatible: daily_sales() and top_products() still work for the dashboard.
"""
from datetime import datetime, date, timedelta
from sqlalchemy import func, and_
from database import db, Sale, SaleItem, Product, Category, User, SavedOrder, Ingredient


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(s, fallback):
    """Safely parse a YYYY-MM-DD string; return fallback on failure."""
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return fallback


def _bounds(date_from, date_to):
    """Convert date objects to datetime bounds for SQLAlchemy filters."""
    dt_from = datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0)
    dt_to   = datetime(date_to.year,   date_to.month,   date_to.day,   23, 59, 59)
    return dt_from, dt_to


def _sale_filter(dt_from, dt_to, include_void=False):
    """Base Sale filter for a date range."""
    f = [Sale.timestamp >= dt_from, Sale.timestamp <= dt_to]
    if not include_void:
        f.append(Sale.is_void == False)
    return and_(*f)


# ---------------------------------------------------------------------------
# KPI Summary
# ---------------------------------------------------------------------------

def get_summary(date_from, date_to):
    """Return KPI metrics for a date range."""
    dt_from, dt_to = _bounds(date_from, date_to)

    sales = Sale.query.filter(_sale_filter(dt_from, dt_to)).all()

    total_revenue  = sum(float(s.final_total or 0) for s in sales)
    total_discount = sum(float(s.discount_amount or 0) for s in sales)
    transactions   = len(sales)
    avg_order      = total_revenue / transactions if transactions else 0.0
    items_sold     = sum(
        sum(int(i.quantity or 0) for i in s.items) for s in sales
    )

    # Void stats (all sales, including voided)
    total_all  = Sale.query.filter(
        Sale.timestamp >= dt_from, Sale.timestamp <= dt_to
    ).count()
    void_count = Sale.query.filter(
        Sale.timestamp >= dt_from, Sale.timestamp <= dt_to, Sale.is_void == True
    ).count()
    void_rate  = round((void_count / total_all * 100), 1) if total_all else 0.0

    return {
        "total_revenue":  round(total_revenue, 2),
        "transactions":   transactions,
        "avg_order":      round(avg_order, 2),
        "total_discount": round(total_discount, 2),
        "items_sold":     int(items_sold),
        "void_count":     void_count,
        "void_rate":      void_rate,
    }


# ---------------------------------------------------------------------------
# Sales Over Time
# ---------------------------------------------------------------------------

def get_sales_over_time(date_from, date_to, group_by="day"):
    """Revenue and transaction count grouped by day / week / month."""
    dt_from, dt_to = _bounds(date_from, date_to)

    fmt_map = {"month": "%Y-%m", "week": "%Y-%W", "day": "%Y-%m-%d"}
    fmt     = fmt_map.get(group_by, "%Y-%m-%d")

    rows = (
        db.session.query(
            func.strftime(fmt, Sale.timestamp).label("period"),
            func.sum(Sale.final_total).label("revenue"),
            func.count(Sale.id).label("transactions"),
        )
        .filter(_sale_filter(dt_from, dt_to))
        .group_by("period")
        .order_by("period")
        .all()
    )

    return [
        {
            "period":       r.period,
            "revenue":      round(float(r.revenue or 0), 2),
            "transactions": int(r.transactions or 0),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Top Products
# ---------------------------------------------------------------------------

def get_top_products(date_from, date_to, limit=10):
    """Products ranked by quantity sold, with revenue."""
    dt_from, dt_to = _bounds(date_from, date_to)

    rows = (
        db.session.query(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.quantity * SaleItem.price).label("revenue"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(_sale_filter(dt_from, dt_to))
        .group_by(SaleItem.product_name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "name":    r.product_name or "Unknown",
            "qty":     int(r.qty or 0),
            "revenue": round(float(r.revenue or 0), 2),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Payment Breakdown
# ---------------------------------------------------------------------------

def get_payment_breakdown(date_from, date_to):
    """Sales grouped by payment method."""
    dt_from, dt_to = _bounds(date_from, date_to)

    rows = (
        db.session.query(
            Sale.payment_method,
            func.count(Sale.id).label("count"),
            func.sum(Sale.final_total).label("total"),
        )
        .filter(_sale_filter(dt_from, dt_to))
        .group_by(Sale.payment_method)
        .all()
    )

    return [
        {
            "method": (r.payment_method or "cash").lower(),
            "count":  int(r.count or 0),
            "total":  round(float(r.total or 0), 2),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Cashier Performance
# ---------------------------------------------------------------------------

def get_cashier_performance(date_from, date_to):
    """Revenue, transactions, and avg order per cashier."""
    dt_from, dt_to = _bounds(date_from, date_to)

    rows = (
        db.session.query(
            Sale.cashier_id,
            func.count(Sale.id).label("transactions"),
            func.sum(Sale.final_total).label("revenue"),
            func.avg(Sale.final_total).label("avg_order"),
            func.sum(Sale.discount_amount).label("discounts"),
        )
        .filter(_sale_filter(dt_from, dt_to))
        .group_by(Sale.cashier_id)
        .all()
    )

    result = []
    for r in rows:
        user = db.session.get(User, r.cashier_id) if r.cashier_id else None
        result.append({
            "name":         user.name if user else "Unknown",
            "role":         user.role if user else "—",
            "transactions": int(r.transactions or 0),
            "revenue":      round(float(r.revenue or 0), 2),
            "avg_order":    round(float(r.avg_order or 0), 2),
            "discounts":    round(float(r.discounts or 0), 2),
        })

    return sorted(result, key=lambda x: x["revenue"], reverse=True)


# ---------------------------------------------------------------------------
# Hourly Breakdown
# ---------------------------------------------------------------------------

def get_hourly_breakdown(date_from, date_to):
    """Transactions and revenue per hour of day (0–23)."""
    dt_from, dt_to = _bounds(date_from, date_to)

    rows = (
        db.session.query(
            func.strftime("%H", Sale.timestamp).label("hour"),
            func.count(Sale.id).label("transactions"),
            func.sum(Sale.final_total).label("revenue"),
        )
        .filter(_sale_filter(dt_from, dt_to))
        .group_by("hour")
        .order_by("hour")
        .all()
    )

    # Seed all 24 hours with zeros
    data = {str(h).zfill(2): {"transactions": 0, "revenue": 0.0} for h in range(24)}
    for r in rows:
        h = str(r.hour).zfill(2)
        data[h]["transactions"] = int(r.transactions or 0)
        data[h]["revenue"]      = round(float(r.revenue or 0), 2)

    return [
        {
            "hour":         h,
            "label":        f"{int(h):02d}:00",
            "transactions": v["transactions"],
            "revenue":      v["revenue"],
        }
        for h, v in sorted(data.items())
    ]


# ---------------------------------------------------------------------------
# Category Sales
# ---------------------------------------------------------------------------

def get_category_sales(date_from, date_to):
    """Revenue and quantity sold per product category."""
    dt_from, dt_to = _bounds(date_from, date_to)

    rows = (
        db.session.query(
            Product.category_id,
            func.sum(SaleItem.quantity).label("qty"),
            func.sum(SaleItem.quantity * SaleItem.price).label("revenue"),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .outerjoin(Product, SaleItem.product_id == Product.id)
        .filter(_sale_filter(dt_from, dt_to))
        .group_by(Product.category_id)
        .all()
    )

    cat_data = {}
    for r in rows:
        cat      = db.session.get(Category, r.category_id) if r.category_id else None
        cat_name = cat.name if cat else "Uncategorized"
        if cat_name not in cat_data:
            cat_data[cat_name] = {"qty": 0, "revenue": 0.0, "color": cat.color if cat else "#888"}
        cat_data[cat_name]["qty"]     += int(r.qty or 0)
        cat_data[cat_name]["revenue"] += float(r.revenue or 0)

    return [
        {
            "category": k,
            "qty":      v["qty"],
            "revenue":  round(v["revenue"], 2),
            "color":    v["color"],
        }
        for k, v in sorted(cat_data.items(), key=lambda x: x[1]["revenue"], reverse=True)
    ]


# ---------------------------------------------------------------------------
# Void Analysis
# ---------------------------------------------------------------------------

def get_void_analysis(date_from, date_to):
    """Voided sales and orders with lost revenue estimate."""
    dt_from, dt_to = _bounds(date_from, date_to)

    void_sales = Sale.query.filter(
        Sale.timestamp >= dt_from, Sale.timestamp <= dt_to, Sale.is_void == True
    ).all()

    void_orders = SavedOrder.query.filter(
        SavedOrder.created_at >= dt_from,
        SavedOrder.created_at <= dt_to,
        SavedOrder.is_void == True,
    ).all()

    lost_revenue = sum(float(s.final_total or 0) for s in void_sales)

    return {
        "void_sale_count":  len(void_sales),
        "void_order_count": len(void_orders),
        "lost_revenue":     round(lost_revenue, 2),
        "recent_voids":     [
            {
                "label":      o.label or f"Order #{o.id}",
                "reason":     o.void_reason     or "N/A",
                "resolution": o.void_resolution or "N/A",
                "created_at": o.created_at.strftime("%b %d, %Y %I:%M %p") if o.created_at else "",
            }
            for o in sorted(void_orders, key=lambda x: x.created_at or datetime.min, reverse=True)[:20]
        ],
    }


# ---------------------------------------------------------------------------
# Transaction Log
# ---------------------------------------------------------------------------

def get_transactions(date_from, date_to, page=1, per_page=50, search=""):
    """Paginated, searchable transaction log."""
    dt_from, dt_to = _bounds(date_from, date_to)

    query = (
        Sale.query
        .filter(Sale.timestamp >= dt_from, Sale.timestamp <= dt_to)
        .order_by(Sale.timestamp.desc())
    )

    total  = query.count()
    sales  = query.offset((page - 1) * per_page).limit(per_page).all()

    rows = []
    for s in sales:
        cashier = db.session.get(User, s.cashier_id) if s.cashier_id else None
        rows.append({
            "id":          s.id,
            "cashier":     cashier.name if cashier else "Unknown",
            "items_count": int(sum(i.quantity or 0 for i in s.items)),
            "subtotal":    round(float(s.total or 0), 2),
            "discount":    round(float(s.discount_amount or 0), 2),
            "total":       round(float(s.final_total or 0), 2),
            "payment":     s.payment_method or "cash",
            "is_void":     bool(s.is_void),
            "timestamp":   s.timestamp.strftime("%b %d, %Y %I:%M %p") if s.timestamp else "",
        })

    return {
        "rows":     rows,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, (total + per_page - 1) // per_page),
    }


# ---------------------------------------------------------------------------
# Inventory Status
# ---------------------------------------------------------------------------

def get_inventory_status():
    """Current snapshot of ingredient stock levels."""
    ings = Ingredient.query.order_by(Ingredient.name).all()
    out  = [i for i in ings if i.quantity <= 0]
    low  = [i for i in ings if 0 < i.quantity <= i.low_stock_threshold]

    return {
        "total":      len(ings),
        "out_count":  len(out),
        "low_count":  len(low),
        "ok_count":   len(ings) - len(out) - len(low),
        "alert_items": [
            {
                "name":      i.name,
                "unit":      i.unit,
                "qty":       round(i.quantity, 3),
                "threshold": round(i.low_stock_threshold, 3),
                "status":    "out" if i.quantity <= 0 else "low",
            }
            for i in (out + low)
        ],
    }


# ---------------------------------------------------------------------------
# Backward-compatible helpers used by dashboard & old route
# ---------------------------------------------------------------------------

def daily_sales():
    """Used by dashboard: returns {total_sales, transactions} for today."""
    today = date.today()
    s     = get_summary(today, today)
    return {"total_sales": s["total_revenue"], "transactions": s["transactions"]}


def top_products():
    """Used by dashboard: returns top 5 products this month."""
    today = date.today()
    start = today.replace(day=1)
    return [{"name": r["name"], "qty": r["qty"]} for r in get_top_products(start, today, 5)]