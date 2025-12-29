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

# Primary + fallback models
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

def _extract_api_error_details(e: Exception)
