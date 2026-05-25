import os
from pathlib import Path

from dotenv import load_dotenv

_BOT_DIR = Path(__file__).resolve().parent
_ENV = _BOT_DIR / ".env"
if _ENV.is_file():
    load_dotenv(_ENV)
else:
    load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_IDS_RAW = (os.getenv("ADMIN_IDS") or "").strip()
# Port health check Koyeb (bukan port Local Bot API — itu 8081 internal)
PORT = int((os.getenv("PORT") or "8000").strip())

VIDOY_EXTRACT_DOMAIN = (os.getenv("VIDOY_EXTRACT_DOMAIN") or "videq.pro").strip().lower()

MAX_VIDEOS_PER_JOB = int((os.getenv("MAX_VIDEOS_PER_JOB") or "30").strip())

# --- Local Bot API Server (upload hingga ~2 GB, bot token) ---
TELEGRAM_API_ID = (os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "").strip()
TELEGRAM_API_HASH = (os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or "").strip()
USE_LOCAL_BOT_API = (os.getenv("USE_LOCAL_BOT_API") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
LOCAL_BOT_API_HTTP_PORT = int((os.getenv("LOCAL_BOT_API_HTTP_PORT") or "8081").strip())
LOCAL_BOT_API_BASE_URL = (
    os.getenv("LOCAL_BOT_API_BASE_URL")
    or f"http://127.0.0.1:{LOCAL_BOT_API_HTTP_PORT}/bot"
).rstrip("/")
if not LOCAL_BOT_API_BASE_URL.endswith("/bot"):
    LOCAL_BOT_API_BASE_URL = f"{LOCAL_BOT_API_BASE_URL}/bot"
LOCAL_BOT_API_FILE_URL = (
    os.getenv("LOCAL_BOT_API_FILE_URL")
    or f"http://127.0.0.1:{LOCAL_BOT_API_HTTP_PORT}/file/bot"
).rstrip("/")
if not LOCAL_BOT_API_FILE_URL.endswith("/file/bot"):
    LOCAL_BOT_API_FILE_URL = f"{LOCAL_BOT_API_FILE_URL}/file/bot"

LOCAL_MODE_ACTIVE = USE_LOCAL_BOT_API and bool(TELEGRAM_API_ID) and bool(TELEGRAM_API_HASH)

# Batas upload Telegram
CLOUD_BOT_FILE_LIMIT_MB = 49.0
LOCAL_BOT_FILE_LIMIT_MB = 2000.0
TELEGRAM_BOT_FILE_LIMIT_MB = (
    LOCAL_BOT_FILE_LIMIT_MB if LOCAL_MODE_ACTIVE else CLOUD_BOT_FILE_LIMIT_MB
)

_raw_tg_mb = float(
    (os.getenv("MAX_TELEGRAM_MB") or ("1800" if LOCAL_MODE_ACTIVE else "48")).strip()
)
MAX_TELEGRAM_MB = min(_raw_tg_mb, TELEGRAM_BOT_FILE_LIMIT_MB)

MAX_DOWNLOAD_MB = float(
    (os.getenv("MAX_DOWNLOAD_MB") or str(int(MAX_TELEGRAM_MB))).strip()
)
if LOCAL_MODE_ACTIVE:
    MAX_DOWNLOAD_MB = min(MAX_DOWNLOAD_MB, MAX_TELEGRAM_MB)
else:
    MAX_DOWNLOAD_MB = min(MAX_DOWNLOAD_MB, 500.0)

MIN_VALID_VIDEO_BYTES = int((os.getenv("MIN_VALID_VIDEO_BYTES") or "50000").strip())
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR") or (_BOT_DIR / "downloads"))
REQUEST_TIMEOUT = int((os.getenv("REQUEST_TIMEOUT") or "45").strip())
DOWNLOAD_CONNECT_TIMEOUT = int((os.getenv("DOWNLOAD_CONNECT_TIMEOUT") or "30").strip())
DOWNLOAD_READ_TIMEOUT = int((os.getenv("DOWNLOAD_READ_TIMEOUT") or "3600").strip())
DELAY_BETWEEN_VIDEOS_SEC = float((os.getenv("DELAY_BETWEEN_VIDEOS_SEC") or "2").strip())
TELEGRAM_MEDIA_TIMEOUT = float(
    (os.getenv("TELEGRAM_MEDIA_TIMEOUT") or ("3600" if LOCAL_MODE_ACTIVE else "300")).strip()
)

ADMIN_IDS: set[int] = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        s = part.strip()
        if s.isdigit():
            ADMIN_IDS.add(int(s))


def validate() -> list[str]:
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN wajib diisi di .env")
    if USE_LOCAL_BOT_API:
        if not TELEGRAM_API_ID:
            errors.append("TELEGRAM_API_ID wajib (dari https://my.telegram.org/apps)")
        if not TELEGRAM_API_HASH:
            errors.append("TELEGRAM_API_HASH wajib (dari https://my.telegram.org/apps)")
    if _raw_tg_mb > TELEGRAM_BOT_FILE_LIMIT_MB:
        mode = "Local Bot API" if LOCAL_MODE_ACTIVE else "Bot API cloud"
        print(
            f"Peringatan: MAX_TELEGRAM_MB={_raw_tg_mb} melebihi batas {mode} "
            f"(~{int(TELEGRAM_BOT_FILE_LIMIT_MB)} MB) — dipakai {MAX_TELEGRAM_MB} MB."
        )
    return errors
