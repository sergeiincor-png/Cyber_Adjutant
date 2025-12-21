import os
import telebot
from flask import Flask
from threading import Thread

from google import genai
from google.genai.types import HttpOptions


# --- 1) ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (healthcheck/ping) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает!"

def run_web():
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
# КРИТИЧНО: по умолчанию SDK использует v1beta. Нам нужен стабильный v1. :contentReference[oaicite:2]{index=2}
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=HttpOptions(api_version="v1")
)

def pick_model_name() -> str:
    """
    Берём из ListModels первую модель, которая поддерживает generateContent.
    Это самый надёжный способ, потому что доступность моделей зависит от ключа/региона/версии API. :contentReference[oaicite:3]{index=3}
    """
    available = []
    for m in client.models.list():
        name = (m.name or "")
        actions = getattr(m, "supported_actions", None) or getattr(m, "supportedActions", []) or []
        if "generateContent" in actions:
            clean = name.replace("models/", "")
            available.append(clean)

    print("✅ Models with generateContent:", available)

    if not available:
        raise RuntimeError("Не нашёл ни одной модели с generateContent для этого ключа (через API v1).")

    # обычно первая — самая универсальная/доступная
    return available[0]

MODEL_NAME = pick_model_name()
print("✅ Using model:", MODEL_NAME)


# --- 4) TELEGRAM ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

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
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
