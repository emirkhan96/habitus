import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_NAME = 'habits.db'


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=5)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                frequency TEXT,
                time TEXT,
                done_count INTEGER DEFAULT 0,
                skip_count INTEGER DEFAULT 0,
                start_date TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                sheet_link TEXT,
                utc_offset INTEGER DEFAULT 3,
                timezone_confirmed INTEGER DEFAULT 0
            )
        ''')
        cursor.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cursor.fetchall()}
        if "timezone_confirmed" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN timezone_confirmed INTEGER DEFAULT 0")


# --- Привычки ---
def add_habit(user_id, name, freq, time):
    start_date = datetime.now().strftime("%d.%m.%Y")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO habits (user_id, name, frequency, time, start_date) VALUES (?, ?, ?, ?, ?)''',
            (user_id, name, freq, time, start_date),
        )


def get_all_user_habits(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT id, name, frequency, time, done_count, skip_count, start_date FROM habits WHERE user_id = ?''',
            (user_id,),
        )
        return cursor.fetchall()


def get_user_habit(habit_id, user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT id, user_id, name, frequency, time, done_count, skip_count, start_date FROM habits WHERE id = ? AND user_id = ?''',
            (habit_id, user_id),
        )
        return cursor.fetchone()


def update_habit_stats(habit_id, user_id, is_done):
    with get_connection() as conn:
        cursor = conn.cursor()
        if is_done:
            cursor.execute('UPDATE habits SET done_count = done_count + 1 WHERE id = ? AND user_id = ?', (habit_id, user_id))
        else:
            cursor.execute('UPDATE habits SET skip_count = skip_count + 1 WHERE id = ? AND user_id = ?', (habit_id, user_id))
        return cursor.rowcount > 0


def delete_habit(habit_id, user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM habits WHERE id = ? AND user_id = ?', (habit_id, user_id))
        return cursor.rowcount > 0


def update_habit_time(habit_id, user_id, new_time):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE habits SET time = ? WHERE id = ? AND user_id = ?', (new_time, habit_id, user_id))
        return cursor.rowcount > 0


# --- Интеграции ---
def set_user_sheet(user_id, link):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO users (user_id, sheet_link) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET sheet_link=excluded.sheet_link
            ''',
            (user_id, link),
        )


def get_user_sheet(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT sheet_link FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        return res[0] if res else None


# --- Часовой пояс ---
def set_user_timezone(user_id, offset):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO users (user_id, utc_offset, timezone_confirmed) VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET utc_offset=excluded.utc_offset, timezone_confirmed=1
            ''',
            (user_id, offset),
        )


def is_timezone_confirmed(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT timezone_confirmed FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        return bool(res and res[0])


def get_user_timezone(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT utc_offset FROM users WHERE user_id = ?', (user_id,))
        res = cursor.fetchone()
        return res[0] if res and res[0] is not None else 3


def get_all_habits_with_users():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, user_id, name, time FROM habits')
        return cursor.fetchall()
