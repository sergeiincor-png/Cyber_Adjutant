import os
import sys
import time
import random
import telebot
from flask import Flask
from threading import Thread

from openai import OpenAI
from openai import RateLimitError, APIError, APITimeoutError

print("✅ BOOT: starting python app", flush=True)
print("✅ BOOT: python =", sys.version, flush=True)

# --- 1) ВЕБ-СЕРВЕР ДЛЯ HEALTHCHECK ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

# --- 2) ENV / КЛЮЧИ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Ключ OpenRouter
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Модель по умолчанию (можно поменять в переменной окружения MODEL)
# Примеры:
#   "openai/gpt-4o-mini"
#   "anthropic/claude-3.5-sonnet"
#   "google/gemini-2.0-flash"
MODEL = os.environ.get("MODEL", "openai/gpt-4o-mini")

# Для статистики/правильной идентификации на OpenRouter
SITE_URL = os.environ.get("SITE_URL", "https://example.com")
APP_NAME = os.environ.get("APP_NAME", "TimewebTelegramBot")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise RuntimeError("Проверь переменные окружения TELEGRAM_TOKEN и OPENROUTER_API_KEY")

# --- 3) OpenRouter client (OpenAI-compatible) ---
client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# Важно: OpenRouter просит эти заголовки (не обязательно, но желательно)
DEFAULT_HEADERS = {
    "HTTP-Referer": SITE_URL,
    "X-Title": APP_NAME,
}

# --- 4) TELEGRAM ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}
HISTORY_LIMIT = 12  # 6 реплик пользователя + 6 ответов ассистента

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram. Отвечай кратко и по делу. "
    "Если вопрос непонятен — задай 1 уточняющий вопрос."
)

def _truncate_history(history, limit):
    return history[-limit:] if len(history) > limit else history

def openrouter_answer(user_id: int, user_text: str) -> str:
    history = user_history.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    # ретраи на 429/временные ошибки
    max_retries = 5
    base_sleep = 1.0

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                extra_headers=DEFAULT_HEADERS,
            )

            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("Провайдер вернул пустой ответ.")

            # сохраняем историю
            new_history = history + [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": text},
            ]
            user_history[user_id] = _truncate_history(new_history, HISTORY_LIMIT)
            return text

        except RateLimitError as e:
            # 429 — подождать и повторить
            last_err = e
            sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(f"⚠️ Rate limit (attempt {attempt}/{max_retries}), sleeping {sleep_s:.2f}s", flush=True)
            time.sleep(sleep_s)

        except (APITimeoutError, APIError) as e:
            # временные/сетевые ошибки
            last_err = e
            sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(f"⚠️ API error (attempt {attempt}/{max_retries}), sleeping {sleep_s:.2f}s: {e}", flush=True)
            time.sleep(sleep_s)

        except Exception as e:
            # прочие ошибки — без агрессивных ретраев
            raise

    raise RuntimeError(f"OpenRouter сейчас не отвечает (после ретраев). Последняя ошибка: {type(last_err).__name__}: {last_err}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    text = (message.text or "").strip()

    if not text:
        bot.reply_to(messag_
