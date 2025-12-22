import os
import time
import threading
from collections import deque
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from google import genai
from google.genai import types


# ---------- Простые лимиты ----------
class RateLimiter:
    """
    Ограничение по запросам: max_calls за period_seconds (скользящее окно).
    """
    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = period_seconds
        self.lock = threading.Lock()
        self.calls = deque()

    def acquire(self):
        with self.lock:
            now = time.time()
            # выкидываем старые
            while self.calls and self.calls[0] <= now - self.period:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                sleep_for = (self.calls[0] + self.period) - now
                if sleep_for > 0:
                    time.sleep(sleep_for)
                # после сна чистим ещё раз
                now = time.time()
                while self.calls and self.calls[0] <= now - self.period:
                    self.calls.popleft()

            self.calls.append(time.time())


# ---------- Настройки лимитов ----------
# Пример: 60 запросов в минуту, не больше 2 одновременных запросов
RPM = int(os.getenv("GEMINI_RPM", "60"))
CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", "2"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

rate_limiter = RateLimiter(max_calls=RPM, period_seconds=60)
semaphore = threading.Semaphore(CONCURRENCY)


class GeminiError(Exception):
    pass


def _is_retryable_exc(exc: Exception) -> bool:
    # Можно расширить: таймауты, 429, 5xx, сетевые ошибки и т.п.
    msg = str(exc).lower()
    return any(k in msg for k in ["429", "rate", "quota", "timeout", "temporarily", "unavailable", "500", "503"])


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(GeminiError),
)
def gemini_generate_text(prompt: str, system: Optional[str] = None) -> str:
    """
    Генерация текста Gemini с лимитами: RPM + concurrency + ретраи.
    """
    # лимиты
    rate_limiter.acquire()
    with semaphore:
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise GeminiError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=api_key)

            contents = []
            if system:
                # system можно зашить в инструкции или в отдельный content
                contents.append(types.Content(role="user", parts=[types.Part(text=f"System: {system}")]))
            contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
                # Можно добавить safety/settings/temperature
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=800,
                ),
            )

            text = getattr(resp, "text", None)
            if not text:
                raise GeminiError(f"Empty response: {resp}")
            return text

        except Exception as e:
            # решаем — ретраим или нет
            if _is_retryable_exc(e):
                raise GeminiError(str(e))
            raise
