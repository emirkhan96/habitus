import gspread
from datetime import datetime
import json

# Подключение
try:
    gc = gspread.service_account(filename='google_key.json')
    # Загружаем json просто как текст, чтобы достать email
    with open('google_key.json') as f:
        creds = json.load(f)
        BOT_EMAIL = creds.get('client_email', 'Не найден email')
except Exception as e:
    print(f"Ошибка с ключом Google: {e}")
    gc = None
    BOT_EMAIL = "Ошибка ключа"

# 1. Функция: Получить Email бота (чтобы показать юзеру)
def get_bot_email():
    return BOT_EMAIL

# 2. Функция: Проверить доступ к таблице
def check_sheet_access(link):
    if not gc: return False
    try:
        sh = gc.open_by_url(link)
        return True
    except:
        return False

# 3. Функция: Запись
def write_to_sheet(sheet_url, habit_name, status):
    if not gc: return "❌ Ошибка: нет ключа"
    try:
        sh = gc.open_by_url(sheet_url)
        worksheet = sh.sheet1
        now = datetime.now()
        worksheet.append_row([
            now.strftime("%d.%m.%Y"), 
            now.strftime("%H:%M"), 
            habit_name, 
            status
        ])
        return "Записано в Google!"
    except Exception as e:
        return f"Ошибка записи: {e}"