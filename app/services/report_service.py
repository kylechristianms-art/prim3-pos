from database import Sale, SaleItem, Product
from sqlalchemy import func
from datetime import date

def daily_sales():
    today = date.today()

    sales = Sale.query.filter(
        func.date(Sale.timestamp) == today,
        Sale.is_void == False
    ).all()

    total = sum(s.final_total for s in sales)

    return {
        "total_sales": total,
        "transactions": len(sales)
    }


def top_products():
    results = (
        SaleItem.query
        .with_entities(
            SaleItem.product_name,
            func.sum(SaleItem.quantity).label("qty")
        )
        .group_by(SaleItem.product_name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(5)
        .all()
    )

    return [
        {"name": r.product_name, "qty": r.qty}
        for r in results
    ]