import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import datetime
import threading
import time

# === Настройки ===
API_TOKEN = '8181951037:AAFkmw8bJNC7Uo2gLoxaPO9myMolpO6Qp2o'
CHAT_ID = None  # установим после /start
bot = telebot.TeleBot(API_TOKEN)

# === Подключение к базе данных ===
conn = sqlite3.connect('bot_db.sqlite', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS task_results (
    user_id INTEGER,
    task_time TEXT,
    status TEXT,
    date TEXT
)''')
conn.commit()

# === Расписание задач ===
tasks = [
    ("09:05", "Ты проснулся? Иди в туалет, пей воду и кофе ☕"),
    ("09:30", "Дыхательная практика 🌬️"),
    ("09:45", "Освежающий душ 🚿"),
    ("10:15", "Готовь завтрак 🍳"),
    ("11:00", "Начинаем работу в программировании 💻"),
    ("13:00", "Перерыв, кушаем или готовим 🍽️"),
    ("14:00", "Программируем 💻"),
    ("16:00", "Остановись, посмотри по другим делам 🧠"),
    ("18:00", "Учим английский 🇬🇧"),
    ("20:00", "Уборка, еда, кошачий лоток 🧹🐱"),
    ("22:30", "Время на кино, YouTube или игры 🎮")
]

# === Хелперы ===
def send_task(user_id, task_time, task_text):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Выполнено", callback_data=f"done|{task_time}"),
        InlineKeyboardButton("❌ Пропущено", callback_data=f"missed|{task_time}")
    )
    bot.send_message(user_id, f"🕒 {task_time}\n{task_text}", reply_markup=markup)


# === Команды ===
@bot.message_handler(commands=['start'])
def start(message):
    global CHAT_ID
    CHAT_ID = message.chat.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (CHAT_ID,))
    conn.commit()
    bot.send_message(message.chat.id, "Привет! Я твой ассистент по самоорганизации. Буду слать напоминания в течение дня.")

@bot.message_handler(commands=['profile'])
def profile(message):
    user_id = message.chat.id
    today = datetime.date.today().isoformat()
    cursor.execute("SELECT xp FROM users WHERE user_id=?", (user_id,))
    xp = cursor.fetchone()[0]

    cursor.execute("SELECT task_time FROM task_results WHERE user_id=? AND date=? AND status IS NULL", (user_id, today))
    pending_tasks = [row[0] for row in cursor.fetchall()]

    response = f"📊 Профиль:\nОпыт: {xp} XP\nЗадачи на сегодня, не отмеченные:\n" + "\n".join(pending_tasks) if pending_tasks else "Все задачи выполнены! 🔥"
    bot.send_message(user_id, response)


# === Обработка кнопок ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    action, task_time = call.data.split("|")
    today = datetime.date.today().isoformat()

    # Проверяем, уже ли отмечено
    cursor.execute("SELECT status FROM task_results WHERE user_id=? AND task_time=? AND date=?", (user_id, task_time, today))
    result = cursor.fetchone()
    if result and result[0] is not None:
        bot.answer_callback_query(call.id, "Уже отмечено")
        return

    status = "done" if action == "done" else "missed"
    cursor.execute("INSERT OR REPLACE INTO task_results (user_id, task_time, status, date) VALUES (?, ?, ?, ?)",
                   (user_id, task_time, status, today))

    if status == "done":
        cursor.execute("UPDATE users SET xp = xp + 10 WHERE user_id=?", (user_id,))

    conn.commit()
    bot.answer_callback_query(call.id, "Отмечено как " + ("выполнено" if status == "done" else "пропущено"))


# === Отчёт в конце дня ===
def send_daily_report():
    while True:
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute == 59:
            today = datetime.date.today().isoformat()
            cursor.execute("SELECT user_id FROM users")
            for (user_id,) in cursor.fetchall():
                cursor.execute("SELECT COUNT(*) FROM task_results WHERE user_id=? AND date=? AND status='done'", (user_id, today))
                done = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM task_results WHERE user_id=? AND date=?", (user_id, today))
                total = cursor.fetchone()[0] or len(tasks)
                bot.send_message(user_id, f"📅 Отчёт за {today}: выполнено {done} из {total} задач. Продолжай в том же духе! 💪")
            time.sleep(60)
        time.sleep(30)


# === Планировщик задач ===
def scheduler():
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        today = datetime.date.today().isoformat()
        for task_time, task_text in tasks:
            if now == task_time:
                cursor.execute("SELECT user_id FROM users")
                for (user_id,) in cursor.fetchall():
                    cursor.execute("INSERT OR IGNORE INTO task_results (user_id, task_time, status, date) VALUES (?, ?, NULL, ?)",
                                   (user_id, task_time, today))
                    conn.commit()
                    send_task(user_id, task_time, task_text)
        time.sleep(60)

# === Запуск в отдельных потоках ===
threading.Thread(target=scheduler, daemon=True).start()
threading.Thread(target=send_daily_report, daemon=True).start()

print("Бот запущен...")
bot.polling(none_stop=True)
