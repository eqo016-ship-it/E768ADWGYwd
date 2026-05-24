"""Impor fungsi ekstrak link dari vidoy_client di folder induk (tanpa duplikasi kode)."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
