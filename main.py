import telebot
import google.generativeai as genai
import os
from flask import Flask
from threading import Thread
import time

# --- 1. ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (Keep-alive) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Статус: Бот активен и слушает серверы Telegram."

@app.route('/health')
def health():
    return {"status": "ok"}, 200

def run_web_server():
    # Timeweb обычно ожидает активность на порту 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- 2. НАСТРОЙКИ И ПРОВЕРКА КЛЮЧЕЙ ---
# Берем ключи из переменных окружения Timeweb
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Ключи не найдены в переменных окружения Timeweb!")
    # Для теста можно вписать сюда, но для продакшна лучше через env
    # TELEGRAM_TOKEN = "ваш_токен" 

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

# --- 3. ЛОГИКА БОТА ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    user_chats[user_id] = model.start_chat(history=[])
    bot.reply_to(message, "Привет! Я твой AI-ассистент на базе Gemini. Чем могу помочь?")

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    user_id = message.chat.id
    user_chats[user_id] = model.start_chat(history=[])
    bot.reply_to(message, "🧠 Память нашей беседы очищена.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    # Инициализация чата, если пользователя нет в памяти
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])

    try:
        bot.send_chat_action(user_id, 'typing')
        chat = user_chats[user_id]
        response = chat.send_message(message.text)
        bot.reply_to(message, response.text)
   except Exception as e:
        # Бот отправит текст самой ошибки вам в чат Telegram
        bot.reply_to(message, f"Техническая ошибка: {str(e)}")
        print(f"Error: {e}")

# --- 4. ЗАПУСК ---

def run_bot():
    # Важнейший шаг для исправления ошибки 409 Conflict:
    print("Очистка старых соединений...")
    bot.remove_webhook()
    time.sleep(1) 
    
    print("✅ Бот запущен!")
    # Используем infinity_polling для автоматического перезапуска при сбоях сети
    bot.infinity_polling(timeout=20, long_polling_timeout=5)

if __name__ == '__main__':
    # 1. Запускаем Flask в фоновом потоке
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()
    
    # 2. Запускаем бота в основном потоке
    try:
        run_bot()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        time.sleep(5) # Пауза перед возможным рестартом контейнера

