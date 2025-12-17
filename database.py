import sqlite3
from datetime import datetime

DB_NAME = 'habits.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Таблица привычек
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
    
    # 2. Таблица пользователей (хранит и ссылку на таблицу, и часовой пояс)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            sheet_link TEXT,
            utc_offset INTEGER DEFAULT 3
        )
    ''')
    conn.commit()
    conn.close()

# --- ПРИВЫЧКИ ---
def add_habit(user_id, name, freq, time):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    start_date = datetime.now().strftime("%d.%m.%Y")
    cursor.execute('''
        INSERT INTO habits (user_id, name, frequency, time, start_date) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, name, freq, time, start_date))
    conn.commit()
    conn.close()

def get_all_user_habits(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, name, frequency, time, done_count, skip_count, start_date 
        FROM habits WHERE user_id = ?
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_habit_name(habit_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM habits WHERE id = ?', (habit_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else "Неизвестно"

def update_habit_stats(habit_id, is_done):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if is_done:
        cursor.execute('UPDATE habits SET done_count = done_count + 1 WHERE id = ?', (habit_id,))
    else:
        cursor.execute('UPDATE habits SET skip_count = skip_count + 1 WHERE id = ?', (habit_id,))
    conn.commit()
    conn.close()

def delete_habit(habit_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM habits WHERE id = ?', (habit_id,))
    conn.commit()
    conn.close()

def update_habit_time(habit_id, new_time):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE habits SET time = ? WHERE id = ?', (new_time, habit_id))
    conn.commit()
    conn.close()

# --- ИНТЕГРАЦИИ (GOOGLE) ---
def set_user_sheet(user_id, link):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Используем UPSERT: если пользователь есть - обновляем ссылку, если нет - создаем
    cursor.execute('''
        INSERT INTO users (user_id, sheet_link) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET sheet_link=excluded.sheet_link
    ''', (user_id, link))
    conn.commit()
    conn.close()

def get_user_sheet(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT sheet_link FROM users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

# --- НОВЫЕ ФУНКЦИИ (ДЛЯ ВРЕМЕНИ) ---
def set_user_timezone(user_id, offset):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Тоже UPSERT: обновляем только смещение времени
    cursor.execute('''
        INSERT INTO users (user_id, utc_offset) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET utc_offset=excluded.utc_offset
    ''', (user_id, offset))
    conn.commit()
    conn.close()

def get_user_timezone(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT utc_offset FROM users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    # Если настройки нет, возвращаем 3 (Москва) как дефолт
    return res[0] if res and res[0] is not None else 3

def get_all_habits_with_users():
    """Возвращает все привычки для проверки времени"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, name, time FROM habits")
    rows = cursor.fetchall()
    conn.close()
    return rows