import os
import time
import telebot
from flask import Flask
from threading import Thread
from google import genai

# --- 1) ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (если тебе нужно для healthcheck/ping) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает!"

def run_web():
    # Если Timeweb/балансер пингует порт — ок.
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

# --- 2) КЛЮЧИ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise RuntimeError("Проверь переменные окружения TELEGRAM_TOKEN и GEMINI_API_KEY")

# --- 3) GEMINI (НОВЫЙ SDK) ---
client = genai.Client(api_key=GEMINI_API_KEY)

# Выбираем актуальную модель.
# Если вдруг на твоём ключе она недоступна — будет fallback ниже.
MODEL_CANDIDATES = [
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
]

# --- 4) TELEGRAM ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

# История диалогов (храним последние N сообщений на пользователя)
user_history = {}
HISTORY_LIMIT = 12  # 6 реплик пользователя + 6 ответов бота

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram. Отвечай кратко и по делу. "
    "Если вопрос непонятен — задай 1 уточняющий вопрос."
)

def gemini_answer(user_id: int, user_text: str) -> str:
    # Собираем контекст: system + история + новое сообщение
    history = user_history.get(user_id, [])
    contents = [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        *history,
        {"role": "user", "parts": [{"text": user_text}]},
    ]

    last_error = None

    for model_name in MODEL_CANDIDATES:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
            )
            text = (resp.text or "").strip()
            if text:
                # сохраняем историю
                new_history = history + [
                    {"role": "user", "parts": [{"text": user_text}]},
                    {"role": "model", "parts": [{"text": text}]},
                ]
                user_history[user_id] = new_history[-HISTORY_LIMIT:]
                return text

            last_error = RuntimeError(f"Пустой ответ от модели {model_name}")

        except Exception as e:
            last_error = e

    # Если ни одна модель не сработала — отдаём понятную ошибку (и логируем)
    raise RuntimeError(f"Gemini не ответил. Последняя ошибка: {type(last_error).__name__}: {last_error}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    text = (message.text or "").strip()
    if not text:
        bot.reply_to(message, "Пришли текстом 🙂")
        return

    try:
        bot.send_chat_action(user_id, "typing")

        answer = gemini_answer(user_id, text)

        # Telegram лимит ~4096, режем безопасно
        chunk_size = 4000
        for i in range(0, len(answer), chunk_size):
            bot.send_message(user_id, answer[i:i + chunk_size])

    except Exception as e:
        # ВАЖНО: временно показываем короткую причину, чтобы ты видел, что именно ломается
        err = f"{type(e).__name__}: {e}"
        print("❌ Gemini error:", err)
        bot.reply_to(message, "Gemini сейчас не отвечает. Ошибка: " + err[:250])

if __name__ == "__main__":
    keep_alive()
    print("🚀 Web healthcheck on :8080")
    print("🤖 Bot is running (polling)...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
