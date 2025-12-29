import os
import sys
import time
import telebot
from flask import Flask
from threading import Thread
from openai import OpenAI
from openai import APIError, RateLimitError, BadRequestError

print("✅ BOOT: starting python app", flush=True)
print("✅ BOOT: python =", sys.version, flush=True)

# =========================
# ENV
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "https://t.me/your_bot")
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "Telegram Bot")

# Важно для большинства платформ: порт берём из env PORT
PORT = int(os.environ.get("PORT", "8080"))

HAS_TG = bool(TELEGRAM_TOKEN)
HAS_OR = bool(OPENROUTER_API_KEY)

# =========================
# FLASK (healthcheck)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    status = {
        "bot": "on" if HAS_TG else "off (no TELEGRAM_TOKEN)",
        "openrouter": "on" if HAS_OR else "off (no OPENROUTER_API_KEY)",
        "port": PORT,
    }
    # Простая строка, чтобы healthcheck точно был happy
    return f"OK | bot={status['bot']} | openrouter={status['openrouter']} | port={status['port']}"

# =========================
# OPENROUTER CLIENT
# =========================
client = None
if HAS_OR:
    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=60,
        default_headers={
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-Title": OPENROUTER_APP_NAME,
        },
    )

MODELS = [
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash",
    "openai/gpt-4o-mini",
]

# =========================
# TELEGRAM
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None) if HAS_TG else None

user_history = {}
HISTORY_LIMIT = 12

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram.\n"
    "Отвечай кратко и по делу.\n"
    "Если вопрос непонятен — задай один уточняющий вопрос.\n"
)

def _cut_history(history: list, limit: int) -> list:
    return history[-limit:] if limit > 0 else []

def _extract_api_error_details(e: Exception) -> str:
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    body = getattr(e, "body", None)
    parts = []
    if status is not None:
        parts.append(f"status={status}")
    if body is not None:
        parts.append(f"body={body}")
    return " ".join(parts) if parts else repr(e)

def _build_messages_for_model(model: str, history: list, user_text: str) -> list:
    # Для Gemini часто стабильнее НЕ слать role=system, а склеить его в user
    if model.startswith("google/gemini"):
        prefix = f"{SYSTEM_PROMPT}\n\n"
        return [*history, {"role": "user", "content": prefix + user_text}]
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": user_text}]

def ai_answer(user_id: int, user_text: str) -> str:
    if client is None:
        raise RuntimeError("OpenRouter выключен: нет OPENROUTER_API_KEY")

    history = _cut_history(user_history.get(user_id, []), HISTORY_LIMIT)
    last_err = None

    for model in MODELS:
        try:
            messages = _build_messages_for_model(model, history, user_text)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=800,
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("AI вернул пустой ответ")

            new_history = history + [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": text},
            ]
            user_history[user_id] = _cut_history(new_history, HISTORY_LIMIT)
            return text

        except (BadRequestError, APIError, RateLimitError) as e:
            last_err = e
            print(f"❌ LLM error on {model}: {_extract_api_error_details(e)}", flush=True)
            continue

    raise RuntimeError(f"Все модели недоступны. Последняя ошибка: {type(last_err).__name__}: {last_err}")

def send_long_message(chat_id: int, text: str, chunk_size: int = 4000):
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])

def run_bot_polling():
    if bot is None:
        print("⚠️ Telegram bot disabled: no TELEGRAM_TOKEN", flush=True)
        return
    print("🤖 Telegram bot polling started", flush=True)

    backoff = 2
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
            backoff = 2
        except Exception as e:
            print("❌ Polling crashed:", type(e).__name__, e, flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

if HAS_TG:
    @bot.message_handler(content_types=["text"])
    def handle_text(message):
        user_id = message.chat.id
        text = (message.text or "").strip()

        if not text:
            bot.reply_to(message, "Пришли текстом 🙂")
            return

        if client is None:
            bot.reply_to(message, "ИИ выключен: нет ключа OPENROUTER_API_KEY.")
            return

        try:
            bot.send_chat_action(user_id, "typing")
            answer = ai_answer(user_id, text)
            send_long_message(user_id, answer)
        except RateLimitError:
            bot.reply_to(message, "Слишком много запросов. Попробуй через минуту 🙂")
        except Exception as e:
            print("❌ Handler error:", type(e).__name__, e, flush=True)
            bot.reply_to(message, "ИИ сейчас недоступен. Попробуй позже.")

    @bot.message_handler(content_types=["voice", "audio", "document", "photo", "video", "sticker"])
    def handle_other(message):
        bot.reply_to(message, "Пока понимаю только текст 🙂")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    # Важно: для PaaS чаще лучше держать Flask в главном потоке,
    # а polling — в фоне.
    Thread(target=run_bot_polling, daemon=True).start()

    print(f"🌐 Flask healthcheck on 0.0.0.0:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
