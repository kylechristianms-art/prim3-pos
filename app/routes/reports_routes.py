from flask import Blueprint, jsonify
from flask_login import login_required
from app.services.report_service import daily_sales, top_products

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports/summary")
@login_required
def summary():
    return jsonify({
        "daily": daily_sales(),
        "top_products": top_products()
    })