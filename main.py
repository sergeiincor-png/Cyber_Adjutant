import os
import sys
import time
import telebot
from flask import Flask
from threading import Thread
from openai import OpenAI
from openai import APIError, RateLimitError, BadRequestError

# =========================
# BOOT LOG
# =========================
print("✅ BOOT: starting python app", flush=True)
print("✅ BOOT: python =", sys.version, flush=True)

# =========================
# ENV
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Опционально (для статистики/идентификации в OpenRouter)
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "https://t.me/your_bot")
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "Telegram Bot")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise RuntimeError("❌ Проверь переменные окружения TELEGRAM_TOKEN и OPENROUTER_API_KEY")

# =========================
# FLASK (healthcheck)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает!"

def run_flask():
    app.run(host="0.0.0.0", port=8080, debug=False)

# =========================
# OPENROUTER CLIENT (OpenAI-compatible)
# =========================
client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=60,
    default_headers={
        "HTTP-Referer": OPENROUTER_SITE_URL,  # optional
        "X-Title": OPENROUTER_APP_NAME,       # optional
    },
)

MODEL_NAME = "google/gemini-2.5-flash"  # ✅ Gemini Flash 2.5 через OpenRouter :contentReference[oaicite:1]{index=1}

# =========================
# TELEGRAM
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}         # { user_id: [ {role, content}, ... ] }
HISTORY_LIMIT = 12        # сколько сообщений истории хранить (user+assistant вместе)

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram.\n"
    "Отвечай кратко и по делу.\n"
    "Если вопрос непонятен — задай один уточняющий вопрос.\n"
)

def _cut_history(history: list, limit: int) -> list:
    """Обрезаем историю до последних limit сообщений."""
    if limit <= 0:
        return []
    return history[-limit:]

def ai_answer(user_id: int, user_text: str) -> str:
    history = user_history.get(user_id, [])
    history = _cut_history(history, HISTORY_LIMIT)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_text},
    ]

    # Важно: Gemini через OpenRouter работает в том же формате messages
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7,
    )

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("AI вернул пустой ответ")

    # обновляем историю
    new_history = history + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": text},
    ]
    user_history[user_id] = _cut_history(new_history, HISTORY_LIMIT)

    return text

def send_long_message(chat_id: int, text: str, chunk_size: int = 4000):
    """Telegram лимитирует размер сообщений — режем на куски."""
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    text = (message.text or "").strip()

    if not text:
        bot.reply_to(message, "Пришли текстом 🙂")
        return

    try:
        bot.send_chat_action(user_id, "typing")
        answer = ai_answer(user_id, text)
        send_long_message(user_id, answer)

    except RateLimitError as e:
        print("❌ RateLimitError:", e, flush=True)
        bot.reply_to(message, "Слишком много запросов. Попробуй через минуту 🙂")

    except BadRequestError as e:
        # Часто это: слишком длинный текст, неподдерживаемые параметры и т.д.
        print("❌ BadRequestError:", e, flush=True)
        bot.reply_to(message, "Запрос не прошёл. Попробуй короче или иначе сформулировать.")

    except APIError as e:
        # Общие ошибки API (в т.ч. временная недоступность провайдера)
        print("❌ APIError:", e, flush=True)
        bot.reply_to(message, "Сервис ИИ временно недоступен. Попробуй позже.")

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print("❌ Unknown error:", err, flush=True)
        bot.reply_to(message, "Ошибка ИИ. Попробуй позже.")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    # Flask в отдельном потоке (healthcheck)
    Thread(target=run_flask, daemon=True).start()

    print("🤖 Telegram bot polling started", flush=True)

    # Telegram polling в основном потоке
    # retry/backoff на случай сетевых ошибок
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print("❌ Polling crashed:", type(e).__name__, e, flush=True)
            time.sleep(3)
