import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "prim3-pos-secret-key")

    database_url = os.environ.get("DATABASE_URL", "sqlite:///prim3pos.db")

    # fix for postgres on Render
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = database_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join("static", "product_photos")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024