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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# optional headers for OpenRouter analytics
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
# OPENROUTER CLIENT
# =========================
client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=60,
    default_headers={
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    },
)

# Primary + fallback models (на случай, если провайдер упал / модель недоступна)
MODELS = [
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash",
    "openai/gpt-4o-mini",
]

# =========================
# TELEGRAM
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}
HISTORY_LIMIT = 12

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram.\n"
    "Отвечай кратко и по делу.\n"
    "Если вопрос непонятен — задай один уточняющий вопрос.\n"
)

def _cut_history(history: list, limit: int) -> list:
    if limit <= 0:
        return []
    return history[-limit:]

def _extract_api_error_details(e: Exception) -> str:
    """Достаём максимум деталей из ошибок SDK (без падения)."""
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    body = getattr(e, "body", None)

    parts = []
    if status is not None:
        parts.append(f"status={status}")
    if body is not None:
        parts.append(f"body={body}")
    return " ".join(parts) if parts else repr(e)

def ai_answer(user_id: int, user_text: str) -> str:
    history = _cut_history(user_history.get(user_id, []), HISTORY_LIMIT)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_text},
    ]

    last_err = None

    for model in MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
            )

            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("AI вернул пустой ответ")

            # update history
            new_history = history + [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": text},
            ]
            user_history[user_id] = _cut_history(new_history, HISTORY_LIMIT)
            return text

        except RateLimitError as e:
            # 429: лимит — пробуем следующую модель или сообщаем
            last_err = e
            print(f"❌ RateLimitError on {model}: {_extract_api_error_details(e)}", flush=True)
            continue

        except BadRequestError as e:
            # 400: обычно проблема запроса — нет смысла пробовать другие модели
            print(f"❌ BadRequestError on {model}: {_extract_api_error_details(e)}", flush=True)
            raise

        except APIError as e:
            # 401/402/5xx/и т.п. — пробуем fallback
            last_err = e
            print(f"❌ APIError on {model}: {_extract_api_error_details(e)}", flush=True)
            continue

        except Exception as e:
            last_err = e
            print(f"❌ Unknown error on {model}: {type(e).__name__}: {e}", flush=True)
            continue

    # если дошли сюда — все модели упали
    raise RuntimeError(f"Все модели недоступны. Последняя ошибка: {type(last_err).__name__}: {last_err}")

def send_long_message(chat_id: int, text: str, chunk_size: int = 4000):
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])

@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.chat.id
    text = (message.text or "").strip()

    if not text:
        bot.reply_to(message, "Пришли текстом 🙂")
        return

    try:
        bot.send_chat_action(user_id, "typing")
        answer = ai_answer(user_id, text)
        send_long_message(user_id, answer)

    except BadRequestError:
        bot.reply_to(message, "Слишком длинно/непонятно для запроса. Сократи или переформулируй 🙂")

    except RateLimitError:
        bot.reply_to(message, "Слишком много запросов. Попробуй через минуту 🙂")

    except APIError as e:
        details = _extract_api_error_details(e)
        print("❌ Final APIError:", details, flush=True)
        # частый кейс: 401/402/503 — даём нормальный текст
        bot.reply_to(message, "ИИ сейчас недоступен (ошибка провайдера/квоты). Попробуй позже.")

    except Exception as e:
        print("❌ Handler error:", type(e).__name__, e, flush=True)
        bot.reply_to(message, "Ошибка ИИ. Попробуй позже.")

@bot.message_handler(content_types=["voice", "audio", "document", "photo", "video", "sticker"])
def handle_other(message):
    bot.reply_to(message, "Пока понимаю только текст 🙂")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
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
