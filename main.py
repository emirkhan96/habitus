import asyncio
import os
import logging
import html
from datetime import datetime, timedelta
from dotenv import load_dotenv, find_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler


# ИМПОРТЫ
from database import (
    init_db,
    add_habit,
    get_all_user_habits,
    get_user_habit,
    update_habit_stats,
    delete_habit,
    update_habit_time,
    set_user_sheet,
    get_user_sheet,
    set_user_timezone,
    get_user_timezone,
    get_all_habits_with_users,
    is_timezone_confirmed,
)
from google_manager import write_to_sheet, get_bot_email, check_sheet_access

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

env_file = find_dotenv()
if not env_file: exit("❌ .env не найден")
load_dotenv(env_file)

token = os.getenv("BOT_TOKEN")
if not token:
    exit("❌ Переменная окружения BOT_TOKEN не найдена. Пожалуйста, добавьте её в .env файл.")
bot = Bot(token=token)

dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- СОСТОЯНИЯ ---
class HabitForm(StatesGroup): name = State(); frequency = State(); time = State()
class EditForm(StatesGroup): waiting_for_new_time = State()
class IntegrationSetup(StatesGroup): waiting_for_link = State()
class TimezoneSetup(StatesGroup): waiting_for_time = State() # Новое состояние

# --- МЕНЮ ---
NO_REMINDER_LABEL = "Не напоминать 🔕"
NO_REMINDER_VALUE = "Без напоминаний"

kb_menu = [
    [KeyboardButton(text="Новая привычка ➕"), KeyboardButton(text="Мои привычки 📋")], 
    [KeyboardButton(text="Моя статистика 📊"), KeyboardButton(text="Настройка времени 🕒")],
    [KeyboardButton(text="Интеграции ⚙️")]
]
main_keyboard = ReplyKeyboardMarkup(keyboard=kb_menu, resize_keyboard=True)

kb_freq = [[KeyboardButton(text="Каждый день"), KeyboardButton(text="По будням"), KeyboardButton(text="Раз в неделю")]]
freq_keyboard = ReplyKeyboardMarkup(keyboard=kb_freq, resize_keyboard=True, one_time_keyboard=True)
kb_time = [[KeyboardButton(text=NO_REMINDER_LABEL)]]
time_keyboard = ReplyKeyboardMarkup(keyboard=kb_time, resize_keyboard=True, one_time_keyboard=True)


def escape_html(text: str) -> str:
    return html.escape(text or "")


TIMEZONE_PROMPT = (
    "Чтобы напоминания приходили вовремя, мне нужно знать твой часовой пояс.\n\n"
    "⏰ <b>Напиши мне, сколько у тебя сейчас времени?</b>\n"
    "(Например: 14:30 или 09:15)"
)


async def start_timezone_setup(message: types.Message, state: FSMContext):
    await state.set_state(TimezoneSetup.waiting_for_time)
    await message.answer(TIMEZONE_PROMPT, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())


# --- START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if not is_timezone_confirmed(message.from_user.id):
        await message.answer("Привет! Сначала настроим время 🕒.")
        await start_timezone_setup(message, state)
        return
    await state.clear()
    await message.answer("Привет! Давай настроим твои привычки.", reply_markup=main_keyboard)

# ==========================================
# БЛОК 0: НАСТРОЙКА ВРЕМЕНИ (НОВОЕ)
# ==========================================
@dp.message(F.text == "Настройка времени 🕒")
async def setup_timezone_start(message: types.Message, state: FSMContext):
    await message.answer("Обновим время напоминаний 🕒.")
    await start_timezone_setup(message, state)

@dp.message(TimezoneSetup.waiting_for_time)
async def setup_timezone_finish(message: types.Message, state: FSMContext):
    try:
        # 1. Парсим время пользователя
        user_time_str = message.text.strip()
        user_h, user_m = map(int, user_time_str.split(":"))
        
        # 2. Берем текущее время сервера (UTC)
        server_now = datetime.utcnow()
        
        # 3. Создаем объект времени пользователя "сегодня"
        user_now = server_now.replace(hour=user_h, minute=user_m)
        
        # 4. Считаем разницу
        # Если пользователь ввел 18:00, а на сервере 13:00 -> разница +5 часов
        diff = user_now - server_now
        
        # Округляем до часов (чтобы убрать минуты погрешности ввода)
        offset_hours = round(diff.total_seconds() / 3600)
        
        # Сохраняем в базу
        set_user_timezone(message.from_user.id, offset_hours)
        
        await state.clear()
        
        sign = "+" if offset_hours >= 0 else ""
        await message.answer(f"✅ Понял! Твой часовой пояс: UTC{sign}{offset_hours}.\nТеперь напоминания будут приходить вовремя.", reply_markup=main_keyboard)
        
    except Exception:
        await message.answer("❌ Не понимаю формат. Пожалуйста, напиши время как ЧЧ:ММ (например 18:30).")

# ==========================================
# БЛОК 1: УПРАВЛЕНИЕ ПРИВЫЧКАМИ
# ==========================================
@dp.message(F.text == "Новая привычка ➕")
async def start_new_habit(message: types.Message, state: FSMContext):
    await state.set_state(HabitForm.name)
    await message.answer("Название?", reply_markup=ReplyKeyboardRemove())

@dp.message(HabitForm.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(habit_name=message.text)
    await state.set_state(HabitForm.frequency)
    await message.answer("Как часто?", reply_markup=freq_keyboard)

@dp.message(HabitForm.frequency)
async def process_freq(message: types.Message, state: FSMContext):
    await state.update_data(habit_freq=message.text)
    await state.set_state(HabitForm.time)
    await message.answer("Во сколько?", reply_markup=time_keyboard)

@dp.message(HabitForm.time)
async def process_time(message: types.Message, state: FSMContext):
    answer = (message.text or "").strip()
    final_time = NO_REMINDER_VALUE if answer == NO_REMINDER_LABEL else answer
    if final_time != NO_REMINDER_VALUE and ":" not in final_time:
        return await message.answer("❌ Формат ЧЧ:ММ")
    data = await state.get_data()
    add_habit(message.from_user.id, data['habit_name'], data['habit_freq'], final_time)
    await state.clear()
    await message.answer(f"✅ '{data['habit_name']}' сохранена!", reply_markup=main_keyboard)

async def send_habits_menu(chat_id: int, user_id: int):
    habits = get_all_user_habits(user_id)
    if not habits:
        await bot.send_message(chat_id, "Список пуст.", reply_markup=main_keyboard)
        return
    text_report = "<b>Твои привычки:</b>\n\n"
    keyboard_buttons = []
    for h in habits:
        display_time = h[3] if h[3] != NO_REMINDER_VALUE else NO_REMINDER_LABEL
        safe_name = escape_html(h[1])
        safe_freq = escape_html(h[2])
        safe_time = escape_html(display_time)
        text_report += f"🔹 <b>{safe_name}</b> ({safe_freq}) — ⏰ {safe_time}\n"
        keyboard_buttons.append([InlineKeyboardButton(text=f"⚙️ {h[1]}", callback_data=f"open_{h[0]}")])
    await bot.send_message(chat_id, text_report, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons), parse_mode="HTML")


@dp.message(F.text == "Мои привычки 📋")
async def show_habits_menu(message: types.Message):
    await send_habits_menu(message.chat.id, message.from_user.id)

@dp.callback_query(F.data.startswith("open_"))
async def open_habit_options(callback: CallbackQuery):
    habit_id = int(callback.data.split("_", 1)[1])
    habit = get_user_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена.", show_alert=True)
        return
    name = escape_html(habit[2])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Время", callback_data=f"edittime_{habit_id}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_{habit_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_list")]
    ])
    await callback.message.edit_text(f"Настройка: <b>{name}</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    await callback.message.delete()
    await send_habits_menu(callback.message.chat.id, callback.from_user.id)
    await callback.answer()

@dp.callback_query(F.data.startswith("del_"))
async def delete_habit_handler(callback: CallbackQuery):
    habit_id = int(callback.data.split("_", 1)[1])
    if delete_habit(habit_id, callback.from_user.id):
        await callback.message.edit_text("✅ Удалено.")
    else:
        await callback.answer("Привычка не найдена.", show_alert=True)
        return
    await callback.answer("Удалено.")

@dp.callback_query(F.data.startswith("edittime_"))
async def edit_time_start(callback: CallbackQuery, state: FSMContext):
    habit_id = int(callback.data.split("_", 1)[1])
    if not get_user_habit(habit_id, callback.from_user.id):
        await callback.answer("Нет доступа к привычке.", show_alert=True)
        return
    await state.update_data(editing_habit_id=habit_id)
    await state.set_state(EditForm.waiting_for_new_time)
    await callback.message.answer("Новое время (ЧЧ:ММ) или выбери «Не напоминать 🔕».", reply_markup=time_keyboard)
    await callback.answer()

@dp.message(EditForm.waiting_for_new_time)
async def edit_time_finish(message: types.Message, state: FSMContext):
    answer = (message.text or "").strip()
    if answer == NO_REMINDER_LABEL:
        new_time = NO_REMINDER_VALUE
    else:
        new_time = answer
    if new_time != NO_REMINDER_VALUE and ":" not in new_time:
        return await message.answer("❌ Формат ЧЧ:ММ")
    data = await state.get_data()
    updated = update_habit_time(data['editing_habit_id'], message.from_user.id, new_time)
    await state.clear()
    if updated:
        await message.answer("✅ Время обновлено!", reply_markup=main_keyboard)
    else:
        await message.answer("❌ Не удалось обновить время. Попробуй снова.", reply_markup=main_keyboard)

# ==========================================
# БЛОК 2: СТАТИСТИКА
# ==========================================
@dp.message(F.text == "Моя статистика 📊")
async def show_detailed_stats(message: types.Message):
    habits = get_all_user_habits(message.from_user.id)
    if not habits: return await message.answer("Нет данных.")
    report = "<b>📊 Твоя эффективность:</b>\n\n"
    for h in habits:
        done = h[4]; skip = h[5]; total = done + skip
        percent = int((done/total)*100) if total > 0 else 0
        bars = "🟩" * (percent // 10) + "⬜" * ((100 - percent) // 10)
        safe_name = escape_html(h[1])
        start_date = escape_html(h[6])
        report += (
            f"🔹 <b>{safe_name}</b>\n"
            f"📅 Старт: {start_date}\n"
            f"✅ Выполнено: {done} | ❌ Пропущено: {skip}\n"
            f"📈 Успех: {percent}%\n"
            f"{bars}\n\n"
        )
    await message.answer(report, parse_mode="HTML")

# ==========================================
# БЛОК 3: ИНТЕГРАЦИИ
# ==========================================
@dp.message(F.text == "Интеграции ⚙️")
async def integrations_menu(message: types.Message):
    current_link = get_user_sheet(message.from_user.id)
    status = "✅ Подключено" if current_link else "❌ Не подключено"
    text = f"<b>Настройки интеграций</b>\nСтатус Google Sheets: {status}\n\nКуда хочешь сохранять отчеты?"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Google Sheets", callback_data="setup_google")]])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "setup_google")
async def setup_google_step1(callback: CallbackQuery):
    bot_email = get_bot_email()
    text = ("<b>Настройка Google Sheets 📄</b>\n\n1. Создай новую таблицу.\n2. Добавь бота как Редактора:\n")
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.message.answer(f"<code>{escape_html(bot_email)}</code>", parse_mode="HTML")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я добавил бота, дальше", callback_data="setup_google_step2")]])
    await callback.message.answer("Когда добавишь бота, нажми кнопку:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "setup_google_step2")
async def setup_google_step2(callback: CallbackQuery, state: FSMContext):
    await state.set_state(IntegrationSetup.waiting_for_link)
    await callback.message.answer("Пришли мне <b>ссылку</b> на таблицу.", parse_mode="HTML")
    await callback.answer()

@dp.message(IntegrationSetup.waiting_for_link)
async def setup_google_finish(message: types.Message, state: FSMContext):
    link = message.text.strip()
    msg = await message.answer("Проверяю доступ... 🔄")
    if check_sheet_access(link):
        set_user_sheet(message.from_user.id, link)
        await msg.edit_text("✅ <b>Успешно!</b> Таблица подключена.", parse_mode="HTML")
    else:
        await msg.edit_text("❌ <b>Ошибка доступа.</b>", parse_mode="HTML")
        return
    await state.clear()

# --- ОТЧЕТЫ И РАССЫЛКА (УМНАЯ) ---
@dp.callback_query(F.data.startswith("done_") | F.data.startswith("skip_"))
async def process_habit_action(callback: CallbackQuery):
    action, habit_id = callback.data.split("_", 1)
    habit_id = int(habit_id)
    habit = get_user_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена.", show_alert=True)
        return
    habit_name = habit[2]
    is_done = (action == "done")
    update_habit_stats(habit_id, callback.from_user.id, is_done)
    
    status_text = "ВЫПОЛНЕНО" if is_done else "ПРОПУЩЕНО"
    sheet_link = get_user_sheet(callback.from_user.id)
    google_res = write_to_sheet(sheet_link, habit_name, status_text) if sheet_link else ""
    
    icon = "✅ Молодец!" if is_done else "😴 Эх..."
    new_text = f"{icon} (Сохранено в Google)" if (sheet_link and "Записано" in google_res) else f"{icon}"
    await callback.message.edit_text(new_text)
    await callback.answer()

async def check_reminders():
    # 1. Получаем текущее время сервера в UTC
    now_utc = datetime.utcnow()
    # Округляем до минут (отбрасываем секунды), чтобы четко совпадало с базой
    now_utc = now_utc.replace(second=0, microsecond=0)
    
    # 2. Получаем ВСЕ привычки
    all_habits = get_all_habits_with_users() # Возвращает (id, user_id, name, time_str)
    
    # 3. Проверяем каждую привычку
    for habit in all_habits:
        habit_id, user_id, habit_name, habit_time_str = habit
        
        # Пропускаем, если "Не напоминать"
        if habit_time_str == "Без напоминаний" or ":" not in habit_time_str:
            continue
            
        # Узнаем часовой пояс пользователя (или берем +3 по дефолту)
        offset = get_user_timezone(user_id)
        
        # Вычисляем время у пользователя: UTC сервера + его сдвиг
        user_local_time = now_utc + timedelta(hours=offset)
        user_time_str = user_local_time.strftime("%H:%M")
        
        # 4. Если время совпало — отправляем!
        if user_time_str == habit_time_str:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сделано ✅", callback_data=f"done_{habit_id}"), InlineKeyboardButton(text="Пропуск ❌", callback_data=f"skip_{habit_id}")]])
            try: 
                safe_name = escape_html(habit_name)
                await bot.send_message(user_id, f"🔔 <b>Пора: {safe_name}</b>", reply_markup=kb, parse_mode="HTML")
                logger.info("Reminder sent to %s for habit %s", user_id, habit_name)
            except Exception as e: 
                logger.exception("Failed to send reminder to %s for habit %s", user_id, habit_name)

async def main():
    init_db()
    # Запускаем планировщик
    scheduler.add_job(check_reminders, 'cron', minute='*')
    scheduler.start()
    print("🤖 Бот (Версия: Умное время) запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
