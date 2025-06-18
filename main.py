import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import logging 
from flask import Flask
import threading 
import os
from apscheduler.jobstores.base import JobLookupError 

API_TOKEN = os.getenv(BOT_API_KEY)
DB_NAME = 'my_daily_tasks_bot.db'
TIMEZONE_STR = 'Europe/Istanbul'
TIMEZONE = pytz.timezone(TIMEZONE_STR)
FLASK_PORT = 8080 

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(API_TOKEN)

TASKS_SCHEDULE = [
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

# --- База данных ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    logger.info("Инициализация базы данных...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        xp INTEGER DEFAULT 0
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS task_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_time TEXT,
        task_text TEXT,
        status TEXT,
        date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        UNIQUE(user_id, task_time, date)
    )''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_task_log_user_date_time
                      ON task_log (user_id, date, task_time)''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_task_log_user_date_status
                      ON task_log (user_id, date, status)''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована.")

# --- Вспомогательные функции для БД ---
def add_user_if_not_exists(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"Пользователь {user_id} добавлен или уже существует.")

def get_user_xp(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row['xp'] if row else 0

def update_user_xp(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET xp = xp + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    logger.info(f"XP пользователя {user_id} обновлен на {amount}.")

def log_task_event(user_id, task_time, task_text, date_str, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO task_log (user_id, task_time, task_text, date, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, task_time, date) DO UPDATE SET status = excluded.status
    """, (user_id, task_time, task_text, date_str, status))
    conn.commit()
    conn.close()
    logger.info(f"Статус задачи {task_time} для {user_id} на {date_str} обновлен на {status}.")

def ensure_daily_tasks_logged(user_id, date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    for task_time, task_text in TASKS_SCHEDULE:
        cursor.execute("""
            INSERT OR IGNORE INTO task_log (user_id, task_time, task_text, date, status)
            VALUES (?, ?, ?, ?, NULL)
        """, (user_id, task_time, task_text, date_str))
    conn.commit()
    conn.close()
    logger.debug(f"Проверено наличие ежедневных задач в логе для {user_id} на {date_str}.")


def get_pending_tasks_for_user_today(user_id):
    today_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    ensure_daily_tasks_logged(user_id, today_str)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_time, task_text FROM task_log
        WHERE user_id = ? AND date = ? AND status IS NULL
        ORDER BY task_time ASC
    """, (user_id, today_str))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

# --- Клавиатуры ---
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(KeyboardButton("👤 Профиль"))
    return markup

# --- Планировщик ---
scheduler = BackgroundScheduler(timezone=TIMEZONE_STR)

# --- Flask для UptimeRobot ---
flask_app = Flask(__name__)

@flask_app.route('/')
def index_flask(): # Переименовал в index_flask во избежание конфликта имен, если бы был другой index
    return 'MyDailyTasksBot is running!'

def run_flask():
    logger.info(f"Запуск Flask для keep-alive на порту {FLASK_PORT}...")
    try:
        flask_app.run(host="0.0.0.0", port=FLASK_PORT, use_reloader=False) # use_reloader=False важен при запуске в потоке
    except Exception as e:
        logger.error(f"Ошибка при запуске Flask: {e}", exc_info=True)

# --- Хэндлеры Telegram ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.chat.id
    add_user_if_not_exists(user_id)
    logger.info(f"Команда /start от пользователя {user_id}.")

    bot.send_message(user_id,
                     "🧠 Привет! Я твой ассистент по дисциплине My Daily Tasks Bot. Буду напоминать тебе о задачах каждый день!",
                     reply_markup=get_main_keyboard())

    current_date = datetime.datetime.now(TIMEZONE).date()
    schedule_user_tasks_for_day(user_id, current_date)

@bot.message_handler(func=lambda m: m.text == "👤 Профиль" or m.text == "/profile")
def profile_cmd(message):
    user_id = message.chat.id
    logger.info(f"Запрос профиля от пользователя {user_id}.")
    xp = get_user_xp(user_id)
    pending_tasks = get_pending_tasks_for_user_today(user_id)

    text = f"👤 Ваш профиль:\n\n🌟 XP: {xp}\n\n"
    if pending_tasks:
        text += f"⏳ Оставшиеся задачи на сегодня ({len(pending_tasks)}):\n"
        for task in pending_tasks:
            text += f"  - {task['task_time']} {task['task_text']}\n"
    else:
        text += "🎉 Все задачи на сегодня выполнены или еще не наступили!"
    bot.send_message(user_id, text, reply_markup=get_main_keyboard())

# --- Логика отправки задач и планирования ---
def send_task_notification(user_id, task_time, task_text):
    try:
        today_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM task_log WHERE user_id=? AND task_time=? AND date=?",
                       (user_id, task_time, today_str))
        row = cursor.fetchone()
        conn.close()

        if row and row['status'] in ('done', 'skip'):
            logger.info(f"Задача {task_time} для {user_id} уже обработана ({row['status']}), не отправляем уведомление.")
            return

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ Выполнено", callback_data=f"task_done|{task_time}"),
            InlineKeyboardButton("❌ Пропущено", callback_data=f"task_skip|{task_time}")
        )
        bot.send_message(user_id, f"🔔 Напоминание!\n🕒 {task_time}\n\n{task_text}", reply_markup=markup)
        logger.info(f"Уведомление о задаче {task_time} отправлено пользователю {user_id}.")
    except Exception as e:
        logger.error(f"Ошибка при отправке задачи {task_time} пользователю {user_id}: {e}", exc_info=True)

def schedule_user_tasks_for_day(user_id, date_obj):
    logger.info(f"Планирование задач для пользователя {user_id} на дату {date_obj.strftime('%Y-%m-%d')}.")
    date_str = date_obj.strftime('%Y-%m-%d')
    ensure_daily_tasks_logged(user_id, date_str)

    now_datetime_aware = datetime.datetime.now(TIMEZONE)

    for task_time_str, task_text in TASKS_SCHEDULE:
        hour, minute = map(int, task_time_str.split(':'))
        task_datetime_naive = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute)
        task_datetime_aware = TIMEZONE.localize(task_datetime_naive)

        if task_datetime_aware >= now_datetime_aware or date_obj > now_datetime_aware.date():
            job_id = f"task_{user_id}_{date_str}_{task_time_str.replace(':', '')}"
            try:
                scheduler.add_job(send_task_notification,
                                  'cron',
                                  hour=hour,
                                  minute=minute,
                                  args=[user_id, task_time_str, task_text],
                                  id=job_id,
                                  replace_existing=True,
                                  misfire_grace_time=300)
                logger.debug(f"Запланирована задача: {job_id} на {task_time_str} ({date_str})")
            except Exception as e:
                logger.error(f"Ошибка планирования задачи {job_id}: {e}", exc_info=True)
        else:
            logger.debug(f"Задача {task_time_str} для {user_id} на {date_str} уже прошла, не планируем.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('task_'))
def task_callback(call):
    user_id = call.message.chat.id
    try:
        action_type, task_time = call.data.split('|')
        date_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        logger.info(f"Колбэк получен: {call.data} от пользователя {user_id}.")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT task_text FROM task_log WHERE user_id=? AND task_time=? AND date=?",
                       (user_id, task_time, date_str))
        row = cursor.fetchone()
        conn.close()

        if not row:
            logger.warning(f"Не найдена задача в логе для колбэка: {call.data}, user {user_id}, date {date_str}")
            bot.answer_callback_query(call.id, "Не удалось найти задачу. Возможно, она устарела.")
            return

        task_text = row['task_text']

        if action_type == 'task_done':
            log_task_event(user_id, task_time, task_text, date_str, 'done')
            update_user_xp(user_id, 10)
            bot.answer_callback_query(call.id, "✅ Выполнено! +10 XP.")
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text=f"👍 Задача выполнена:\n🕒 {task_time}\n\n{task_text}", reply_markup=None)
        elif action_type == 'task_skip':
            log_task_event(user_id, task_time, task_text, date_str, 'skip')
            bot.answer_callback_query(call.id, "❌ Пропущено.")
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text=f"😔 Задача пропущена:\n🕒 {task_time}\n\n{task_text}", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка обработки колбэка {call.data}: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке вашего ответа.")

# --- Ежедневные задачи планировщика ---
def schedule_tasks_for_all_users_for_today_on_startup():
    logger.info("Первоначальное планирование задач на сегодня для всех существующих пользователей...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    today_date = datetime.datetime.now(TIMEZONE).date()
    for user_row in users:
        schedule_user_tasks_for_day(user_row['user_id'], today_date)
    logger.info(f"Завершено первоначальное планирование для {len(users)} пользователей.")

def schedule_tasks_for_all_users_for_next_day_job():
    logger.info("Ежедневное задание: планирование задач на следующий день...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    next_day_date = (datetime.datetime.now(TIMEZONE) + datetime.timedelta(days=1)).date()
    for user_row in users:
        schedule_user_tasks_for_day(user_row['user_id'], next_day_date)
    logger.info(f"Завершено планирование на следующий день для {len(users)} пользователей.")

def send_daily_report_job():
    logger.info("Ежедневное задание: отправка отчета за прошедший день...")
    report_date = (datetime.datetime.now(TIMEZONE) - datetime.timedelta(days=1)).date()
    report_date_str = report_date.strftime('%Y-%m-%d')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users_rows = cursor.fetchall()

    for user_row in users_rows:
        user_id = user_row['user_id']
        cursor.execute("SELECT COUNT(*) as cnt FROM task_log WHERE user_id=? AND date=?",
                       (user_id, report_date_str))
        total_logged_for_day = cursor.fetchone()['cnt']

        if total_logged_for_day == 0:
            logger.info(f"Для пользователя {user_id} нет залогированных задач за {report_date_str}. Отчет не отправляется.")
            continue

        cursor.execute("SELECT COUNT(*) as cnt FROM task_log WHERE user_id=? AND date=? AND status='done'",
                       (user_id, report_date_str))
        done_count = cursor.fetchone()['cnt']
        total_scheduled_tasks = len(TASKS_SCHEDULE)
        xp = get_user_xp(user_id)

        try:
            bot.send_message(user_id,
                             f"📊 Итоги за {report_date_str}:\n\n"
                             f"✅ Выполнено задач: {done_count} из {total_scheduled_tasks}\n"
                             f"🌟 Ваш текущий XP: {xp}\n\n"
                             "Новый день - новые цели! 💪")
            logger.info(f"Отчет за {report_date_str} отправлен пользователю {user_id}.")
        except Exception as e:
            logger.error(f"Не удалось отправить отчет пользователю {user_id} за {report_date_str}: {e}", exc_info=True)

    conn.close()
    logger.info("Отправка ежедневных отчетов завершена.")


# --- Запуск бота ---
if __name__ == '__main__':
    init_db()

    # Запуск Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    scheduler.add_job(schedule_tasks_for_all_users_for_next_day_job, 'cron', hour=0, minute=1, timezone=TIMEZONE_STR, id='schedule_next_day', replace_existing=True)
    scheduler.add_job(send_daily_report_job, 'cron', hour=0, minute=5, timezone=TIMEZONE_STR, id='daily_report', replace_existing=True)

    scheduler.start()
    logger.info("Планировщик запущен.")

    schedule_tasks_for_all_users_for_today_on_startup()

    logger.info("Бот My Daily Tasks Bot запускается...")
    try:
        bot.infinity_polling(timeout=120, logger_level=logging.INFO, skip_pending=True)
    except Exception as e:
        logger.critical(f"Критическая ошибка в работе бота: {e}", exc_info=True)
    finally:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Планировщик остановлен.")
        logger.info("Бот My Daily Tasks Bot остановлен.")
