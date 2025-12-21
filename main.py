import telebot
import google.generativeai as genai
import os
from flask import Flask  # <-- Добавили Flask
from threading import Thread # <-- Добавили потоки

# --- 1. НАСТРОЙКА "ФЕЙКОВОГО" ВЕБ-СЕРВЕРА ---
# Это нужно, чтобы Timeweb не убивал бота
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

def run_web_server():
    # Запускаем сервер на порту 80 или том, который даст Timeweb
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- 2. НАСТРОЙКИ БОТА ---
TELEGRAM_TOKEN = "8257461303:AAE1FQv_BPStOqxOx_28KSrCP_xytReE7Ck"
GEMINI_API_KEY = "AIzaSyB_DKI4PQHl5_-CeUTpXOneMGq0f37q1Sw"

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("ОШИБКА: Нет ключей в переменных окружения.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')
bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

print("Бот готовится к запуску...")

# --- 3. ЛОГИКА БОТА ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    user_chats[user_id] = model.start_chat(history=[])
    bot.reply_to(message, "Привет! Я твой AI-ассистент. Пиши, я отвечу.")

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    user_id = message.chat.id
    user_chats[user_id] = model.start_chat(history=[])
    bot.reply_to(message, "Память очищена.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])

    try:
        bot.send_chat_action(user_id, 'typing')
        chat = user_chats[user_id]
        response = chat.send_message(message.text)
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, "Ошибка обработки запроса.")
        print(f"Error: {e}")

# --- 4. ЗАПУСК ВСЕГО ВМЕСТЕ ---
def run_bot():
    bot.polling(non_stop=True)

if __name__ == '__main__':
    # Запускаем веб-сервер в отдельном потоке
    # 👇 Дописываем сюда daemon=True
    t = Thread(target=run_web_server, daemon=True) 
    t.start()
    
    # Запускаем бота в основном потоке
    run_bot()



