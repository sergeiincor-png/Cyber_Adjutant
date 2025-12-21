import telebot
import google.generativeai as genai
import os
from flask import Flask
from threading import Thread

# --- 1. ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (для Timeweb) ---
app = Flask('')

@app.route('/')
def home():
    return "Бот работает!"

def run():
    # Timeweb будет обращаться к этому порту, чтобы не выключать контейнер
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- 2. НАСТРОЙКА КЛЮЧЕЙ И МОДЕЛЕЙ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    print("❌ ОШИБКА: Проверь переменные окружения TELEGRAM_TOKEN и GEMINI_API_KEY")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Словарь для хранения истории чатов
user_chats = {}

# --- 3. ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    
    # Создаем сессию чата, если её еще нет
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])

    try:
        # Показываем статус "печает..."
        bot.send_chat_action(user_id, 'typing')
        
        # Отправляем запрос в нейросеть
        chat = user_chats[user_id]
        response = chat.send_message(message.text)
        full_text = response.text

        # Разбиваем ответ, если он длиннее 4096 символов (лимит Telegram)
        if len(full_text) > 4000:
            for i in range(0, len(full_text), 4000):
                bot.send_message(user_id, full_text[i:i+4000])
        else:
            bot.reply_to(message, full_text)

    except Exception as e:
        print(f"Ошибка: {e}")
        bot.reply_to(message, "Произошла ошибка при генерации ответа.")

# --- 4. ЗАПУСК ВСЕЙ СИСТЕМЫ ---
if __name__ == "__main__":
    # Сначала запускаем Flask в фоне
    keep_alive()
    print("🚀 Веб-сервер запущен на порту 8080")
    
    # Затем запускаем Telegram бота
    print("🤖 Бот запущен и готов к работе!")
    bot.polling(none_stop=True)
