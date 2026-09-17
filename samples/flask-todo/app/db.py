"""Every read and write of the SQLite file goes through here."""
import sqlite3
from contextlib import contextmanager

from app.config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL
);
"""


@contextmanager
def connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connection() as conn:
        conn.executescript(SCHEMA)


def insert_user(email, password_hash, salt):
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, salt) VALUES (?, ?, ?)",
            (email, password_hash, salt),
        )
        return cursor.lastrowid


def find_user_by_email(email):
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def save_session(token, user_id, expires_at):
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at),
        )


def find_session(token):
    with connection() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None


def insert_todo(user_id, text):
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO todos (user_id, text, done) VALUES (?, ?, 0)", (user_id, text)
        )
        return {"id": cursor.lastrowid, "user_id": user_id, "text": text, "done": False}


def select_todos(user_id):
    with connection() as conn:
        rows = conn.execute("SELECT * FROM todos WHERE user_id = ?", (user_id,)).fetchall()
        return [dict(row) for row in rows]


def update_todo_done(todo_id, user_id, done):
    with connection() as conn:
        conn.execute(
            "UPDATE todos SET done = ? WHERE id = ? AND user_id = ?", (int(done), todo_id, user_id)
        )
