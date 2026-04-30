from flask import Flask, render_template, request, redirect, session, url_for, flash
from werkzeug.security import check_password_hash
from config import Config
from database import db, User, AuditLog
from datetime import datetime


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_defaults()

    # ── AUTH ROUTES ──────────────────────────────────
    @app.route('/')
    def home():
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user = User.query.filter_by(username=username).first()

            if user and check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                _log(user.id, "LOGIN", f"{user.username} logged in")
                return redirect(url_for('dashboard'))
            else:
                return render_template('login.html', error="Invalid username or password.")

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        user_id = session.get('user_id')
        username = session.get('username')
        if user_id:
            _log(user_id, "LOGOUT", f"{username} logged out")
        session.clear()
        return redirect(url_for('login'))

    # ── DASHBOARD ────────────────────────────────────
    @app.route('/dashboard')
    def dashboard():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return render_template('dashboard.html',
                               username=session.get('username'),
                               role=session.get('role'))

    return app


# ── HELPERS ──────────────────────────────────────────
def _log(user_id, action, details):
    try:
        log = AuditLog(user_id=user_id, action=action,
                       details=details, created_at=datetime.utcnow())
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass


def _seed_defaults():
    """Create default admin and receipt counter if they don't exist."""
    from werkzeug.security import generate_password_hash
    from database import ReceiptCounter

    if not User.query.filter_by(username="admin").first():
        admin = User(
            name="Administrator",
            username="admin",
            password=generate_password_hash("admin123"),
            role="admin"
        )
        db.session.add(admin)

    if not ReceiptCounter.query.first():
        db.session.add(ReceiptCounter(current_number=1))

    db.session.commit()