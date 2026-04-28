from database import db, User
from werkzeug.security import generate_password_hash

def create_user(data):
    user = User(
        name=data["name"],
        username=data["username"],
        password=generate_password_hash(data["password"]),
        role=data.get("role", "cashier")
    )

    db.session.add(user)
    db.session.commit()

    return user