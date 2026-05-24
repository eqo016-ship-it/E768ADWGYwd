# @name: config.py v2.0
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
PORT = int((os.getenv("PORT") or "8081").strip())

VIDOY_EXTRACT_DOMAIN = (os.getenv("VIDOY_EXTRACT_DOMAIN") or "videq.pro").strip().lower()

MAX_VIDEOS_PER_JOB = int((os.getenv("MAX_VIDEOS_PER_JOB") or "30").strip())

# Plafon maksimal kita set ke 1000 MB
TELEGRAM_BOT_FILE_LIMIT_MB = 1000.0
_raw_tg_mb = float((os.getenv("MAX_TELEGRAM_MB") or "1000").strip())
MAX_TELEGRAM_MB = min(_raw_tg_mb, TELEGRAM_BOT_FILE_LIMIT_MB)

# Maks yang mau diunduh ke disk; diubah batas mentoknya jadi 1000 MB
MAX_DOWNLOAD_MB = float((os.getenv("MAX_DOWNLOAD_MB") or str(int(MAX_TELEGRAM_MB))).strip())
MAX_DOWNLOAD_MB = min(MAX_DOWNLOAD_MB, 1000.0)

MIN_VALID_VIDEO_BYTES = int((os.getenv("MIN_VALID_VIDEO_BYTES") or "50000").strip())
# Folder legacy (dibersihkan saat startup); unduhan pakai folder sementara per job
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR") or (_BOT_DIR / "downloads"))
REQUEST_TIMEOUT = int((os.getenv("REQUEST_TIMEOUT") or "45").strip())
# Unduh file besar butuh waktu lama (connect, read per chunk)
DOWNLOAD_CONNECT_TIMEOUT = int((os.getenv("DOWNLOAD_CONNECT_TIMEOUT") or "30").strip())
DOWNLOAD_READ_TIMEOUT = int((os.getenv("DOWNLOAD_READ_TIMEOUT") or "900").strip())
DELAY_BETWEEN_VIDEOS_SEC = float((os.getenv("DELAY_BETWEEN_VIDEOS_SEC") or "2").strip())
# Upload video ke Telegram (file besar butuh timeout lebih lama)
TELEGRAM_MEDIA_TIMEOUT = float((os.getenv("TELEGRAM_MEDIA_TIMEOUT") or "300").strip())

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
    if _raw_tg_mb > TELEGRAM_BOT_FILE_LIMIT_MB:
        print(
            f"Peringatan: MAX_TELEGRAM_MB={_raw_tg_mb} terlalu besar. "
            f"Sistem dibatasi maks ~{int(TELEGRAM_BOT_FILE_LIMIT_MB)} MB — "
            f"dipakai {MAX_TELEGRAM_MB} MB."
        )
    return errors
