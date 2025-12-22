import os
import sys
import telebot
from flask import Flask
from threading import Thread
from openai import OpenAI

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

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise RuntimeError(
        "❌ Проверь переменные окружения TELEGRAM_TOKEN и OPENROUTER_API_KEY"
    )

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
# OPENROUTER CLIENT
# =========================
client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

MODEL_NAME = "openai/gpt-4o-mini"  # дешёвый и стабильный

# =========================
# TELEGRAM
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}
HISTORY_LIMIT = 12

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram. "
    "Отвечай кратко и по делу. "
    "Если вопрос непонятен — задай один уточняющий вопрос."
)

def ai_answer(user_id: int, user_text: str) -> str:
    history = user_history.get(user_id, [])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_text},
    ]

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7,
    )

    text = response.choices[0].message.content.strip()

    if not text:
        raise RuntimeError("AI вернул пустой ответ")

    new_history = history + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": text},
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
        answer = ai_answer(user_id, text)

        for i in range(0, len(answer), 4000):
            bot.send_message(user_id, answer[i:i + 4000])

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print("❌ AI error:", err, flush=True)
        bot.reply_to(message, "Ошибка ИИ. Попробуй позже.")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    # Flask в отдельном потоке
    Thread(target=run_flask, daemon=True).start()

    print("🤖 Telegram bot polling started", flush=True)

    # Telegram polling в основном потоке
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
