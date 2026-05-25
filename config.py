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
TELEGRAM_API_ID = (os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "").strip()
TELEGRAM_API_HASH = (os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or "").strip()
SESSION_STRING = (os.getenv("SESSION_STRING") or "").strip()
SESSION_NAME = (os.getenv("SESSION_NAME") or "vidoy_downloader").strip()

ADMIN_IDS_RAW = (os.getenv("ADMIN_IDS") or "").strip()
PORT = int((os.getenv("PORT") or "8000").strip())

VIDOY_EXTRACT_DOMAIN = (os.getenv("VIDOY_EXTRACT_DOMAIN") or "videq.pro").strip().lower()
MAX_VIDEOS_PER_JOB = int((os.getenv("MAX_VIDEOS_PER_JOB") or "30").strip())

# Userbot (SESSION_STRING) ≈ 2 GB; bot token saja ≈ 50 MB
IS_USERBOT = bool(SESSION_STRING)
BOT_FILE_LIMIT_MB = 49.0
USER_FILE_LIMIT_MB = 2000.0
TELEGRAM_FILE_LIMIT_MB = USER_FILE_LIMIT_MB if IS_USERBOT else BOT_FILE_LIMIT_MB

_raw_tg_mb = float(
    (os.getenv("MAX_TELEGRAM_MB") or str(int(TELEGRAM_FILE_LIMIT_MB - 100))).strip()
)
MAX_TELEGRAM_MB = min(_raw_tg_mb, TELEGRAM_FILE_LIMIT_MB)

MAX_DOWNLOAD_MB = float(
    (os.getenv("MAX_DOWNLOAD_MB") or str(int(MAX_TELEGRAM_MB))).strip()
)
MAX_DOWNLOAD_MB = min(MAX_DOWNLOAD_MB, MAX_TELEGRAM_MB)
if not IS_USERBOT:
    MAX_DOWNLOAD_MB = min(MAX_DOWNLOAD_MB, 500.0)

MIN_VALID_VIDEO_BYTES = int((os.getenv("MIN_VALID_VIDEO_BYTES") or "50000").strip())
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR") or (_BOT_DIR / "downloads"))
REQUEST_TIMEOUT = int((os.getenv("REQUEST_TIMEOUT") or "45").strip())
DOWNLOAD_CONNECT_TIMEOUT = int((os.getenv("DOWNLOAD_CONNECT_TIMEOUT") or "30").strip())
DOWNLOAD_READ_TIMEOUT = int((os.getenv("DOWNLOAD_READ_TIMEOUT") or "3600").strip())
DELAY_BETWEEN_VIDEOS_SEC = float((os.getenv("DELAY_BETWEEN_VIDEOS_SEC") or "2").strip())

ADMIN_IDS: set[int] = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        s = part.strip()
        if s.isdigit():
            ADMIN_IDS.add(int(s))


def validate() -> list[str]:
    errors = []
    if not TELEGRAM_API_ID or not str(TELEGRAM_API_ID).isdigit():
        errors.append("TELEGRAM_API_ID wajib (angka, dari https://my.telegram.org/apps)")
    if not TELEGRAM_API_HASH:
        errors.append("TELEGRAM_API_HASH wajib (dari https://my.telegram.org/apps)")
    if not SESSION_STRING and not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN wajib (atau isi SESSION_STRING untuk userbot)")
    if _raw_tg_mb > TELEGRAM_FILE_LIMIT_MB:
        mode = "userbot" if IS_USERBOT else "bot"
        print(
            f"Peringatan: MAX_TELEGRAM_MB={_raw_tg_mb} melebihi batas {mode} "
            f"(~{int(TELEGRAM_FILE_LIMIT_MB)} MB) — dipakai {MAX_TELEGRAM_MB} MB."
        )
    return errors
