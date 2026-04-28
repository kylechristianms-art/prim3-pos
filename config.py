import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "prim3-pos-secret-key")
    SQLALCHEMY_DATABASE_URI = "sqlite:///prim3pos.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join("static", "product_photos")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024