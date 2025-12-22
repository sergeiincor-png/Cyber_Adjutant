import os
import sys
import time
import random
import telebot

print("✅ BOOT: starting python app", flush=True)
print("✅ BOOT: python =", sys.version, flush=True)

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
# Важно: используем стабильный v1
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=HttpOptions(api_version="v1")
)

def pick_model_name() -> str:
    available = []
    all_names = []
    for m in client.models.list():
        name = (m.name or "")
        all_names.append(name)
        actions = getattr(m, "supported_actions", None) or getattr(m, "supportedActions", []) or []
        if "generateContent" in actions:
            available.append(name.replace("models/", ""))

    print("✅ BOOT: total models seen =", len(all_names), flush=True)
    print("✅ BOOT: models with generateContent =", available, flush=True)

    if not available:
        raise RuntimeError("Не нашёл ни одной модели с generateContent для этого ключа (через API v1).")

    # Берем первую доступную (обычно универсальная)
    return available[0]

MODEL_NAME = pick_model_name()
print("✅ Using model:", MODEL_NAME, flush=True)


# --- 4) TELEGRAM ---
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}
HISTORY_LIMIT = 6  # меньше истории = меньше токенов = меньше шанс упереться в лимиты

SYSTEM_PROMPT = "Отвечай кратко и по делу. Если вопрос неясен — задай 1 уточняющий вопрос."


# --- 5) ЗАЩИТА ОТ СПАМА (чтобы один юзер не сжёг квоту) ---
