"""Ambil URL unduhan langsung dari halaman /d/ atau /e/ (host mirip Doodstream/Vidoy)."""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PASS_MD5_PATTERNS = [
    re.compile(r"""pass_md5['"]\s*,\s*['"]([a-zA-Z0-9]+)['"]"""),
    re.compile(r"""pass_md5["']\s*:\s*["']([a-zA-Z0-9]+)['"]"""),
    re.compile(r"""['"]pass_md5['"]\s*:\s*['"]([a-zA-Z0-9]+)['"]"""),
]
EXPIRES_PATTERNS = [
    re.compile(r"""expires['"]\s*,\s*['"]?(\d+)['"]?"""),
    re.compile(r"""expires["']\s*:\s*(\d+)"""),
]
MP4_IN_HTML = re.compile(r"""https?://[^\s"'<>]+\.mp4[^\s"'<>]*""", re.I)
M3U8_IN_HTML = re.compile(r"""https?://[^\s"'<>]+\.m3u8[^\s"'<>]*""", re.I)
DOWNLOAD_URL_JSON = re.compile(
    r"""(?:download_url|url|file|src)["']\s*:\s*["'](https?://[^"']+)["']""",
    re.I,
)
TITLE_TAG = re.compile(r"<title>([^<]+)</title>", re.I)
EMBED_BUCKET_PATTERN = re.compile(
    r"""embed\.php\?bucket=([^&"'\s]+)&id=""",
    re.I,
)
VIDEO_SOURCE_PATTERN = re.compile(
    r"""<source\s+src=["'](https?://[^"']+)["']""",
    re.I,
)
VIDEO_SRC_PATTERN = re.compile(
    r"""<video[^>]+src=["'](https?://[^"']+)["']""",
    re.I,
)


@dataclass
class ResolvedStream:
    direct_url: str
    title: str = ""
    is_hls: bool = False
    page_url: str = ""


def _video_id_and_base(page_url: str) -> tuple[str, str, str]:
    page_url = (page_url or "").strip()
    m = re.search(
        r"(?:https?://)?(?:www\.)?([^/]+)/(d|e)/([a-zA-Z0-9_-]+)",
        page_url,
        re.I,
    )
    if not m:
        raise ValueError("Link video tidak valid. Format: https://domain/d/ID atau /e/ID")
    domain, link_type, vid = m.group(1).lower(), m.group(2).lower(), m.group(3)
    base = f"https://{domain}"
    if not page_url.lower().startswith("http"):
        page_url = f"{base}/{link_type}/{vid}"
    return vid, base, page_url


def _pick_title(html: str, video_id: str) -> str:
    t = TITLE_TAG.search(html or "")
    if t:
        name = re.sub(r"\s*-\s*.*$", "", t.group(1).strip())
        name = re.sub(r'[<>:"/\\|?*]', "", name)
        if name and name.lower() not in ("poophd", "vidoy", "download"):
            return name[:180]
    return video_id


def _ajax_headers(page_url: str) -> dict:
    return {
        **HEADERS,
        "Referer": page_url,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }


def _resolve_via_embed_player(
    session: requests.Session,
    base: str,
    file_id: str,
    page_url: str,
    main_html: str,
    timeout: int,
) -> str | None:
    """
    Player Vidoy generasi baru (vidvf.com, dll.):
    POST /token911 → GET /embed.php?bucket=...&id=... → <source src="https://...mp4">
    """
    bucket = "temporary"
    m = EMBED_BUCKET_PATTERN.search(main_html or "")
    if m:
        bucket = m.group(1).strip()
    embed_url = f"{base}/embed.php?bucket={bucket}&id={file_id}"
    try:
        session.post(
            f"{base}/token911",
            data={"id": file_id},
            headers=_ajax_headers(page_url),
            timeout=min(timeout, 30),
        )
    except Exception:
        pass
    try:
        r = session.get(
            embed_url,
            headers={**HEADERS, "Referer": embed_url},
            timeout=timeout,
        )
        r.raise_for_status()
        html = r.text or ""
    except Exception:
        return None

    for pat in (VIDEO_SOURCE_PATTERN, VIDEO_SRC_PATTERN):
        sm = pat.search(html)
        if sm:
            url = sm.group(1).strip()
            if url.startswith("http"):
                return url
    for pat in MP4_IN_HTML.finditer(html):
        url = pat.group(0)
        if "thumbnail" not in url.lower() and "preview" not in url.lower():
            return url
    return None


def _pass_md5_request(
    session: requests.Session,
    page_url: str,
    file_id: str,
    html: str,
    pass_md5: str,
    expires: str,
) -> str | None:
    host_candidates: list[str] = []
    for m in re.finditer(r"https?://([a-z0-9][a-z0-9.-]+)/pass_md5", html, re.I):
        host_candidates.append(m.group(1).lower())
    parsed = urlparse(page_url)
    host_candidates.append(parsed.netloc.lower())
    # host CDN umum di ekosistem dood/vidoy
    for hint in ("dood", "vide", "vid", "dsimg", "imgvdy", "cloudflare", "oppen"):
        for m in re.finditer(rf"https?://([a-z0-9.-]*{hint}[a-z0-9.-]*)/", html, re.I):
            host_candidates.append(m.group(1).lower())

    seen: set[str] = set()
    for host in host_candidates:
        if not host or host in seen:
            continue
        seen.add(host)
        api = f"https://{host}/pass_md5/{file_id}"
        try:
            r = session.get(
                api,
                params={"hash": pass_md5, "expires": expires},
                headers={**HEADERS, "Referer": page_url, "X-Requested-With": "XMLHttpRequest"},
                timeout=30,
            )
            text = (r.text or "").strip()
            if text.startswith("http"):
                return text.split("\n")[0].strip()
            try:
                data = r.json()
                if isinstance(data, dict):
                    for key in ("url", "download_url", "file", "link"):
                        v = data.get(key)
                        if isinstance(v, str) and v.startswith("http"):
                            return v
            except Exception:
                pass
            m = MP4_IN_HTML.search(text)
            if m:
                return m.group(0)
        except Exception:
            continue
    return None


def resolve_stream_url(page_url: str, timeout: int = 45) -> ResolvedStream:
    """
    Ubah link halaman Vidoy (/d/ atau /e/) menjadi URL file yang bisa diunduh.
    """
    file_id, base, page_url = _video_id_and_base(page_url)
    session = requests.Session()
    session.headers.update(HEADERS)

    r = session.get(page_url, timeout=timeout)
    r.raise_for_status()
    html = r.text or ""
    title = _pick_title(html, file_id)

    embed_direct = _resolve_via_embed_player(
        session, base, file_id, page_url, html, timeout
    )
    if embed_direct:
        return ResolvedStream(
            direct_url=embed_direct,
            title=title,
            page_url=page_url,
        )

    for pat in MP4_IN_HTML.finditer(html):
        url = pat.group(0)
        if "thumbnail" not in url.lower() and "preview" not in url.lower():
            return ResolvedStream(direct_url=url, title=title, page_url=page_url)

    pass_md5 = ""
    for pat in PASS_MD5_PATTERNS:
        m = pat.search(html)
        if m:
            pass_md5 = m.group(1)
            break
    expires = ""
    for pat in EXPIRES_PATTERNS:
        m = pat.search(html)
        if m:
            expires = m.group(1)
            break
    if pass_md5 and expires:
        direct = _pass_md5_request(session, page_url, file_id, html, pass_md5, expires)
        if direct:
            is_hls = ".m3u8" in direct.lower()
            return ResolvedStream(
                direct_url=direct,
                title=title,
                is_hls=is_hls,
                page_url=page_url,
            )

    for pat in DOWNLOAD_URL_JSON.finditer(html):
        url = pat.group(1)
        if ".mp4" in url.lower() or ".m3u8" in url.lower():
            return ResolvedStream(
                direct_url=url,
                title=title,
                is_hls=".m3u8" in url.lower(),
                page_url=page_url,
            )

    m3 = M3U8_IN_HTML.search(html)
    if m3:
        return ResolvedStream(
            direct_url=m3.group(0),
            title=title,
            is_hls=True,
            page_url=page_url,
        )

    # JSON tersembunyi di script
    for blob in re.finditer(r"\{[^{}]{0,2000}download[^{}]{0,2000}\}", html, re.I):
        try:
            data = json.loads(blob.group(0).replace("'", '"'))
            if isinstance(data, dict):
                for key in ("download_url", "url", "file"):
                    v = data.get(key)
                    if isinstance(v, str) and v.startswith("http"):
                        return ResolvedStream(
                            direct_url=v,
                            title=title,
                            is_hls=".m3u8" in v.lower(),
                            page_url=page_url,
                        )
        except Exception:
            continue

    raise RuntimeError(
        "Tidak bisa mengambil link unduhan langsung dari halaman ini. "
        "Coba domain lain atau kirim link /d/ yang masih aktif."
    )


def safe_filename(title: str, video_id: str, ext: str = ".mp4") -> str:
    base = (title or video_id).strip() or video_id
    base = re.sub(r'[<>:"/\\|?*\n\r\t]', "", base)
    base = re.sub(r"\s+", " ", base).strip()[:160]
    if not base.lower().endswith(ext.lower().lstrip(".")):
        base += ext if ext.startswith(".") else f".{ext}"
    return base
