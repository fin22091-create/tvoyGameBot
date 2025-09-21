import time
time.sleep(10) 
# ждем 10 секунд перед запуском
import threading
import random
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask
from telebot import types
import logging
import os

# =======================
# 🔧 НАСТРОЙКИ
# =======================

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен. Добавь его в Environment Variables.")

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не установлен. Добавь его в Environment Variables.")

bot = telebot.TeleBot(TOKEN)

# =======================
# 🗃️ ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# =======================

def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            best_score INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    cursor.close()
    conn.close()

# =======================
# 💾 ФУНКЦИИ РАБОТЫ С БАЗОЙ
# =======================

def save_user(user_id, name):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, name, best_score)
        VALUES (%s, %s, COALESCE((SELECT best_score FROM users WHERE user_id = %s), 0))
        ON CONFLICT (user_id) DO UPDATE
        SET name = EXCLUDED.name
    ''', (user_id, name, user_id))
    conn.commit()
    cursor.close()
    conn.close()

def update_score(user_id, attempts):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('SELECT best_score FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    current_best = result[0] if result and result[0] > 0 else None

    if not current_best or attempts < current_best:
        cursor.execute('UPDATE users SET best_score = %s WHERE user_id = %s', (attempts, user_id))

    conn.commit()
    cursor.close()
    conn.close()

def get_user_score(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('SELECT best_score FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

def get_top_players(limit=10):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('''
        SELECT name, best_score
        FROM users
        WHERE best_score > 0
        ORDER BY best_score ASC
        LIMIT %s
    ''', (limit,))
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

# =======================
# 🤖 ЛОГИКА БОТА
# =======================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    save_user(user_id, name)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn1 = types.KeyboardButton("🎮 Начать игру")
    btn2 = types.KeyboardButton("🏆 Мой счёт")
    btn3 = types.KeyboardButton("🏅 Топ-10")
    markup.add(btn1, btn2, btn3)

    bot.send_message(
        message.chat.id,
        f"Привет, {name}! Я загадаю число от 1 до 100 — попробуй угадать!\nЖми 'Начать игру'.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == "🎮 Начать игру")
def start_game(message):
    user_id = message.from_user.id
    bot.current_number = random.randint(1, 100)
    bot.attempts = 0
    bot.send_message(message.chat.id, "Я загадал число от 1 до 100. Какое число?")
    bot.register_next_step_handler(message, guess_number)

def guess_number(message):
    user_id = message.from_user.id
    try:
        guess = int(message.text)
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введи число!")
        bot.register_next_step_handler(message, guess_number)
        return

    bot.attempts += 1

    if guess < bot.current_number:
        bot.reply_to(message, "Больше! 📈")
        bot.register_next_step_handler(message, guess_number)
    elif guess > bot.current_number:
        bot.reply_to(message, "Меньше! 📉")
        bot.register_next_step_handler(message, guess_number)
    else:
        bot.reply_to(message, f"🎉 Поздравляю! Ты угадал за {bot.attempts} попыток!")
        update_score(user_id, bot.attempts)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn1 = types.KeyboardButton("🎮 Сыграть ещё")
        btn2 = types.KeyboardButton("🏆 Мой счёт")
        btn3 = types.KeyboardButton("🏅 Топ-10")
        markup.add(btn1, btn2, btn3)

        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🏆 Мой счёт")
def show_score(message):
    user_id = message.from_user.id
    score = get_user_score(user_id)

    if score and score > 0:
        bot.reply_to(message, f"🏆 Твой лучший результат: {score} попыток")
    else:
        bot.reply_to(message, "Ты ещё не угадал число. Нажми 'Начать игру'!")

@bot.message_handler(func=lambda message: message.text == "🎮 Сыграть ещё")
def play_again(message):
    start_game(message)

@bot.message_handler(commands=['top'])
@bot.message_handler(func=lambda message: message.text == "🏅 Топ-10")
def show_top_players(message):
    results = get_top_players(10)

    if not results:
        bot.reply_to(message, "Пока нет рекордов. Сыграй и установи свой!")
        return

    text = "🏆 *ТОП-10 ЛУЧШИХ ИГРОКОВ*\n\n"
    for i, row in enumerate(results, 1):
        text += f"{i}. {row['name']} — {row['best_score']} попыток\n"

    bot.reply_to(message, text, parse_mode="Markdown")

# =======================
# 🌐 ВЕБ-СЕРВЕР (чтобы Render не ругался)
# =======================

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Telegram Bot with PostgreSQL is running! Port is open.", 200

@app.route('/health')
def health():
    return {"status": "ok", "message": "Game bot with DB is alive"}, 200

# =======================
# 🚀 ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ
# =======================

def run_bot():
    time.sleep(10)  # Даём время на завершение предыдущего процесса
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
    except Exception as e:
        logging.error(f"❌ Ошибка бота: {e}")

# =======================
# 📊 ЛОГИРОВАНИЕ
# =======================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =======================
# ▶️ ЗАПУСК
# =======================

if __name__ == '__main__':
    init_db()  # Инициализируем базу
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    PORT = int(os.environ.get('PORT', 5000))
    logging.info(f"🌐 Запуск веб-сервера на порту {PORT}...")
    app.run(host='0.0.0.0', port=PORT)
