import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect('database.db')
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL
)
''')

# DEFAULT ADMIN
username = "admin"
password = generate_password_hash("admin123")
role = "admin"

c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
          (username, password, role))

conn.commit()
conn.close()

print("✅ admin created → username: admin | password: admin123")