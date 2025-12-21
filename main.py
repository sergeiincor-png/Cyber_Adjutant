import os
import time
import telebot
from flask import Flask
from threading import Thread
from openai import OpenAI


# --- 1) HEALTHCHECK ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    Thread(target=run_web, daemon=True).start()


# --- 2) КЛЮЧИ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Проверь TELEGRAM_TOKEN и OPENAI_API_KEY")

# --- 3) OPENAI ---
client = OpenAI(api_key=OPENAI_API_KEY)

MODEL_NAME = "gpt-4o-mini"  # быстрый и дешёвый

# --- 4) TELEGRAM ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)

user_history = {}
HISTORY_LIMIT = 10
last_request_at = {}
USER_COOLDOWN_SEC = 2

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram. Отвечай кратко и по делу. "
    "Если вопрос непонятен — задай 1 уточняющий вопрос."
)

def chatgpt_answer(user_id: int, user_text: str) -> str:
    history = user_history.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7,
    )

    text = resp.choices[0].message.content.strip()

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
        bot.reply_to(message, "Напиши текст 🙂")
        return

    now = time.time()
    if now - last_request_at.get(user_id, 0) < USER_COOLDOWN_SEC:
        bot.reply_to(message, "Подожди пару секунд 🙂")
        return
    last_request_at[user_id] = now

    try:
        bot.send_chat_action(user_id, "typing")
        answer = chatgpt_answer(user_id, text)

        for i in range(0, len(answer), 4000):
            bot.send_message(user_id, answer[i:i+4000])

    except Exception as e:
        err = str(e)
        print("❌ OpenAI error:", err)
        bot.reply_to(message, "Ошибка ИИ. Попробуй позже.")


if __name__ == "__main__":
    keep_alive()
    print("🤖 Bot with ChatGPT is running...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)
