"""Impor vidoy_client: folder bot ini dulu (Docker), lalu folder induk (develop lokal)."""
import sys
from pathlib import Path

_BOT_DIR = Path(__file__).resolve().parent
_PARENT = _BOT_DIR.parent
for _p in (_BOT_DIR, _PARENT):
    if (_p / "vidoy_client.py").is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vidoy_client import (  # noqa: E402
    FOLDER_LINK_PATTERN,
    VIDEO_ID_FROM_URL,
    VidoyClient,
)

__all__ = [
    "FOLDER_LINK_PATTERN",
    "VIDEO_ID_FROM_URL",
    "VidoyClient",
]
