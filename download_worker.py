import logging
import re
import shutil
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from stream_resolver import ResolvedStream, resolve_stream_url, safe_filename

logger = logging.getLogger(__name__)

CHUNK = 1024 * 256
MP4_FTYP = b"ftyp"


def validate_local_video(path: Path, expected_size: int | None = None) -> tuple[bool, str]:
    """
    Cek file siap dikirim ke Telegram.
    Thumbnail hitam + 0:00 biasanya = unduhan putus / bukan MP4 valid.
    """
    if not path.is_file():
        return False, "File tidak ditemukan."
    size = path.stat().st_size
    if size < 50_000:
        return False, f"File terlalu kecil ({size} byte) — unduhan kemungkinan putus di tengah."
    if expected_size and expected_size > 0:
        if size < expected_size * 0.97:
            got_mb = size / (1024 * 1024)
            exp_mb = expected_size / (1024 * 1024)
            return False, (
                f"Unduhan tidak lengkap: baru {got_mb:.1f} MB dari {exp_mb:.1f} MB."
            )
    with open(path, "rb") as f:
        head = f.read(32)
    if len(head) >= 8 and head[4:8] == MP4_FTYP:
        return True, ""
    if head[:3] == b"ID3" or head[:2] == b"\xff\xfb":
        return True, ""  # audio — tetap bisa dikirim
    if head.strip().startswith(b"<!") or head.strip().startswith(b"<html"):
        return False, "Yang terunduh bukan video (halaman HTML/error)."
    return False, "Format bukan MP4 standar — Telegram bisa tampil hitam/0:00."


def _download_headers(resolved: ResolvedStream) -> dict:
    referer = (
        resolved.referer_url
        or resolved.page_url
        or resolved.direct_url
    )
    origin = ""
    if resolved.page_url and "://" in resolved.page_url:
        p = urlparse(resolved.page_url)
        origin = f"{p.scheme}://{p.netloc}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if origin:
        headers["Origin"] = origin
    return headers


def remote_content_length(
    resolved: ResolvedStream,
    connect_timeout: int = 30,
) -> int | None:
    """Ukuran file di server (byte), None jika tidak diketahui."""
    try:
        r = requests.head(
            resolved.direct_url,
            headers=_download_headers(resolved),
            timeout=connect_timeout,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            r = requests.get(
                resolved.direct_url,
                headers={**_download_headers(resolved), "Range": "bytes=0-0"},
                timeout=connect_timeout,
                stream=True,
            )
            r.close()
        cl = r.headers.get("Content-Length") or r.headers.get("content-length")
        if cl and str(cl).isdigit():
            return int(cl)
    except Exception as e:
        logger.debug("HEAD ukuran gagal: %s", e)
    return None


def download_to_path(
    resolved: ResolvedStream,
    dest_dir: Path,
    connect_timeout: int = 30,
    read_timeout: int = 900,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Unduh file ke folder tujuan; file .part dihapus jika gagal."""
    if resolved.is_hls:
        raise RuntimeError(
            "Video ini format HLS (m3u8). Bot belum mengonversi otomatis — "
            "gunakan link unduhan langsung (VLC/IDM)."
        )
    dest_dir.mkdir(parents=True, exist_ok=True)
    vid_m = re.search(r"/(d|e)/([a-zA-Z0-9_-]+)", resolved.page_url or "")
    vid = vid_m.group(2) if vid_m else "video"
    fname = safe_filename(resolved.title, vid)
    out = dest_dir / fname
    if out.exists():
        stem, suffix = out.stem, out.suffix
        n = 1
        while out.exists():
            out = dest_dir / f"{stem}_{n}{suffix}"
            n += 1

    part = out.with_suffix(out.suffix + ".part")
    timeout = (connect_timeout, read_timeout)
    headers = _download_headers(resolved)
    expected_size: int | None = None
    try:
        with requests.get(
            resolved.direct_url,
            headers=headers,
            stream=True,
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            cl = r.headers.get("Content-Length") or r.headers.get("content-length")
            if cl and str(cl).isdigit():
                expected_size = int(cl)
            downloaded = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress and expected_size:
                            on_progress(downloaded, expected_size)
                        elif on_progress and downloaded % (CHUNK * 4) < len(chunk):
                            on_progress(downloaded, expected_size or downloaded)
            if expected_size and downloaded < expected_size * 0.97:
                raise RuntimeError(
                    f"Unduhan putus: {downloaded / (1024*1024):.1f} MB "
                    f"dari {expected_size / (1024*1024):.1f} MB"
                )
        part.replace(out)
        ok, err = validate_local_video(out, expected_size)
        if not ok:
            out.unlink(missing_ok=True)
            raise RuntimeError(err)
        return out
    except Exception:
        part.unlink(missing_ok=True)
        if out.exists():
            out.unlink(missing_ok=True)
        raise


def resolve_and_download(
    page_url: str,
    dest_dir: Path,
    request_timeout: int = 45,
    connect_timeout: int = 30,
    read_timeout: int = 900,
) -> tuple[Path, ResolvedStream]:
    resolved = resolve_stream_url(page_url, timeout=request_timeout)
    path = download_to_path(
        resolved,
        dest_dir,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )
    return path, resolved


def cleanup_path(path: Path | None) -> None:
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        logger.debug("Hapus file gagal %s: %s", path, e)


def cleanup_dir(path: Path | None) -> None:
    if not path or not path.exists():
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.debug("Hapus folder gagal %s: %s", path, e)
