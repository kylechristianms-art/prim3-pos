import os
from flask import Flask
from flask_login import LoginManager
from database import db, User


def create_app():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "app", "templates"),
        static_folder=os.path.join(base_dir, "app", "static"),
    )

    # ── Config ────────────────────────────────────────
    from config import Config
    app.config.from_object(Config)

    # ── Database ──────────────────────────────────────
    db.init_app(app)

    # ── Flask-Login ───────────────────────────────────
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Blueprints ────────────────────────────────────
    from app.routes.auth_routes import auth_bp
    from app.routes.pos_routes import pos_bp
    from app.routes.orders_routes import orders_bp
    from app.routes.products_routes import products_bp
    from app.routes.users_routes import users_bp
    from app.routes.reports_routes import reports_bp
    from app.routes.print_routes import print_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(print_bp)

    # ── Root redirect ─────────────────────────────────
    @app.route("/")
    def home():
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))

    # ── DB seed ───────────────────────────────────────
    with app.app_context():
        db.create_all()
        _migrate_existing_db()
        _seed_defaults()

    return app


def _migrate_existing_db():
    """Safely add any missing columns to the existing SQLite database."""
    import sqlalchemy as sa

    migrations = [
        ("users",         "pin",          "VARCHAR(10)"),
        ("categories",    "color",        "VARCHAR(20) DEFAULT '#f5c518'"),
        ("categories",    "parent_id",    "INTEGER"),
        ("saved_printers","printer_type", "VARCHAR(20) DEFAULT 'receipt'"),
    ]

    with db.engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
                existing_cols = [row[1] for row in rows]
                if column not in existing_cols:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    conn.commit()
                    print(f"[migration] Added column '{column}' to '{table}'")
            except Exception as e:
                print(f"[migration] Skipped {table}.{column}: {e}")


def _seed_defaults():
    from werkzeug.security import generate_password_hash
    from database import ReceiptCounter

    if not User.query.filter_by(username="admin").first():
        admin = User(
            name="Administrator",
            username="admin",
            password=generate_password_hash("admin123"),
            role="admin",
        )
        db.session.add(admin)

    if not ReceiptCounter.query.first():
        db.session.add(ReceiptCounter(current_number=1))

    db.session.commit()