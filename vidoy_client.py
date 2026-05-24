# vidoy_client.py - Client untuk API Vidoy (chat, statistik, pencarian)
# Login pakai username & password dari .env; session didapat otomatis
import re
import json
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from typing import Optional

# Pola untuk ekstrak ID video dari URL (domain apa pun dengan /d/ID atau /e/ID)
# - Menerima berbagai format:
#   https://videq.pro/d/xxx
#   http://videq.pro/e/xxx
#   videq.pro/d/xxx
#   www.videq.pro/e/xxx
#   /d/xxx atau d/xxx (fallback di-normalisasi manual)
VIDEO_ID_FROM_URL = re.compile(
    r"(?:https?://)?(?:www\.)?[^\s/]+/(?:d|e)/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
REMOTE_LINK_NORMALIZED = "https://videq.pro/d/{}"

# Host/pola yang biasanya bukan link video (iklan / marketplace / medsos)
_NON_VIDEO_URL_HINTS = (
    "shopee.", "shp.ee", "lazada.", "tokopedia.", "blibli.", "bukalapak.",
    "tiktok.com", "instagram.com", "facebook.com", "wa.me",
)

def _is_probable_non_video_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return True
    if any(h in u for h in _NON_VIDEO_URL_HINTS):
        return True
    if "/promo" in u or "/product" in u or "/affiliate" in u:
        return True
    return False


def is_probable_non_video_url(url: str) -> bool:
    """True jika URL kemungkinan besar bukan link video (iklan/marketplace)."""
    return _is_probable_non_video_url(url)

# Pola untuk link folder Vidoy: https://domain/f/folder_id (atau tanpa http/https)
FOLDER_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?([^\s/]+)/f/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
# Pola untuk ekstrak link video dari HTML: href="/d/xxx" atau href="/e/xxx"
VIDEO_HREF_PATTERN = re.compile(
    r'href=["\']/(?:d|e)/([a-zA-Z0-9_-]+)["\']',
    re.IGNORECASE,
)
# Pola untuk ekstrak nomor halaman dari pagination: /f/xxx?p=1
PAGE_PATTERN = re.compile(
    r'/f/[a-zA-Z0-9_-]+\?p=(\d+)',
    re.IGNORECASE,
)
# Pola untuk ekstrak link folder dari HTML (halaman "deep" yang berisi banyak folder): href="/f/xxx" atau /f/xxx
FOLDER_HREF_PATTERN = re.compile(
    r'href=["\']?(?:https?://[^\s"\']+/)?f/([a-zA-Z0-9_-]+)["\']?',
    re.IGNORECASE,
)
# Fallback: /f/folder_id tanpa href (di dalam teks/atribut)
FOLDER_ID_IN_PAGE_PATTERN = re.compile(
    r'/f/([a-zA-Z0-9_-]+)',
    re.IGNORECASE,
)
# Pola untuk ekstrak nama folder dari HTML: <title>Nama Folder - PoopHD</title> atau elemen lain
FOLDER_NAME_PATTERN = re.compile(
    r'<title>([^<]+?)(?:\s*-\s*PoopHD)?</title>',
    re.IGNORECASE,
)

# Default headers mirip browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://vidoy.com/",
}

HEADERS_JSON = {
    **HEADERS,
    "Accept": "application/json",
}


class VidoyClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._username = username
        self._password = password
        self._logged_in = False
        self._login()

    def _login(self) -> None:
        """Login ke Vidoy (POST /signin), session cookie otomatis tersimpan di self.session."""
        signin_url = f"{self.base_url}/signin"
        # Ambil halaman login dulu (biasanya dapat cookie awal / CSRF)
        self.session.get(signin_url, timeout=15)
        # POST login seperti form browser
        r = self.session.post(
            signin_url,
            data={"username": self._username, "password": self._password},
            allow_redirects=True,
            timeout=15,
        )
        # Cek apakah masih di halaman signin (login gagal) atau sudah redirect
        if r.url.rstrip("/").endswith("/signin"):
            raise RuntimeError("Login Vidoy gagal: username/password salah atau akun diblokir. Cek VIDOY_USERNAME dan VIDOY_PASSWORD di .env.")
        self._logged_in = True

    def _get(self, path: str, params: Optional[dict] = None):
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        r = self.session.get(url, params=params, headers=HEADERS_JSON, timeout=15)
        r.raise_for_status()
        ct = (r.headers.get("content-type", "") or "").lower()
        if "application/json" in ct:
            return r.json()
        # Fallback: beberapa endpoint Vidoy kadang mengirim JSON dengan content-type yang tidak konsisten.
        try:
            return r.json()
        except Exception:
            text = r.text or ""
            try:
                return json.loads(text)
            except Exception:
                return text

    def _post(self, path: str, data: dict, json_mode: bool = False):
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        if json_mode:
            r = self.session.post(url, json=data, headers=HEADERS_JSON, timeout=15)
        else:
            r = self.session.post(url, data=data, headers=HEADERS_JSON, timeout=15)
        r.raise_for_status()
        ct = (r.headers.get("content-type", "") or "").lower()
        if "application/json" in ct:
            return r.json()
        try:
            return r.json()
        except Exception:
            text = r.text or ""
            try:
                return json.loads(text)
            except Exception:
                return text

    # --- Chat ---
    def fetch_chat(self):
        """Ambil semua pesan chat terbaru. Return list of {user, user_id, message, time, verified}."""
        try:
            data = self._get("/chat/fetch")
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def send_chat(self, message: str) -> tuple[bool, str]:
        """
        Kirim pesan ke chat web Vidoy.
        Return: (ok, error_message). Jika ok=True maka error_message kosong.
        """
        text = (message or "").strip()
        if not text:
            return False, "Pesan kosong."

        # Beberapa instalasi Vidoy memakai endpoint/nama field yang berbeda.
        # Coba beberapa kombinasi agar tetap kompatibel.
        endpoint_candidates = [
            "/chat/send",
            "/chat/post",
            "/chat/message",
            "/chat/add",
        ]
        payload_candidates = [
            {"message": text},
            {"msg": text},
            {"text": text},
        ]

        last_err = "Endpoint chat tidak dikenali."
        for ep in endpoint_candidates:
            for payload in payload_candidates:
                try:
                    result = self._post(ep, payload, json_mode=False)
                    # Umumnya sukses jika tidak raise exception.
                    if isinstance(result, dict):
                        # Tangkap pola error umum.
                        status = result.get("status")
                        err = result.get("error")
                        if not err and status in ("error", False):
                            err = result.get("message") or "Unknown error"
                        if err:
                            last_err = str(err)
                            continue
                    return True, ""
                except Exception as e:
                    last_err = str(e)
                    continue
        return False, last_err

    # --- Statistik ---
    def fetch_statistics(self, days: int = 7):
        """Ambil data statistik. days: 7, 30, 60, 365."""
        try:
            return self._get("/statistics", params={"days": days})
        except Exception as e:
            return {"error": str(e)}

    def fetch_overview_metrics(self) -> dict:
        """
        Ambil metrik dashboard dari halaman /overview (HTML) untuk nilai yang tidak ada di /statistics,
        khususnya Balance USD & IDR terbaru.
        Return dict bisa berisi: balance_usd, balance_idr, today_views, avg_cpm, today_earn, this_week, last_week, total.
        """
        try:
            r = self.session.get(f"{self.base_url}/overview", headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text or ""
        except Exception as e:
            return {"error": str(e)}

        def _window_after(label: str, win: int = 900) -> str:
            m = re.search(re.escape(label), html, re.IGNORECASE)
            if not m:
                return ""
            return html[m.end() : m.end() + win]

        def _pick_money(label: str) -> float | None:
            w = _window_after(label)
            if not w:
                return None
            m = re.search(r"\$([\d.,]+)", w)
            if not m:
                return None
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                return None

        def _pick_idr(label: str) -> float | None:
            w = _window_after(label)
            if not w:
                return None
            m = re.search(r"IDR\s*([\d.,]+)", w, re.IGNORECASE)
            if not m:
                return None
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                return None

        def _pick_int(label: str) -> int | None:
            w = _window_after(label)
            if not w:
                return None
            m = re.search(r"(\d[\d,]*)", w)
            if not m:
                return None
            try:
                return int(m.group(1).replace(",", ""))
            except Exception:
                return None

        out: dict[str, object] = {}
        bal_usd = _pick_money("Balance")
        bal_idr = _pick_idr("Balance")
        if bal_usd is not None:
            out["balance_usd"] = bal_usd
        if bal_idr is not None:
            out["balance_idr"] = bal_idr

        tv = _pick_int("Today Views")
        if tv is not None:
            out["today_views"] = tv
        cpm = _pick_money("Avg. CPM")
        if cpm is not None:
            out["avg_cpm"] = cpm
        today_earn = _pick_money("Today")
        if today_earn is not None:
            out["today_earn"] = today_earn
        this_week = _pick_money("This Week")
        if this_week is not None:
            out["this_week"] = this_week
        last_week = _pick_money("Last Week")
        if last_week is not None:
            out["last_week"] = last_week
        total = _pick_money("Total")
        if total is not None:
            out["total"] = total

        return out

    # --- Pencarian ---
    def search(self, query: str, page: int = 1):
        """Cari video. Return {contents: {videos, results, totalResults}, page: {prev, next, current, max, number}, query}."""
        try:
            return self._get("/search", params={"q": query, "p": page})
        except Exception as e:
            return {"error": str(e), "contents": {"videos": [], "results": 0, "totalResults": 0}, "page": {}}

    def get_thumbnail_url(self, video: dict) -> str:
        """Dapatkan URL thumbnail dari objek video."""
        img = video.get("image") or ""
        bucket = video.get("bucket", "default")
        if bucket in ("default", "vidoycdn", "temporary") and img:
            return f"https://i.vide63.com/image/{img}"
        return img or ""

    def copy_video(self, video_id: str, folder: str = "0"):
        """Copy video ke akun (remote upload). Butuh auth. Kirim form seperti browser."""
        try:
            return self._post("/remote/upload", data={
                "folder": folder,
                "links": f"https://videq.pro/d/{video_id}",
                "reff": "search",
            }, json_mode=False)
        except Exception as e:
            return {"error": str(e)}

    # --- Normalisasi link untuk Remote Upload ---
    @staticmethod
    def normalize_remote_link(url: str) -> Optional[str]:
        """
        Ubah URL video apa pun (doodstream, vidstrm, dll) menjadi format
        https://videq.pro/d/{id} agar remote upload Vidoy sukses.
        Return None jika URL tidak valid/tidak bisa diekstrak ID-nya.
        """
        url = (url or "").strip()
        if not url:
            return None
        if _is_probable_non_video_url(url):
            return None

        # Beberapa mirror pakai ID palsu di path embed, ID asli ada di ?id=...
        parse_input = url if url.startswith(("http://", "https://")) else f"https://{url}"
        try:
            parsed = urlparse(parse_input)
            qs = parse_qs(parsed.query)
            for key in ("id", "file", "filecode", "code"):
                vals = qs.get(key) or []
                if vals:
                    cand = unquote(str(vals[0])).strip()
                    if cand and re.match(r"^[a-zA-Z0-9_-]+$", cand):
                        return REMOTE_LINK_NORMALIZED.format(cand)
        except Exception:
            pass

        # Langsung cek pola umum: (opsional) http/https/www + domain + /d|e/ID
        m = VIDEO_ID_FROM_URL.search(url)
        if m:
            return REMOTE_LINK_NORMALIZED.format(m.group(1))

        # Fallback: jika user hanya kirim path seperti "/d/abcd" atau "d/abcd"
        # atau embed "/e/abcd" tanpa domain sama sekali
        path_match = re.search(r"(?:^|[\s])/?(?:d|e)/([a-zA-Z0-9_-]+)", url, re.IGNORECASE)
        if path_match:
            return REMOTE_LINK_NORMALIZED.format(path_match.group(1))

        return None

    @staticmethod
    def normalize_remote_links(links_str: str) -> str:
        """
        Normalisasi banyak link (dipisah newline/spasi) ke format videq.pro/d/xxx.
        Hanya link yang bisa diekstrak ID-nya yang dikembalikan (satu per baris).
        """
        seen = set()
        out = []
        for part in re.split(r"[\r\n\s]+", (links_str or "").strip()):
            part = part.strip()
            if not part:
                continue
            norm = VidoyClient.normalize_remote_link(part)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(norm)
        return "\n".join(out)

    # --- Remote Upload (link bebas) ---
    def remote_upload(self, links: str, folder_id: str = "0", should_cancel=None) -> list:
        """
        Remote upload dari link. Links bisa banyak, dipisah newline.
        Link yang bukan videq.pro/d/ akan dinormalisasi dulu ke videq.pro/d/{id}.
        Return list of {status, filecode?, id?, ...} per link. status 200 = sukses.
        should_cancel: callable tanpa argumen; jika mengembalikan True, sisa link tidak di-upload.
        """
        normalized = self.normalize_remote_links(links)
        if not normalized:
            return [{"status": 400, "error": "Tidak ada link valid. Gunakan format seperti https://videq.pro/d/xxxxx atau link doodstream/vidstrm."}]

        # Satu URL per request: kalau ada link iklan/error di antara banyak link video,
        # yang lain tetap diproses (batch besar sering gagal total dengan 500).
        all_urls = [u for u in normalized.splitlines() if u.strip()]
        if not all_urls:
            return [{"status": 400, "error": "Tidak ada link valid setelah normalisasi."}]

        results: list[dict] = []
        for single in all_urls:
            if should_cancel is not None and should_cancel():
                break
            try:
                r = self._post(
                    "/remote/upload",
                    data={
                        "folder": folder_id,
                        "links": single,
                        "reff": "bot",
                    },
                    json_mode=False,
                )
                if isinstance(r, list):
                    results.extend(r)
                elif isinstance(r, dict):
                    results.append(r)
                else:
                    results.append({"status": 400, "error": "Invalid response", "link": single})
            except Exception as e:
                results.append({"status": 400, "error": str(e), "link": single})
        return results or [{"status": 400, "error": "Tidak ada response dari server."}]

    # --- Folders ---
    def get_folders(self) -> list:
        """Ambil daftar folder (nested). Return list of {id, name, child: [...]}."""
        try:
            data = self._get("/folders")
            if isinstance(data, list):
                return data
            # Fallback struktur response yang berbeda-beda
            if isinstance(data, dict):
                for key in ("folders", "data", "contents", "result"):
                    v = data.get(key)
                    if isinstance(v, list):
                        return v
            return []
        except Exception as e:
            return []

    def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        """
        Buat folder baru. parent_id kosong = di root My Videos.
        Jika parent_id diisi, buat subfolder di dalam folder tersebut (jika API mendukung).
        Return dict response jika tersedia, atau {'error': msg} jika gagal.
        """
        name = (name or "").strip()
        if not name:
            return {"error": "Nama folder kosong."}
        try:
            data = {"folder_name": name}
            if parent_id:
                data["parent_id"] = str(parent_id)
            res = self._post("/add-folder", data=data, json_mode=False)
            # Jika server mengirim JSON, kembalikan apa adanya. Jika HTML, kembalikan dict kosong.
            return res if isinstance(res, dict) else {}
        except Exception as e:
            return {"error": str(e)}

    def move_items(self, move_type: str, item_ids: list[str], move_to: str = "0") -> dict:
        """
        Pindahkan item ke folder lain (fitur Move di web).
        move_type: biasanya 'folder' atau 'video' (sesuai implementasi web).
        item_ids: list of id yang akan dipindah.
        move_to: folder tujuan (id). '0' = root.
        """
        move_type = (move_type or "").strip().lower()
        ids = [str(x).strip() for x in (item_ids or []) if str(x).strip()]
        if not move_type:
            return {"error": "move_type kosong."}
        if not ids:
            return {"error": "Tidak ada item untuk dipindah."}
        try:
            # Di web, move_data diisi lewat textarea; format umum: satu ID per baris.
            move_data = "\n".join(ids)
            res = self._post(
                "/move",
                data={
                    "move_data": move_data,
                    "move_type": move_type,
                    "move_to": str(move_to or "0"),
                },
                json_mode=False,
            )
            return res if isinstance(res, dict) else {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def move_folders(self, folder_ids: list[str], move_to: str) -> dict:
        """Shortcut untuk memindahkan beberapa folder ke folder tujuan."""
        return self.move_items("folder", folder_ids, move_to=move_to)

    def delete_folder(self, folder_id: str) -> dict:
        """
        Hapus folder kosong / tidak terpakai di akun (panel web).
        Endpoint pasti bervariasi antar versi Vidoy; beberapa kandidat dicoba berurutan.
        """
        fid = str(folder_id or "").strip()
        if not fid or fid == "0":
            return {"error": "folder_id tidak valid"}
        # Form panel web: POST /delete — name="files" (ID), name="type" (folder|video)
        candidates = [
            ("/delete", {"files": fid, "type": "folder"}),
            ("/delete", {"files": fid, "type": "Folder"}),
            ("/delete-folder", {"id": fid}),
            ("/delete-folder", {"folder": fid}),
            ("/folder-delete", {"id": fid}),
        ]
        last_err = "tidak ada endpoint hapus yang cocok"
        for path, data in candidates:
            try:
                res = self._post(path, data=data, json_mode=False)
                if isinstance(res, dict):
                    err = res.get("error") or res.get("message")
                    if err and str(err).lower() not in ("ok", "success", "true"):
                        # Kadang API sukses tapi mengembalikan teks error palsu — lanjut coba
                        if res.get("status") in (200, "ok", True) or res.get("success"):
                            return res
                        last_err = str(err)
                        continue
                    return res
                return {"ok": True}
            except Exception as e:
                last_err = str(e)
                continue
        return {"error": last_err}

    # --- Rename (video/folder) ---
    def rename_item(self, item_type: str, item_id: str, new_name: str) -> dict:
        """
        Rename item via endpoint web (/rename).
        Berdasarkan HTML web Vidoy:
        - file: id item
        - type: 'video' atau 'folder'
        - name: nama baru
        """
        item_type = (item_type or "").strip().lower()
        item_id = str(item_id or "").strip()
        new_name = (new_name or "").strip()
        if item_type not in ("video", "folder"):
            return {"error": "item_type harus 'video' atau 'folder'."}
        if not item_id:
            return {"error": "item_id kosong."}
        if not new_name:
            return {"error": "new_name kosong."}
        try:
            res = self._post(
                "/rename",
                data={"file": item_id, "type": item_type, "name": new_name},
                json_mode=False,
            )
            return res if isinstance(res, dict) else {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def _flatten_folders(self, folders: list, parent_path: str = "") -> list:
        """Ubah nested folders jadi list flat untuk keyboard."""
        out = []
        for f in folders or []:
            if not isinstance(f, dict):
                continue
            name = (f.get("name") or "").strip()
            folder_id = str(f.get("id", "")).strip()
            path = f"{parent_path}/{name}" if parent_path else name
            out.append({"id": folder_id, "name": name, "path": path})
            child = f.get("child") or f.get("children") or f.get("sub") or []
            if isinstance(child, list) and child:
                out.extend(self._flatten_folders(child, path))
        return out

    # --- My Videos ---
    def get_my_videos(
        self,
        folder_id: str = "",
        page: int = 1,
        per_page: int = 100,
        query: str = "",
        sort_by: str = "date",
        order_by: str = "DESC",
    ) -> dict:
        """
        Ambil video dari My Videos. folder_id kosong = root.
        Return {contents: {videos, folders, totalResults, publicSite}, page, ...}
        """
        try:
            params = {
                "p": page,
                "l": per_page,
                "q": query,
                "f": sort_by,
                "s": order_by,
            }
            if folder_id:
                params["folder"] = folder_id
            r = self.session.get(
                f"{self.base_url}/videos_ajax",
                params=params,
                headers=HEADERS_JSON,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if not data.get("contents"):
                data.setdefault("contents", {})
            data["contents"].setdefault("videos", [])
            data["contents"].setdefault("publicSite", ["vidstrm.cloud"])
            return data
        except Exception as e:
            return {"error": str(e), "contents": {"videos": [], "publicSite": ["vidstrm.cloud"]}}

    # --- Ekstrak Link dari Folder Orang ---
    @staticmethod
    def extract_links_from_folder(folder_url: str) -> tuple[list[str], str, str]:
        """
        Ekstrak semua link video dari halaman folder share orang (bisa multi-halaman).
        folder_url: https://videq.pro/f/i4qslaevbce atau link domain Vidoy lainnya
        Return: (list_url_video, error_message, folder_name). 
        Jika sukses, error_message kosong. folder_name bisa kosong jika tidak ditemukan.
        """
        folder_url = (folder_url or "").strip()
        if not folder_url:
            return [], "Link folder kosong.", ""
        m = FOLDER_LINK_PATTERN.search(folder_url)
        if not m:
            return [], "Link folder tidak valid. Gunakan format: https://domain/f/folder_id", ""
        domain = m.group(1).lower()
        folder_id = m.group(2)
        base = f"https://{domain}"
        url_page1 = f"{base}/f/{folder_id}"
        seen_ids: set[str] = set()
        all_urls: list[str] = []
        max_page = 1
        folder_name = ""
        try:
            r = requests.get(url_page1, headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text
            # Ekstrak nama folder dari <title> atau elemen HTML lainnya
            title_match = FOLDER_NAME_PATTERN.search(html)
            if title_match:
                folder_name = title_match.group(1).strip()
                # Bersihkan nama folder dari karakter yang tidak valid dan emoji
                folder_name = re.sub(r'[<>:"/\\|?*]', '', folder_name)
                # Hapus emoji (Unicode ranges untuk emoji)
                emoji_pattern = re.compile(
                    "["
                    "\U0001F600-\U0001F64F"  # emoticons
                    "\U0001F300-\U0001F5FF"  # symbols & pictographs
                    "\U0001F680-\U0001F6FF"  # transport & map symbols
                    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
                    "\U00002702-\U000027B0"
                    "\U000024C2-\U0001F251"
                    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
                    "\U0001FA00-\U0001FA6F"  # Chess Symbols
                    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
                    "\U00002600-\U000026FF"  # Miscellaneous Symbols
                    "\U00002700-\U000027BF"  # Dingbats
                    "]+",
                    flags=re.UNICODE,
                )
                folder_name = emoji_pattern.sub("", folder_name)
                folder_name = re.sub(r"\s+", " ", folder_name).strip()
        except Exception as e:
            return [], f"Gagal fetch halaman: {e}", ""
        # Ekstrak video ID dari HTML
        for vid in VIDEO_HREF_PATTERN.findall(html):
            if vid not in seen_ids:
                seen_ids.add(vid)
                all_urls.append(f"{base}/d/{vid}")
        # Ekstrak max page dari pagination
        for p_match in PAGE_PATTERN.findall(html):
            pn = int(p_match)
            if pn > max_page:
                max_page = pn
        # Fetch halaman 2, 3, ... max_page
        for p in range(2, max_page + 1):
            try:
                r2 = requests.get(url_page1, params={"p": p}, headers=HEADERS, timeout=15)
                r2.raise_for_status()
                html2 = r2.text
            except Exception:
                continue
            for vid in VIDEO_HREF_PATTERN.findall(html2):
                if vid not in seen_ids:
                    seen_ids.add(vid)
                    all_urls.append(f"{base}/d/{vid}")
        if not all_urls:
            return [], "Tidak ada video ditemukan di folder ini.", folder_name
        return all_urls, "", folder_name

    # --- Ekstrak Link Folder dari Halaman "Deep" (folder dalam folder) ---
    @staticmethod
    def extract_folder_links_from_page(page_url: str) -> tuple[list[str], list[str], str]:
        """
        Ekstrak semua link folder dari halaman yang berisi banyak folder (deep/thread).
        page_url: URL halaman yang menampilkan daftar folder (contoh: https://domain/f/parent_id)
        Return: (list_url_folder, list_nama_folder, error_message).
        Jika sukses, error_message kosong. List berisi URL penuh tiap subfolder
        dan (jika bisa dideteksi) nama folder yang tampil di tombol/link.
        """
        page_url = (page_url or "").strip()
        if not page_url:
            return [], [], "Link halaman kosong."
        m = FOLDER_LINK_PATTERN.search(page_url)
        if not m:
            return [], [], "Link tidak valid. Gunakan format: https://domain/f/folder_id (halaman yang berisi daftar folder)."
        domain = m.group(1).lower()
        base = f"https://{domain}"
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text
        except Exception as e:
            return [], [], f"Gagal fetch halaman: {e}"
        # Ekstrak folder ID dari href="/f/xxx" atau href="https://.../f/xxx"
        seen_ids: set[str] = set()
        folder_urls: list[str] = []
        for folder_id in FOLDER_HREF_PATTERN.findall(html):
            if folder_id not in seen_ids:
                seen_ids.add(folder_id)
                folder_urls.append(f"{base}/f/{folder_id}")
        # Fallback: cari pola /f/xxx di seluruh HTML (bisa tanpa href)
        if not folder_urls:
            for folder_id in FOLDER_ID_IN_PAGE_PATTERN.findall(html):
                if folder_id not in seen_ids:
                    seen_ids.add(folder_id)
                    folder_urls.append(f"{base}/f/{folder_id}")
        # Buang folder_id yang sama dengan halaman saat ini (parent)
        parent_id = m.group(2)
        folder_urls = [u for u in folder_urls if not u.endswith(f"/f/{parent_id}")]
        if not folder_urls:
            return [], [], "Tidak ada link folder ditemukan di halaman ini. Pastikan link mengarah ke halaman yang menampilkan daftar folder (mis. Thread)."

        # Coba ambil nama folder dari teks di dalam <a>...</a> yang mengandung link /f/{id}
        folder_names: list[str] = []
        for url in folder_urls:
            name = ""
            id_match = re.search(r"/f/([a-zA-Z0-9_-]+)", url)
            folder_id = id_match.group(1) if id_match else ""
            if folder_id:
                try:
                    # Cari anchor yang mengarah ke folder_id lalu ambil teks akhirnya (setelah SVG/dll)
                    anchor_pattern = re.compile(
                        r'href=["\'](?:https?://[^\s"\']+/)?/?f/'
                        + re.escape(folder_id)
                        + r'["\'][^>]*>(.*?)</a>',
                        re.IGNORECASE | re.DOTALL,
                    )
                    m_anchor = anchor_pattern.search(html)
                    if m_anchor:
                        inner_html = m_anchor.group(1)
                        # Hapus tag HTML di dalam anchor, sisakan teks polos
                        inner_text = re.sub(r"<.*?>", "", inner_html)
                        inner_text = re.sub(r"\s+", " ", inner_text).strip()
                        name = inner_text
                except Exception:
                    name = ""
            folder_names.append(name)

        return folder_urls, folder_names, ""

    # --- Ekstrak Link Video dari Halaman "Deep" (video dalam halaman/thread) ---
    @staticmethod
    def extract_video_links_from_page(page_url: str) -> tuple[list[str], str]:
        """
        Ekstrak semua link video (/d/ atau /e/) dari sebuah halaman HTML.
        Cocok untuk halaman thread/landing yang memuat banyak video sekaligus.

        page_url: URL halaman yang bisa diakses publik (biasanya domain Vidoy) dan mengandung link video.
        Return: (list_url_video, error_message). Jika sukses, error_message kosong.
        """
        page_url = (page_url or "").strip()
        if not page_url:
            return [], "Link halaman kosong."
        # Coba tebak base domain dari URL (agar link relatif bisa jadi URL penuh)
        domain = ""
        m_dom = re.search(r"https?://([^/]+)/", page_url, re.IGNORECASE)
        if m_dom:
            domain = (m_dom.group(1) or "").strip().lower()
        base = f"https://{domain}" if domain else ""
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text or ""
        except Exception as e:
            return [], f"Gagal fetch halaman: {e}"

        seen_ids: set[str] = set()
        out: list[str] = []

        # 1) Pola href="/d/xxx" atau href="/e/xxx" (paling umum)
        for vid in VIDEO_HREF_PATTERN.findall(html):
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            if base:
                out.append(f"{base}/d/{vid}")
            else:
                out.append(f"https://videq.pro/d/{vid}")

        # 2) Fallback: cari semua URL video yang sudah lengkap di HTML
        for m in VIDEO_ID_FROM_URL.finditer(html):
            # VIDEO_ID_FROM_URL hanya punya 1 group (id)
            vid = m.group(1)
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            # Pertahankan tipe /d/ atau /e/ jika muncul di match
            raw = m.group(0) or ""
            link_type = "e" if "/e/" in raw.lower() else "d"
            if base:
                out.append(f"{base}/{link_type}/{vid}")
            else:
                out.append(f"https://videq.pro/{link_type}/{vid}")

        if not out:
            return [], "Tidak ada link video ditemukan di halaman ini."
        return out, ""

    def get_share_links(
        self,
        video_ids: list,
        link_type: str = "download",
        site: str = "https://vidstrm.cloud",
    ) -> list[str]:
        """
        Generate share link untuk video. link_type: 'download' atau 'embed'.
        Return list URL.
        """
        base = site.rstrip("/").replace("https://", "").replace("http://", "")
        base = f"https://{base}"
        out = []
        for vid in video_ids:
            vid_str = str(vid).strip()
            if not vid_str:
                continue
            if link_type == "embed":
                out.append(f"{base}/e/{vid_str}")
            else:
                out.append(f"{base}/d/{vid_str}")
        return out
