import telebot
import os
import threading
import random
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask
from telebot import types
import logging
import sys
from datetime import datetime, timedelta

# =======================
# 🚨 ПРОВЕРКА ЗАПУСКА
# =======================
print("🚀 Запуск Telegram-бота...", file=sys.stderr)

# =======================
# 🔧 НАСТРОЙКИ
# =======================
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен. Добавь его в Environment Variables на Render.")
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не установлен.")

bot = telebot.TeleBot(TOKEN, threaded=False)  # ← Важно: threaded=False

# Храним игру по user_id (вместо глобальных переменных!)
user_games = {}  # {user_id: {'number': 42, 'attempts': 3}}

# =======================
# 🗃️ ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# =======================
def init_db():
    try:
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
        print("✅ База данных инициализирована", file=sys.stderr)
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}", file=sys.stderr)
        raise

# =======================
# 💾 ФУНКЦИИ РАБОТЫ С БАЗОЙ
# =======================
def save_user(user_id, name):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, name, best_score)
            VALUES (%s, %s, COALESCE((SELECT best_score FROM users WHERE user_id = %s), 0))
            ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name
        ''', (user_id, name, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка сохранения пользователя: {e}", file=sys.stderr)

def update_score(user_id, attempts):
    try:
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
    except Exception as e:
        print(f"❌ Ошибка обновления счёта: {e}", file=sys.stderr)

def get_user_score(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('SELECT best_score FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        print(f"❌ Ошибка получения счёта: {e}", file=sys.stderr)
        return None

def get_top_players(limit=10):
    try:
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
    except Exception as e:
        print(f"❌ Ошибка получения топа: {e}", file=sys.stderr)
        return []

# =======================
# 🤖 ЛОГИКА БОТА
# =======================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    save_user(user_id, name)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
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
    secret_number = random.randint(1, 100)
    user_games[user_id] = {'number': secret_number, 'attempts': 0}
    bot.send_message(message.chat.id, "Я загадал число от 1 до 100. Какое число?")
    bot.register_next_step_handler(message, guess_number)

def guess_number(message):
    user_id = message.from_user.id
    if user_id not in user_games:
        bot.reply_to(message, "Сначала начни игру!")
        return

    try:
        guess = int(message.text)
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введи число!")
        bot.register_next_step_handler(message, guess_number)
        return

    game = user_games[user_id]
    game['attempts'] += 1

    if guess < game['number']:
        bot.reply_to(message, "Больше! 📈")
        bot.register_next_step_handler(message, guess_number)
    elif guess > game['number']:
        bot.reply_to(message, "Меньше! 📉")
        bot.register_next_step_handler(message, guess_number)
    else:
        bot.reply_to(message, f"🎉 Поздравляю! Ты угадал за {game['attempts']} попыток!")
        update_score(user_id, game['attempts'])
        user_games.pop(user_id, None)  # Удаляем игру
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
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
    text = "🏆 *ТОП-10 ЛУЧШИХ ИГРОКОВ*\n"
    for i, row in enumerate(results, 1):
        text += f"{i}. {row['name']} — {row['best_score']} попыток\n"
    bot.reply_to(message, text, parse_mode="Markdown")

# =======================
# 🌐 ВЕБ-СЕРВЕР (для Render)
# =======================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Telegram Bot is running!", 200

@app.route('/health')
def health():
    return {"status": "ok", "message": "Bot is alive"}, 200

# =======================
# 🚀 ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ
# =======================
def run_bot():
    try:
        print("🤖 Запуск бота...", file=sys.stderr)
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"❌ Ошибка бота: {e}", file=sys.stderr)

# =======================
# ▶️ ЗАПУСК
# =======================
if __name__ == '__main__':
    print("🔧 Инициализация базы данных...", file=sys.stderr)
    init_db()
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    PORT = int(os.environ.get('PORT', 5000))
    print(f"🌐 Запуск веб-сервера на порту {PORT}...", file=sys.stderr)
    app.run(host='0.0.0.0', port=PORT)