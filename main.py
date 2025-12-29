import os
import sys
import time
import json
import base64
import subprocess
import telebot
from flask import Flask
from threading import Thread
from openai import OpenAI
from vosk import Model, KaldiRecognizer

print("✅ BOOT: starting python app", flush=True)
print("✅ BOOT: python =", sys.version, flush=True)

# =========================
# ENV
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "https://t.me/your_bot")
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "Telegram Bot")

PORT = int(os.environ.get("PORT", "8080"))
VOSK_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "/app/models/vosk-ru")

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ Проверь TELEGRAM_TOKEN")
if not OPENROUTER_API_KEY:
    raise RuntimeError("❌ Проверь OPENROUTER_API_KEY")

# =========================
# FLASK (healthcheck)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    vosk_ok = "on" if os.path.isdir(VOSK_MODEL_PATH) else f"off (no model at {VOSK_MODEL_PATH})"
    return f"OK | bot=on | openrouter=on | vosk={vosk_ok}"

# =========================
# OPENROUTER CLIENT
# =========================
or_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=60,
    default_headers={
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    },
)

# =========================
# MODELS
# =========================
TEXT_MODEL = "google/gemini-2.5-flash"
FALLBACK_TEXT_MODEL = "openai/gpt-4o-mini"
VISION_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = (
    "Ты — полезный ассистент в Telegram.\n"
    "Отвечай кратко и по делу.\n"
    "Если вопрос непонятен — задай один уточняющий вопрос.\n"
)

# =========================
# TELEGRAM
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

user_history = {}
HISTORY_LIMIT = 12

def _cut_history(history: list, limit: int) -> list:
    return history[-limit:] if limit > 0 else []

def send_long_message(chat_id: int, text: str, chunk_size: int = 4000):
    text = text or ""
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])

def _gemini_messages(history: list, user_text: str) -> list:
    # Для Gemini часто стабильнее не использовать role=system
    prefix = f"{SYSTEM_PROMPT}\n\n"
    return [*history, {"role": "user", "content": prefix + user_text}]

def ai_answer(user_id: int, user_text: str) -> str:
    history = _cut_history(user_history.get(user_id, []), HISTORY_LIMIT)

    # 1) Gemini
    try:
        resp = or_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=_gemini_messages(history, user_text),
            temperature=0.7,
            max_tokens=900,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("AI вернул пустой ответ")

        user_history[user_id] = _cut_history(
            history + [{"role": "user", "content": user_text}, {"role": "assistant", "content": text}],
            HISTORY_LIMIT
        )
        return text

    except Exception as e:
        print(f"❌ Gemini error: {type(e).__name__}: {e}", flush=True)

        # 2) fallback
        resp = or_client.chat.completions.create(
            model=FALLBACK_TEXT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *history,
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
            max_tokens=900,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("AI вернул пустой ответ (fallback)")

        user_history[user_id] = _cut_history(
            history + [{"role": "user", "content": user_text}, {"role": "assistant", "content": text}],
            HISTORY_LIMIT
        )
        return text

def vision_answer(image_bytes: bytes, prompt: str) -> str:
    if not prompt:
        prompt = "Распознай, что на изображении. Если это скрин — выпиши важный текст и кратко объясни."

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    resp = or_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        max_tokens=900,
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()

# =========================
# VOSK STT
# =========================
_vosk_model = None

def _get_vosk_model():
    global _vosk_model
    if _vosk_model is None:
        if not os.path.isdir(VOSK_MODEL_PATH):
            raise RuntimeError(f"Vosk model not found at {VOSK_MODEL_PATH}")
        print(f"🎙️ Loading Vosk model from {VOSK_MODEL_PATH}", flush=True)
        _vosk_model = Model(VOSK_MODEL_PATH)
    return _vosk_model

def speech_to_text_vosk(ogg_bytes: bytes) -> str:
    """
    Telegram voice = ogg/opus. Конвертим через ffmpeg в wav 16k mono,
    потом распознаём Vosk.
    """
    tmp_base = f"/tmp/tg_voice_{int(time.time()*1000)}"
    ogg_path = tmp_base + ".ogg"
    wav_path = tmp_base + ".wav"

    with open(ogg_path, "wb") as f:
        f.write(ogg_bytes)

    # ffmpeg -> wav 16k mono
    cmd = ["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", wav_path]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg conversion failed")

    model = _get_vosk_model()
    rec = KaldiRecognizer(model, 16000)

    with open(wav_path, "rb") as f:
        while True:
            data = f.read(4000)
            if not data:
                break
            rec.AcceptWaveform(data)

    result = json.loads(rec.FinalResult() or "{}")
    text = (result.get("text") or "").strip()

    # cleanup
    try:
        os.remove(ogg_path)
        os.remove(wav_path)
    except Exception:
        pass

    return text

# =========================
# HANDLERS
# =========================
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
    except Exception as e:
        print("❌ Text handler error:", type(e).__name__, e, flush=True)
        bot.reply_to(message, "Ошибка ИИ. Попробуй позже.")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.chat.id
    prompt = (message.caption or "").strip()
    try:
        bot.send_chat_action(user_id, "typing")
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        img_bytes = bot.download_file(file_info.file_path)

        text = vision_answer(img_bytes, prompt)
        send_long_message(user_id, text if text else "Не смог разобрать скрин 😅")
    except Exception as e:
        print("❌ Photo handler error:", type(e).__name__, e, flush=True)
        bot.reply_to(message, "Не получилось обработать скрин. Попробуй ещё раз.")

@bot.message_handler(content_types=["document"])
def handle_document(message):
    user_id = message.chat.id
    prompt = (message.caption or "").strip()
    try:
        bot.send_chat_action(user_id, "typing")
        doc = message.document
        mime = (doc.mime_type or "").lower()
        if not mime.startswith("image/"):
            bot.reply_to(message, "Пришли скрин как картинку (или файлом-изображением) 🙂")
            return

        file_info = bot.get_file(doc.file_id)
        img_bytes = bot.download_file(file_info.file_path)

        text = vision_answer(img_bytes, prompt)
        send_long_message(user_id, text if text else "Не смог разобрать изображение 😅")
    except Exception as e:
        print("❌ Document handler error:", type(e).__name__, e, flush=True)
        bot.reply_to(message, "Не получилось обработать файл. Попробуй ещё раз.")

@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    user_id = message.chat.id
    try:
        bot.send_chat_action(user_id, "typing")
        file_info = bot.get_file(message.voice.file_id)
        ogg_bytes = bot.download_file(file_info.file_path)

        text = speech_to_text_vosk(ogg_bytes)
        if not text:
            bot.reply_to(message, "Не разобрал голосовое 😅 Попробуй ещё раз (погромче/помедленнее).")
            return

        answer = ai_answer(user_id, text)
        send_long_message(user_id, answer)
    except Exception as e:
        print("❌ Voice handler error:", type(e).__name__, e, flush=True)
        bot.reply_to(message, "Не получилось обработать голосовое. Попробуй ещё раз.")

# =========================
# RUNNERS
# =========================
def run_bot_polling():
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

if __name__ == "__main__":
    Thread(target=run_bot_polling, daemon=True).start()
    print(f"🌐 Flask healthcheck on 0.0.0.0:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
