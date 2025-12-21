import telebot
import google.generativeai as genai
import os

# --- ПОЛУЧЕНИЕ КЛЮЧЕЙ ИЗ НАСТРОЕК СЕРВЕРА (Timeweb) ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Проверка, что ключи успешно загрузились
if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    # Если ключей нет, бот выдаст ошибку в логах и остановится
    raise ValueError("ОШИБКА: Ключи не найдены. Укажите TELEGRAM_TOKEN и GEMINI_API_KEY в переменных окружения Timeweb.")

# --- НАСТРОЙКА GEMINI И TELEGRAM ---
genai.configure(api_key=GEMINI_API_KEY)
# Используем модель flash, она быстрее и дешевле для чатов
model = genai.GenerativeModel('gemini-1.5-flash')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Хранилище памяти (словарь: ID пользователя -> Объект чата)
user_chats = {}

print("Бот успешно запущен и ждет сообщений...")

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    # Создаем новую историю диалога для пользователя
    user_chats[user_id] = model.start_chat(history=[])
    
    welcome_text = (
        "Привет! Я твой AI-помощник на базе Gemini.\n"
        "Я помню контекст нашего диалога.\n"
        "Если захочешь сменить тему и очистить память, напиши /reset"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['reset'])
def reset_memory(message):
    user_id = message.chat.id
    # Перезаписываем чат на новый (пустой)
    user_chats[user_id] = model.start_chat(history=[])
    bot.reply_to(message, "🗑 Память очищена. Можем начать новую тему!")

# --- ОБРАБОТЧИК ТЕКСТА ---

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    
    # Если бот перезагружался, создаем чат заново, чтобы не было ошибки
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])

    try:
        # Показываем статус "печатает..."
        bot.send_chat_action(user_id, 'typing')
        
        # Получаем текущую сессию пользователя
        chat = user_chats[user_id]
        
        # Отправляем сообщение в Gemini
        response = chat.send_message(message.text)
        
        # Отправляем ответ пользователю.
        # Используем Markdown для красивого форматирования (жирный шрифт и т.д.)
        bot.reply_to(message, response.text, parse_mode='Markdown')

    except Exception as e:
        error_message = "Произошла ошибка. Возможно, текст слишком длинный или сработали фильтры безопасности."
        bot.reply_to(message, error_message)
        print(f"Error for user {user_id}: {e}")

# Запуск бота в бесконечном режиме
bot.polling(non_stop=True)