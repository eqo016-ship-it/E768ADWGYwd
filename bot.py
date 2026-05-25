"""
Bot Telegram (Pyrogram): unduh video dari link Vidoy (/d/, /e/, /f/).
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import config
from download_worker import (
    cleanup_dir,
    cleanup_path,
    download_to_path,
    remote_content_length,
    validate_local_video,
)
from health_server import start_health_server
from progress_ui import TelegramProgress
from stream_resolver import resolve_stream_url
from vidoy_extract import FOLDER_LINK_PATTERN, VIDEO_ID_FROM_URL, VidoyClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LINK_PATTERN = re.compile(
    r"https?://(?:www\.)?[^\s/]+/(?:f|d|e)/[a-zA-Z0-9_-]+",
    re.I,
)

# State per user (setara context.user_data di PTB)
_user_state: dict[int, dict[str, Any]] = {}


def _state(user_id: int) -> dict[str, Any]:
    if user_id not in _user_state:
        _user_state[user_id] = {}
    return _user_state[user_id]


def _allowed(user_id: int | None) -> bool:
    if not config.ADMIN_IDS:
        return True
    return user_id in config.ADMIN_IDS


def _normalize_folder_url(url: str) -> str:
    url = (url or "").strip()
    m = FOLDER_LINK_PATTERN.search(url)
    if m:
        dom = m.group(1).lower()
        return f"https://{dom}/f/{m.group(2)}"
    return url


def _is_folder(url: str) -> bool:
    return bool(FOLDER_LINK_PATTERN.search(url))


def _is_video(url: str) -> bool:
    return bool(VIDEO_ID_FROM_URL.search(url))


def _extract_links_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(LINK_PATTERN.findall(text or "")))


def _scan_folder(url: str) -> dict:
    url = _normalize_folder_url(url)
    videos, err, folder_name = VidoyClient.extract_links_from_folder(url)
    sub_urls, sub_names, err2 = VidoyClient.extract_folder_links_from_page(url)
    if err and not videos and not sub_urls:
        raise RuntimeError(err)
    if err2 and not sub_urls and not videos:
        raise RuntimeError(err2)
    pairs = []
    for i, su in enumerate(sub_urls):
        name = sub_names[i] if i < len(sub_names) and sub_names[i] else f"Subfolder {i + 1}"
        pairs.append((su, name[:40]))
    return {
        "url": url,
        "name": folder_name or "Folder",
        "videos": videos,
        "subfolders": pairs,
    }


def _kb_main_video() -> tuple[InlineKeyboardMarkup, str]:
    tok = secrets.token_hex(4)
    return (
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬇️ Unduh video ini", callback_data=f"vdl:go:{tok}"
                    )
                ],
                [InlineKeyboardButton("❌ Batal", callback_data=f"vdl:x:{tok}")],
            ]
        ),
        tok,
    )


def _kb_folder_menu(scan: dict, token: str) -> InlineKeyboardMarkup:
    rows = []
    n_vid = len(scan["videos"])
    if n_vid:
        rows.append(
            [
                InlineKeyboardButton(
                    f"⬇️ Unduh semua video di sini ({n_vid})",
                    callback_data=f"vdl:fa:{token}",
                )
            ]
        )
    for idx, (_url, name) in enumerate(scan["subfolders"][:12]):
        rows.append(
            [InlineKeyboardButton(f"📁 {name}", callback_data=f"vdl:fs:{token}:{idx}")]
        )
    if len(scan["subfolders"]) > 12:
        rows.append([InlineKeyboardButton("…", callback_data=f"vdl:noop:{token}")])
    rows.append([InlineKeyboardButton("❌ Batal", callback_data=f"vdl:x:{token}")])
    return InlineKeyboardMarkup(rows)


def _upload_limit_hint() -> str:
    if config.IS_USERBOT:
        return f", via <b>Pyrogram userbot</b> hingga ~{config.MAX_TELEGRAM_MB:.0f} MB"
    return " — batas <b>bot</b> Telegram ~50 MB (isi <code>SESSION_STRING</code> untuk file besar)"


def _format_error(e: Exception) -> str:
    msg = str(e).strip() or type(e).__name__
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return (
            f"{msg}\n\n"
            "<i>Unduhan/upload kehabisan waktu. File besar butuh koneksi stabil. "
            "Bot akan mengirim link langsung jika bisa.</i>"
        )
    return msg


async def _notify_status(
    client: Client,
    status_msg: Message | None,
    chat_id: int,
    text: str,
) -> Message:
    try:
        if status_msg:
            return await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return await client.send_message(chat_id, text, parse_mode=ParseMode.HTML)


async def _send_direct_link_only(
    client: Client,
    chat_id: int,
    caption: str,
    direct_url: str,
    reason: str,
):
    await client.send_message(
        chat_id,
        (
            f"{caption}\n\n"
            f"ℹ️ {reason}\n"
            f"Link unduhan:\n<code>{direct_url}</code>"
        ),
        parse_mode=ParseMode.HTML,
    )


def _job_download_dir(user_id: int) -> Path:
    """Subfolder di DOWNLOAD_DIR untuk satu sesi unduh."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = config.DOWNLOAD_DIR / f"user_{user_id}_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


async def _send_file_or_link(
    client: Client,
    chat_id: int,
    local_path: Path | None,
    caption: str,
    fallback_url: str,
    progress: TelegramProgress | None = None,
):
    max_bytes = int(config.MAX_TELEGRAM_MB * 1024 * 1024)
    if not local_path or not local_path.exists():
        await _send_direct_link_only(
            client,
            chat_id,
            caption,
            fallback_url,
            "File lokal tidak ada — gunakan link di bawah.",
        )
        return

    size = local_path.stat().st_size
    ok, err = await asyncio.to_thread(validate_local_video, local_path, None)
    if not ok:
        await _send_direct_link_only(
            client,
            chat_id,
            caption.replace("✅", "⚠️"),
            fallback_url,
            f"File tidak valid untuk preview Telegram: {err}",
        )
        return

    try:
        if size <= max_bytes:
            path = str(local_path.resolve())
            upload_cb = None
            if progress:
                progress.reset_pct()
                await progress.show(
                    "upload",
                    0,
                    current=0,
                    total=size,
                    note=local_path.name,
                )
                upload_cb = progress.thread_callback("upload", note=local_path.name)
            await asyncio.wait_for(
                client.send_video(
                    chat_id,
                    video=path,
                    caption=caption[:1024],
                    supports_streaming=True,
                    progress=upload_cb,
                ),
                timeout=config.DOWNLOAD_READ_TIMEOUT + 120,
            )
            if progress:
                await progress.show(
                    "upload",
                    100,
                    current=size,
                    total=size,
                    note="Selesai ✓",
                )
        else:
            mb = size / (1024 * 1024)
            await _send_direct_link_only(
                client,
                chat_id,
                caption,
                fallback_url,
                f"File <b>{mb:.1f} MB</b> — terlalu besar (maks <b>{config.MAX_TELEGRAM_MB:.0f} MB</b>).",
            )
    finally:
        cleanup_path(local_path)


async def _process_one_video(
    client: Client,
    chat_id: int,
    page_url: str,
    index: int,
    total: int,
    dest: Path,
    progress: TelegramProgress | None = None,
) -> tuple[bool, bool]:
    cap_prefix = f"[{index}/{total}]"
    resolved = None
    local_path = None
    try:
        resolved = await asyncio.to_thread(
            resolve_stream_url, page_url, config.REQUEST_TIMEOUT
        )
        dl_max = int(config.MAX_DOWNLOAD_MB * 1024 * 1024)
        remote_size = await asyncio.to_thread(
            remote_content_length,
            resolved,
            config.DOWNLOAD_CONNECT_TIMEOUT,
        )
        title = resolved.title or page_url
        caption_ok = f"✅ {cap_prefix} {title}"
        if progress:
            progress.set_job(index, total)
            progress.set_title(title)

        limit = remote_size or 0
        if limit > dl_max:
            mb = limit / (1024 * 1024)
            await _send_direct_link_only(
                client,
                chat_id,
                caption_ok,
                resolved.direct_url,
                (
                    f"Video <b>{mb:.1f} MB</b> — melebihi batas "
                    f"(maks ≈ <b>{config.MAX_TELEGRAM_MB:.0f} MB</b>). "
                    "Salin link di bawah ke IDM / browser."
                ),
            )
            return True, False

        dl_cb = None
        if progress:
            progress.reset_pct()
            await progress.show(
                "download",
                0,
                current=0,
                total=remote_size or 0,
                note="Menyimpan ke folder downloads…",
            )
            dl_cb = progress.thread_callback("download")

        local_path = await asyncio.to_thread(
            download_to_path,
            resolved,
            dest,
            config.DOWNLOAD_CONNECT_TIMEOUT,
            config.DOWNLOAD_READ_TIMEOUT,
            dl_cb,
        )
        if progress:
            fsize = local_path.stat().st_size
            await progress.show(
                "download",
                100,
                current=fsize,
                total=fsize,
                note=f"Tersimpan: {local_path.name}",
            )
        await _send_file_or_link(
            client,
            chat_id,
            local_path,
            caption_ok,
            resolved.direct_url,
            progress,
        )
        local_path = None
        return True, False
    except Exception as e:
        logger.warning("Gagal unduh %s: %s", page_url, e)
        hint = ""
        if not resolved:
            try:
                resolved = await asyncio.to_thread(
                    resolve_stream_url, page_url, config.REQUEST_TIMEOUT
                )
            except Exception:
                pass
        if resolved:
            hint = f"\n\nLink langsung:\n<code>{resolved.direct_url}</code>"
        cleanup_path(local_path)
        await client.send_message(
            chat_id,
            (
                f"❌ {cap_prefix} Gagal\n"
                f"<code>{page_url}</code>\n\n"
                f"{_format_error(e)}{hint}"
            ),
            parse_mode=ParseMode.HTML,
        )
        return False, True


async def _job_download_videos(
    client: Client,
    user_id: int,
    chat_id: int,
    video_urls: list[str],
    label: str,
):
    st = _state(user_id)
    urls = video_urls[: config.MAX_VIDEOS_PER_JOB]
    total = len(urls)
    if not urls:
        await client.send_message(chat_id, "Tidak ada video untuk diunduh.")
        return

    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_dir = _job_download_dir(user_id)
    dest = job_dir

    status = await client.send_message(
        chat_id,
        (
            f"⏳ Memulai unduh <b>{total}</b> video — {label}\n"
            f"📁 Folder: <code>downloads/{dest.name}</code>\n"
            "<i>Video disimpan di folder <b>downloads</b>, lalu dikirim ke Telegram.</i>"
        ),
        parse_mode=ParseMode.HTML,
    )
    ok, fail = 0, 0
    loop = asyncio.get_running_loop()
    tg_progress = TelegramProgress(
        client, status, chat_id, loop, job_index=1, job_total=total
    )

    try:
        for i, page_url in enumerate(urls, 1):
            tg_progress.set_job(i, total)
            await tg_progress.show(
                "resolve",
                0,
                note=f"Mengambil link…",
            )
            success, failed = await _process_one_video(
                client,
                chat_id,
                page_url,
                i,
                total,
                dest,
                tg_progress,
            )
            if success:
                ok += 1
            if failed:
                fail += 1
            if i < total:
                await asyncio.sleep(config.DELAY_BETWEEN_VIDEOS_SEC)
    finally:
        try:
            if job_dir.exists() and not any(job_dir.iterdir()):
                cleanup_dir(job_dir)
        except Exception:
            pass

    await _notify_status(
        client,
        tg_progress.status_msg,
        chat_id,
        (
            f"🏁 <b>Selesai</b> — {label}\n"
            f"Berhasil: <b>{ok}</b> | Gagal: <b>{fail}</b> | Total: <b>{total}</b>"
        ),
    )
    st.pop("download_busy", None)


def _spawn_download_job(
    client: Client,
    user_id: int,
    chat_id: int,
    video_urls: list[str],
    label: str,
) -> bool:
    st = _state(user_id)
    if st.get("download_busy"):
        return False
    st["download_busy"] = True

    async def _safe():
        try:
            await _job_download_videos(client, user_id, chat_id, video_urls, label)
        except Exception as e:
            logger.exception("Job unduh crash: %s", label)
            st.pop("download_busy", None)
            await client.send_message(
                chat_id,
                (
                    f"❌ <b>Unduhan terhenti mendadak</b> — {label}\n\n"
                    f"{_format_error(e)}\n\n"
                    "Coba lagi dengan lebih sedikit video, atau periksa koneksi."
                ),
                parse_mode=ParseMode.HTML,
            )

    asyncio.create_task(_safe())
    return True


def _create_client() -> Client:
    common = dict(
        name=config.SESSION_NAME,
        api_id=int(config.TELEGRAM_API_ID),
        api_hash=config.TELEGRAM_API_HASH,
        workdir=str(Path(__file__).resolve().parent),
        sleep_threshold=60,
    )
    if config.SESSION_STRING:
        return Client(**common, session_string=config.SESSION_STRING)
    return Client(**common, bot_token=config.TELEGRAM_BOT_TOKEN)


app = _create_client()


@app.on_message(filters.command("start"))
async def cmd_start(_client: Client, message: Message):
    uid = message.from_user.id if message.from_user else 0
    if not _allowed(uid):
        await message.reply_text("Bot ini dibatasi untuk admin tertentu.")
        return
    await message.reply_text(
        "👋 <b>Bot Unduh Vidoy</b> (Pyrogram)\n\n"
        "Kirim link:\n"
        "• <b>Video</b> — <code>https://domain/d/ID</code> atau <code>/e/ID</code>\n"
        "• <b>Folder</b> — <code>https://domain/f/ID</code>\n\n"
        "Jika folder berisi <b>subfolder</b>, bot menampilkan daftar subfolder "
        "dan opsi unduh semua video di folder yang sedang dibuka.\n\n"
        "Perintah: /help",
        parse_mode=ParseMode.HTML,
    )


@app.on_message(filters.command("help"))
async def cmd_help(_client: Client, message: Message):
    await message.reply_text(
        "<b>Cara pakai</b>\n"
        "1. Tempel 1 link video atau folder.\n"
        "2. Pilih tombol di bawah pesan.\n"
        "3. Video disimpan di folder <b>downloads/</b> lalu dikirim ke chat "
        f"(maks <b>{config.MAX_TELEGRAM_MB:.0f} MB</b>{_upload_limit_hint()}).\n"
        "4. Progress unduh & upload: <code>proses download 1/30</code> + bar ⏱️━━●.\n"
        "5. Video lebih besar / timeout: bot kirim <b>link unduhan</b> saja.\n"
        "6. Thumbnail hitam & 0:00 = file rusak/tidak lengkap (sudah dicek otomatis).\n\n"
        "<b>Folder dalam folder</b>: buka subfolder lewat tombol 📁, "
        "lalu unduh video di level itu.\n\n"
        f"Batas per job: {config.MAX_VIDEOS_PER_JOB} video.",
        parse_mode=ParseMode.HTML,
    )


@app.on_message(filters.text)
async def handle_text(_client: Client, message: Message):
    if not message.text or message.text.startswith("/"):
        return
    uid = message.from_user.id if message.from_user else 0
    if not _allowed(uid):
        await message.reply_text("Akses ditolak.")
        return

    links = _extract_links_from_text(message.text or "")
    if not links:
        await message.reply_text(
            "Tidak ada link Vidoy. Contoh:\n"
            "https://videq.pro/d/xxxxx\n"
            "https://videq.pro/f/xxxxx"
        )
        return

    if len(links) > 1:
        await message.reply_text("Satu pesan = satu link. Kirim ulang satu link saja.")
        return

    url = links[0]
    st = _state(uid)

    if _is_video(url):
        kb, tok = _kb_main_video()
        st[f"offer_{tok}"] = {"type": "video", "url": url}
        await message.reply_text(
            "🎬 <b>Link video terdeteksi</b>\n\nPilih aksi:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if _is_folder(url):
        try:
            scan = await asyncio.to_thread(_scan_folder, url)
        except Exception as e:
            await message.reply_text(f"❌ Gagal baca folder: {e}")
            return
        tok = secrets.token_hex(4)
        st[f"offer_{tok}"] = {"type": "folder", "scan": scan, "stack": []}
        await message.reply_text(
            f"📂 <b>{scan['name']}</b>\n"
            f"Video di folder ini: <b>{len(scan['videos'])}</b>\n"
            f"Subfolder: <b>{len(scan['subfolders'])}</b>\n\n"
            "Pilih opsi di bawah:",
            parse_mode=ParseMode.HTML,
            reply_markup=_kb_folder_menu(scan, tok),
        )
        return

    await message.reply_text("Format link tidak dikenali.")


@app.on_callback_query(filters.regex(r"^vdl:"))
async def callback_vdl(client: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not _allowed(uid):
        await query.answer("Akses ditolak.", show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    token = parts[2]
    st = _state(uid)

    if action == "noop":
        await query.answer(
            "Terlalu banyak subfolder. Buka link subfolder secara terpisah.",
            show_alert=True,
        )
        return

    offer = st.get(f"offer_{token}")
    if not offer:
        await query.answer("Menu kedaluwarsa. Kirim link lagi.", show_alert=True)
        return

    chat_id = query.message.chat.id if query.message else 0
    await query.answer()

    if action == "x":
        st.pop(f"offer_{token}", None)
        if query.message:
            await query.message.edit_text("Dibatalkan.")
        return

    if action == "go" and offer.get("type") == "video":
        url = offer.get("url")
        st.pop(f"offer_{token}", None)
        if query.message:
            await query.message.edit_text("⏳ Mengunduh 1 video…")
        if not _spawn_download_job(client, uid, chat_id, [url], "satu video"):
            await client.send_message(
                chat_id, "⚠️ Masih ada unduhan berjalan. Tunggu sampai selesai dulu."
            )
        return

    if action == "fa" and offer.get("type") == "folder":
        scan = offer.get("scan") or {}
        videos = scan.get("videos") or []
        st.pop(f"offer_{token}", None)
        name = scan.get("name", "Folder")
        if query.message:
            await query.message.edit_text(
                f"⏳ Mengunduh semua video di <b>{name}</b>…",
                parse_mode=ParseMode.HTML,
            )
        if not _spawn_download_job(client, uid, chat_id, videos, name):
            await client.send_message(
                chat_id, "⚠️ Masih ada unduhan berjalan. Tunggu sampai selesai dulu."
            )
        return

    if action == "fs" and offer.get("type") == "folder" and len(parts) >= 4:
        try:
            idx = int(parts[3])
        except ValueError:
            return
        scan = offer.get("scan") or {}
        subs = scan.get("subfolders") or []
        if idx < 0 or idx >= len(subs):
            await query.answer("Subfolder tidak valid.", show_alert=True)
            return
        sub_url, sub_name = subs[idx]
        try:
            new_scan = await asyncio.to_thread(_scan_folder, sub_url)
        except Exception as e:
            await query.answer(f"Gagal buka subfolder: {e}", show_alert=True)
            return
        new_tok = secrets.token_hex(4)
        stack = list(offer.get("stack") or [])
        stack.append({"name": scan.get("name"), "url": scan.get("url")})
        st.pop(f"offer_{token}", None)
        st[f"offer_{new_tok}"] = {
            "type": "folder",
            "scan": new_scan,
            "stack": stack,
        }
        trail = " → ".join(s["name"] for s in stack) + f" → {sub_name}"
        if query.message:
            await query.message.edit_text(
                f"📂 <b>{new_scan['name']}</b>\n"
                f"<i>{trail}</i>\n\n"
                f"Video: <b>{len(new_scan['videos'])}</b> | "
                f"Subfolder: <b>{len(new_scan['subfolders'])}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_folder_menu(new_scan, new_tok),
            )
        return


def main():
    errs = config.validate()
    if errs:
        for e in errs:
            print(e)
        return

    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for part in config.DOWNLOAD_DIR.rglob("*.part"):
        cleanup_path(part)
    start_health_server(config.PORT)

    mode = "userbot" if config.IS_USERBOT else "bot"
    print(
        f"Vidoy Downloader (Pyrogram/{mode}) — "
        f"upload maks ~{config.MAX_TELEGRAM_MB:.0f} MB, health :{config.PORT}"
    )
    app.run()


if __name__ == "__main__":
    main()
