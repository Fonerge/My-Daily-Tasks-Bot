import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
import threading

API_TOKEN = '8181951037:AAFkmw8bJNC7Uo2gLoxaPO9myMolpO6Qp2o'
bot = telebot.TeleBot(API_TOKEN)

# Локальное время
TIMEZONE = pytz.timezone('Europe/Istanbul')  # замени на свой регион

# Flask-сервер
app = Flask(__name__)

@app.route('/')
def index():
    return 'OK'

# Запуск Flask в отдельном потоке
def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# База
conn = sqlite3.connect('bot.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS task_log (
    user_id INTEGER,
    task_time TEXT,
    status TEXT,
    date TEXT
)''')
conn.commit()

# Твои задачи (время, текст)
tasks = [
    ("09:05", "Ты проснулся? Иди в туалет, пей воду и кофе."),
    ("09:30", "Дыхательная практика."),
    ("09:45", "Освежающий душ."),
    ("10:15", "Готовь завтрак."),
    ("11:00", "Начинаем работу в программировании."),
    ("13:00", "Перерыв, кушаем или готовим."),
    ("14:00", "Продолжаем программировать."),
    ("16:00", "Смотрим дела по другим задачам."),
    ("18:00", "Учим английский."),
    ("20:00", "Проверяем квартиру, еду, кошачий лоток."),
    ("22:30", "Можно YouTube, кино или игры 🎮")
]

# Команды
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    bot.send_message(user_id, "Привет! Я твой ассистент по дисциплине. Буду напоминать тебе о задачах!")

@bot.message_handler(commands=['profile'])
def profile(message):
    user_id = message.chat.id
    today = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    xp = cursor.fetchone()[0]
    cursor.execute("SELECT task_time FROM task_log WHERE user_id = ? AND date = ? AND status IS NULL", (user_id, today))
    pending = cursor.fetchall()
    pending_list = [t[0] for t in pending]
    text = f"🌟 XP: {xp}\n📅 Осталось задач сегодня: {len(pending_list)}\n\n⏳ Задачи:\n" + '\n'.join(pending_list)
    bot.send_message(user_id, text)

# Отправка задач
def send_task(user_id, task_time, text):
    date = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM task_log WHERE user_id=? AND task_time=? AND date=?", (user_id, task_time, date))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO task_log (user_id, task_time, date) VALUES (?, ?, ?)", (user_id, task_time, date))
        conn.commit()
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ Выполнено", callback_data=f"done|{task_time}"),
            InlineKeyboardButton("❌ Пропущено", callback_data=f"skip|{task_time}")
        )
        bot.send_message(user_id, f"🕒 {task_time}\n{text}", reply_markup=markup)

# Колбэки на кнопки
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    user_id = call.message.chat.id
    data = call.data.split('|')
    action, task_time = data[0], data[1]
    date = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')

    if action == 'done':
        cursor.execute("UPDATE task_log SET status = 'done' WHERE user_id=? AND task_time=? AND date=?", (user_id, task_time, date))
        cursor.execute("UPDATE users SET xp = xp + 10 WHERE user_id=?", (user_id,))
        bot.answer_callback_query(call.id, f"✅ Выполнено! +10 XP.")
    elif action == 'skip':
        cursor.execute("UPDATE task_log SET status = 'skip' WHERE user_id=? AND task_time=? AND date=?", (user_id, task_time, date))
        bot.answer_callback_query(call.id, "❌ Пропущено.")
    conn.commit()

# Отчёт в конце дня
def send_daily_report():
    today = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    for (user_id,) in users:
        cursor.execute("SELECT COUNT(*) FROM task_log WHERE user_id=? AND date=? AND status='done'", (user_id, today))
        done = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM task_log WHERE user_id=? AND date=?", (user_id, today))
        total = cursor.fetchone()[0]
        bot.send_message(user_id, f"📊 Итоги за {today}:\n✅ Выполнено: {done}/{total}\n🌟 XP обновлён!")

# Планировщик
def schedule_all():
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    for user_id, in users:
        for task_time, text in tasks:
            hour, minute = map(int, task_time.split(":"))
            scheduler.add_job(send_task, 'cron', hour=hour, minute=minute, args=[user_id, task_time, text])

    # Отчёт вечером
    scheduler.add_job(send_daily_report, 'cron', hour=23, minute=59)
    scheduler.start()

# Старт
schedule_all()
bot.infinity_polling()
