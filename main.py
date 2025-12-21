import os
import telebot
from flask import Flask
from threading import Thread

from google import genai
from google.genai import types


# --- 1) ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (healthcheck/ping) ---
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
# КРИТИЧНО: фикс 404 “not found for API version v1beta”
# Принудительно используем стабильный API v1.
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(api_version="v1")
)

def pick_model_name() -> str:
    """
    Выбираем первую доступную модель, которая поддерживает generateContent.
    Это надежнее, чем угадывать имя модели.
    """
    last = None
    try:
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or getattr(m, "supportedActions", []) or []
            if "generateContent" in actions:
                # SDK часто возвращает 'models/....' — убираем префикс
                return (m.name or "").replace("models/", "")
        last = "Список моделей получен, но ни одна не поддерживает generateContent."
    except Exception as e:
        last = f"{type(e).__name__}: {e}"

    raise RuntimeError(f"Не нашёл ни одной модели с generateContent для этого ключа. Детали: {last}")

MODEL_NAME = pick_model_name()
print("✅ Using model:", MODEL_NAME)


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
    history = user_history.get(user_id, [])
    contents = [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        *history,
        {"role": "user", "parts": [{"text": user_text}]},
    ]

    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
    )

    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Gemini вернул пустой ответ.")

    # сохраняем историю
    new_history = history + [
        {"role": "user", "parts": [{"text": user_text}]},
        {"role": "model", "parts": [{"text": text}]},
    ]
    user_history[user_id] = new_history[-HISTORY_LIMIT:]

    return text


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
        err = f"{type(e).__name__}: {e}"
        print("❌ Gemini error:", err)
        bot.reply_to(message, "Gemini сейчас не отвечает. Ошибка: " + err[:350])


if __name__ == "__main__":
    keep_alive()
    print("🚀 Web healthcheck on :8080")
    print("🤖 Bot is running (polling)...")
    # timeout/long_polling_timeout помогают избежать подвисаний
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
