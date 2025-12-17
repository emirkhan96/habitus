import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ИМПОРТЫ
from database import init_db, add_habit, get_all_user_habits, update_habit_stats, set_user_sheet, get_user_sheet, get_habit_name, delete_habit, update_habit_time, get_habits_by_time
from google_manager import write_to_sheet, get_bot_email, check_sheet_access

logging.basicConfig(level=logging.ERROR)

env_file = find_dotenv()
if not env_file: exit("❌ .env не найден")
load_dotenv(env_file)
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- СОСТОЯНИЯ ---
class HabitForm(StatesGroup):
    name = State(); frequency = State(); time = State()
class EditForm(StatesGroup):
    waiting_for_new_time = State()
class IntegrationSetup(StatesGroup): # Состояние для мастера настройки
    waiting_for_link = State()

# --- НОВОЕ ГЛАВНОЕ МЕНЮ ---
kb_menu = [
    [KeyboardButton(text="Новая привычка ➕"), KeyboardButton(text="Мои привычки 📋")], 
    [KeyboardButton(text="Моя статистика 📊"), KeyboardButton(text="Интеграции ⚙️")] 
]
main_keyboard = ReplyKeyboardMarkup(keyboard=kb_menu, resize_keyboard=True)

kb_freq = [[KeyboardButton(text="Каждый день"), KeyboardButton(text="По будням"), KeyboardButton(text="Раз в неделю")]]
freq_keyboard = ReplyKeyboardMarkup(keyboard=kb_freq, resize_keyboard=True, one_time_keyboard=True)
kb_time = [[KeyboardButton(text="Не напоминать 🔕")]]
time_keyboard = ReplyKeyboardMarkup(keyboard=kb_time, resize_keyboard=True, one_time_keyboard=True)

# --- START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Твой трекер готов.", reply_markup=main_keyboard)

# ==========================================
# БЛОК 1: УПРАВЛЕНИЕ ПРИВЫЧКАМИ (Стандарт)
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
    answer = message.text
    final_time = "Без напоминаний" if answer == "Не напоминать 🔕" else answer
    if final_time != "Без напоминаний" and ":" not in final_time: return await message.answer("❌ Формат ЧЧ:ММ")
    data = await state.get_data()
    add_habit(message.from_user.id, data['habit_name'], data['habit_freq'], final_time)
    await state.clear()
    await message.answer(f"✅ '{data['habit_name']}' сохранена!", reply_markup=main_keyboard)

@dp.message(F.text == "Мои привычки 📋")
async def show_habits_menu(message: types.Message):
    habits = get_all_user_habits(message.from_user.id)
    if not habits: return await message.answer("Список пуст.", reply_markup=main_keyboard)
    text_report = "<b>Твои привычки:</b>\n\n"
    keyboard_buttons = []
    # h[0]=id, h[1]=name, h[2]=freq, h[3]=time
    for h in habits:
        text_report += f"🔹 <b>{h[1]}</b> ({h[2]}) — ⏰ {h[3]}\n"
        keyboard_buttons.append([InlineKeyboardButton(text=f"⚙️ {h[1]}", callback_data=f"open_{h[0]}")])
    await message.answer(text_report, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons), parse_mode="HTML")

# Кнопки редактирования (Удалить / Время)
@dp.callback_query(F.data.startswith("open_"))
async def open_habit_options(callback: CallbackQuery):
    habit_id = callback.data.split("_")[1]
    name = get_habit_name(habit_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Время", callback_data=f"edittime_{habit_id}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_{habit_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_list")]
    ])
    await callback.message.edit_text(f"Настройка: <b>{name}</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    await callback.message.delete()
    await show_habits_menu(callback.message)

@dp.callback_query(F.data.startswith("del_"))
async def delete_habit_handler(callback: CallbackQuery):
    delete_habit(callback.data.split("_")[1])
    await callback.message.edit_text("✅ Удалено.")

@dp.callback_query(F.data.startswith("edittime_"))
async def edit_time_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_habit_id=callback.data.split("_")[1])
    await state.set_state(EditForm.waiting_for_new_time)
    await callback.message.answer("Новое время:", reply_markup=ReplyKeyboardRemove())
    await callback.answer()

@dp.message(EditForm.waiting_for_new_time)
async def edit_time_finish(message: types.Message, state: FSMContext):
    if ":" not in message.text and message.text != "Без напоминаний": return await message.answer("❌ Формат ЧЧ:ММ")
    data = await state.get_data()
    update_habit_time(data['editing_habit_id'], message.text)
    await state.clear()
    await message.answer(f"✅ Время обновлено!", reply_markup=main_keyboard)

# ==========================================
# БЛОК 2: КРАСИВАЯ СТАТИСТИКА
# ==========================================

@dp.message(F.text == "Моя статистика 📊")
async def show_detailed_stats(message: types.Message):
    habits = get_all_user_habits(message.from_user.id)
    if not habits: return await message.answer("Нет данных.")
    
    report = "<b>📊 Твоя эффективность:</b>\n\n"
    # h[1]=name, h[4]=done, h[5]=skip, h[6]=start_date
    for h in habits:
        done = h[4]; skip = h[5]; total = done + skip
        percent = int((done/total)*100) if total > 0 else 0
        bars = "🟩" * (percent // 10) + "⬜" * ((100 - percent) // 10)
        
        report += (
            f"🔹 <b>{h[1]}</b>\n"
            f"📅 Старт: {h[6]}\n"
            f"✅ Выполнено: {done} | ❌ Пропущено: {skip}\n"
            f"📈 Успех: {percent}%\n"
            f"{bars}\n\n"
        )
    await message.answer(report, parse_mode="HTML")

# ==========================================
# БЛОК 3: ИНТЕГРАЦИИ (МАСТЕР НАСТРОЙКИ)
# ==========================================

@dp.message(F.text == "Интеграции ⚙️")
async def integrations_menu(message: types.Message):
    # Проверяем, подключено ли уже
    current_link = get_user_sheet(message.from_user.id)
    status = "✅ Подключено" if current_link else "❌ Не подключено"
    
    text = f"<b>Настройки интеграций</b>\nСтатус Google Sheets: {status}\n\nКуда хочешь сохранять отчеты?"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Google Sheets", callback_data="setup_google")],
        [InlineKeyboardButton(text="🔜 Notion (скоро)", callback_data="dummy_notion")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# Шаг 1: Инструкция
@dp.callback_query(F.data == "setup_google")
async def setup_google_step1(callback: CallbackQuery):
    bot_email = get_bot_email()
    text = (
        "<b>Настройка Google Sheets 📄</b>\n\n"
        "1. Создай новую таблицу (или открой существующую).\n"
        "2. Нажми <b>Настройки доступа</b> (Share).\n"
        "3. Добавь этого бота как <b>Редактора</b>:\n"
    )
    # Отправляем инструкцию
    await callback.message.edit_text(text, parse_mode="HTML")
    
    # Отправляем Email отдельным сообщением для копирования
    await callback.message.answer(f"`{bot_email}`", parse_mode="MarkdownV2")
    
    # Кнопка подтверждения
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я добавил бота, дальше", callback_data="setup_google_step2")]])
    await callback.message.answer("Когда добавишь бота, нажми кнопку:", reply_markup=kb)

# Шаг 2: Запрос ссылки
@dp.callback_query(F.data == "setup_google_step2")
async def setup_google_step2(callback: CallbackQuery, state: FSMContext):
    await state.set_state(IntegrationSetup.waiting_for_link)
    await callback.message.answer(
        "Отлично! Теперь пришли мне <b>ссылку</b> на эту таблицу.\n"
        "(Просто скопируй из адресной строки браузера)", 
        parse_mode="HTML"
    )

# Шаг 3: Проверка и сохранение
@dp.message(IntegrationSetup.waiting_for_link)
async def setup_google_finish(message: types.Message, state: FSMContext):
    link = message.text.strip()
    
    msg = await message.answer("Проверяю доступ... 🔄")
    
    if check_sheet_access(link):
        set_user_sheet(message.from_user.id, link)
        await msg.edit_text(f"✅ <b>Успешно!</b>\nТаблица подключена.\nТеперь все отчеты летят туда.")
    else:
        await msg.edit_text(
            "❌ <b>Ошибка доступа.</b>\n"
            "Я не могу открыть эту таблицу. Проверь:\n"
            "1. Ты точно добавил бота в Редакторы?\n"
            "2. Ссылка правильная?\n\n"
            "Попробуй прислать ссылку еще раз или нажми /start для выхода."
        )
        return # Не сбрасываем состояние, ждем новую ссылку

    await state.clear()


# --- ОТЧЕТЫ (Callback) ---
@dp.callback_query(F.data.startswith("done_") | F.data.startswith("skip_"))
async def process_habit_action(callback: CallbackQuery):
    action, habit_id = callback.data.split("_")
    habit_name = get_habit_name(habit_id)
    is_done = (action == "done")
    
    update_habit_stats(habit_id, is_done)
    
    status_text = "ВЫПОЛНЕНО" if is_done else "ПРОПУЩЕНО"
    sheet_link = get_user_sheet(callback.from_user.id)
    google_res = write_to_sheet(sheet_link, habit_name, status_text) if sheet_link else ""
    
    # Красивый ответ без спама текстом про таблицу, если она не подключена
    icon = "✅ Молодец!" if is_done else "😴 Эх..."
    if sheet_link and "Записано" in google_res:
        new_text = f"{icon} (Сохранено в Google)"
    else:
        new_text = f"{icon}"
        
    await callback.message.edit_text(new_text)

# --- РАССЫЛКА ---
async def check_reminders():
    habits = get_habits_by_time(datetime.now().strftime("%H:%M"))
    for hid, uid, hname in habits:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сделано ✅", callback_data=f"done_{hid}"), InlineKeyboardButton(text="Пропуск ❌", callback_data=f"skip_{hid}")]])
        try: await bot.send_message(uid, f"🔔 <b>Пора: {hname}</b>", reply_markup=kb, parse_mode="HTML")
        except: pass

async def main():
    init_db()
    scheduler.add_job(check_reminders, 'cron', minute='*')
    scheduler.start()
    print("🤖 Бот (Версия: Интеграции + Статистика) запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass