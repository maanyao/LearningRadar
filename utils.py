# utils.py
import sqlite3
import json
from datetime import datetime, timedelta
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'student_data.db')
STUCK_TIMEOUT_MINUTES = 1

def format_datetime(dt):
    if dt is None:
        return ''
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return str(dt)[:19]

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_action(user_id, action_type):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO actions (user_id, action_type, timestamp) VALUES (?,?,?)",
              (user_id, action_type, datetime.now()))
    conn.commit()
    conn.close()