"""
@name: Vidoy Downloader Bot v2.0
Bot Telegram: unduh video dari link Vidoy (/d/, /e/, /f/).
Folder bersarang: tampilkan subfolder + opsi unduh semua video di folder aktif.
"""
import asyncio
import logging
import re
import secrets
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram import InputFile

import config
from download_worker import (
    cleanup_dir,
    cleanup_path,
    download_to_path,
    remote_content_length,
    validate_local_video,
)
from health_server import start_health_server
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
    """Video + subfolder di satu halaman folder."""
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


def _kb_main_video(page_url: str) -> InlineKeyboardMarkup:
    tok = secrets.token_hex(4)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬇️ Unduh video ini", callback_data=f"vdl:go:{tok}")],
            [InlineKeyboardButton("❌ Batal", callback_data=f"vdl:x:{tok}")],
        ]
    ), tok


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
        rows.append(
            [InlineKeyboardButton("…", callback_data=f"vdl:noop:{token}")]
        )
    rows.append([InlineKeyboardButton("❌ Batal", callback_data=f"vdl:x:{token}")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user and update.effective_user.id):
        await update.message.reply_text("Bot ini dibatasi untuk admin tertentu.")
        return
    await update.message.reply_text(
        "👋 <b>Bot Unduh Vidoy</b>\n\n"
        "Kirim link:\n"
        "• <b>Video</b> — <code>https://domain/d/ID</code> atau <code>/e/ID</code>\n"
        "• <b>Folder</b> — <code>https://domain/f/ID</code>\n\n"
        "Jika folder berisi <b>subfolder</b>, bot menampilkan daftar subfolder "
        "dan opsi unduh semua video di folder yang sedang dibuka.\n\n"
        "Perintah: /help",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Cara pakai</b>\n"
        "1. Tempel 1 link video atau folder.\n"
        "2. Pilih tombol di bawah pesan.\n"
        "3. Bot mengirim video ke chat (maks <b>2000 MB / 2 GB</b> — "
        "menggunakan server Local Telegram Bot API).\n"
        "4. Video lebih besar / timeout: bot kirim <b>link unduhan</b> saja.\n"
        "5. Thumbnail hitam & 0:00 = file rusak/tidak lengkap (sudah dicek otomatis).\n\n"
        "<b>Folder dalam folder</b>: buka subfolder lewat tombol 📁, "
        "lalu unduh video di level itu.\n\n"
        f"Batas per job: {config.MAX_VIDEOS_PER_JOB} video.",
        parse_mode=ParseMode.HTML,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not _allowed(update.effective_user and update.effective_user.id):
        await update.message.reply_text("Akses ditolak.")
        return

    links = _extract_links_from_text(update.message.text)
    if not links:
        await update.message.reply_text(
            "Tidak ada link Vidoy. Contoh:\n"
            "https://videq.pro/d/xxxxx\n"
            "https://videq.pro/f/xxxxx"
        )
        return

    if len(links) > 1:
        await update.message.reply_text(
            "Satu pesan = satu link. Kirim ulang satu link saja."
        )
        return

    url = links[0]
    if _is_video(url):
        kb, tok = _kb_main_video(url)
        context.user_data[f"offer_{tok}"] = {"type": "video", "url": url}
        await update.message.reply_text(
            "🎬 <b>Link video terdeteksi</b>\n\nPilih aksi:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if _is_folder(url):
        try:
            scan = await asyncio.to_thread(_scan_folder, url)
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal baca folder: {e}")
            return
        tok = secrets.token_hex(4)
        context.user_data[f"offer_{tok}"] = {"type": "folder", "scan": scan, "stack": []}
        n_sub = len(scan["subfolders"])
        n_vid = len(scan["videos"])
        await update.message.reply_text(
            f"📂 <b>{scan['name']}</b>\n"
            f"Video di folder ini: <b>{n_vid}</b>\n"
            f"Subfolder: <b>{n_sub}</b>\n\n"
            "Pilih opsi di bawah:",
            parse_mode=ParseMode.HTML,
            reply_markup=_kb_folder_menu(scan, tok),
        )
        return

    await update.message.reply_text("Format link tidak dikenali.")


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
    status_msg,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):
    """Update pesan status; jika gagal edit, kirim pesan baru."""
    try:
        if status_msg:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            return status_msg
    except Exception:
        pass
    return await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


async def _send_direct_link_only(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    caption: str,
    direct_url: str,
    reason: str,
):
    await context.bot.send_message(
        chat_id,
        text=(
            f"{caption}\n\n"
            f"ℹ️ {reason}\n"
            f"Link unduhan:\n<code>{direct_url}</code>"
        ),
        parse_mode=ParseMode.HTML,
    )


async def _send_file_or_link(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    local_path: Path | None,
    caption: str,
    fallback_url: str,
):
    max_bytes = int(config.MAX_TELEGRAM_MB * 1024 * 1024)
    if not local_path or not local_path.exists():
        await _send_direct_link_only(
            context,
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
            context,
            chat_id,
            caption.replace("✅", "⚠️"),
            fallback_url,
            f"File tidak valid untuk preview Telegram: {err}",
        )
        return

    try:
        if size <= max_bytes:
            with open(local_path, "rb") as f:
                await asyncio.wait_for(
                    context.bot.send_video(
                        chat_id=chat_id,
                        video=InputFile(f, filename=local_path.name),
                        caption=caption[:1024],
                        supports_streaming=True,
                        read_timeout=config.TELEGRAM_MEDIA_TIMEOUT,
                        write_timeout=config.TELEGRAM_MEDIA_TIMEOUT,
                    ),
                    timeout=config.TELEGRAM_MEDIA_TIMEOUT + 30,
                )
        else:
            mb = size / (1024 * 1024)
            await _send_direct_link_only(
                context,
                chat_id,
                caption,
                fallback_url,
                f"File <b>{mb:.1f} MB</b> — terlalu besar untuk dikirim lewat Telegram (maks 2 GB).",
            )
    finally:
        cleanup_path(local_path)


async def _process_one_video(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    page_url: str,
    index: int,
    total: int,
    dest: Path,
) -> tuple[bool, bool]:
    """
    Proses satu video. Return (sukses, gagal).
    Selalu mengirim info ke Telegram (sukses / gagal / link saja).
    """
    cap_prefix = f"[{index}/{total}]"
    resolved = None
    local_path = None
    try:
        resolved = await asyncio.to_thread(
            resolve_stream_url, page_url, config.REQUEST_TIMEOUT
        )
        tg_max = int(config.MAX_TELEGRAM_MB * 1024 * 1024)
        dl_max = int(config.MAX_DOWNLOAD_MB * 1024 * 1024)
        remote_size = await asyncio.to_thread(
            remote_content_length,
            resolved,
            config.DOWNLOAD_CONNECT_TIMEOUT,
        )
        title = resolved.title or page_url
        caption_ok = f"✅ {cap_prefix} {title}"

        # Pengondisian batas file besar disesuaikan ke Local Bot API (maks 2 GB)
        limit = remote_size or 0
        if limit > dl_max:
            mb = limit / (1024 * 1024)
            await _send_direct_link_only(
                context,
                chat_id,
                caption_ok,
                resolved.direct_url,
                (
                    f"Video <b>{mb:.1f} MB</b> — terlalu besar untuk diunduh & dikirim bot "
                    f"(maks upload bot ≈ 2 GB). "
                    "Salin link di bawah ke IDM / browser."
                ),
            )
            return True, False

        local_path = await asyncio.to_thread(
            download_to_path,
            resolved,
            dest,
            config.DOWNLOAD_CONNECT_TIMEOUT,
            config.DOWNLOAD_READ_TIMEOUT,
        )
        await _send_file_or_link(
            context, chat_id, local_path, caption_ok, resolved.direct_url
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
        await context.bot.send_message(
            chat_id,
            text=(
                f"❌ {cap_prefix} Gagal\n"
                f"<code>{page_url}</code>\n\n"
                f"{_format_error(e)}{hint}"
            ),
            parse_mode=ParseMode.HTML,
        )
        return False, True


async def _job_download_videos(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_urls: list[str],
    label: str,
):
    urls = video_urls[: config.MAX_VIDEOS_PER_JOB]
    total = len(urls)
    if not urls:
        await context.bot.send_message(chat_id, "Tidak ada video untuk diunduh.")
        return

    status = await context.bot.send_message(
        chat_id,
        f"⏳ Memulai unduh <b>{total}</b> video — {label}\n"
        "<i>File disimpan sementara lalu dihapus otomatis.</i>",
        parse_mode=ParseMode.HTML,
    )
    ok, fail = 0, 0

    with tempfile.TemporaryDirectory(prefix="vidoy_dl_") as tmp:
        dest = Path(tmp)
        for i, page_url in enumerate(urls, 1):
            status = await _notify_status(
                status,
                chat_id,
                context,
                f"⏳ [{i}/{total}] Mengambil link & mengunduh…\n<code>{page_url}</code>",
            )
            success, failed = await _process_one_video(
                context, chat_id, page_url, i, total, dest
            )
            if success:
                ok += 1
            if failed:
                fail += 1
            if i < total:
                await asyncio.sleep(config.DELAY_BETWEEN_VIDEOS_SEC)

    await _notify_status(
        status,
        chat_id,
        context,
        f"🏁 <b>Selesai</b> — {label}\n"
        f"Berhasil: <b>{ok}</b> | Gagal: <b>{fail}</b> | Total: <b>{total}</b>",
    )


async def _job_download_videos_safe(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_urls: list[str],
    label: str,
):
    """Wrapper: selalu beri tahu Telegram jika job crash di tengah jalan."""
    try:
        await _job_download_videos(context, chat_id, video_urls, label)
    except Exception as e:
        logger.exception("Job unduh crash: %s", label)
        await context.bot.send_message(
            chat_id,
            text=(
                f"❌ <b>Unduhan terhenti mendadak</b> — {label}\n\n"
                f"{_format_error(e)}\n\n"
                "Coba lagi dengan lebih sedikit video, atau periksa koneksi internet."
            ),
            parse_mode=ParseMode.HTML,
        )
    finally:
        context.user_data.pop("download_busy", None)


def _spawn_download_job(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_urls: list[str],
    label: str,
) -> bool:
    if context.user_data.get("download_busy"):
        return False
    context.user_data["download_busy"] = True
    asyncio.create_task(
        _job_download_videos_safe(context, chat_id, video_urls, label)
    )
    return True


async def callback_vdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    await q.answer()
    if not _allowed(q.from_user and q.from_user.id):
        await q.answer("Akses ditolak.", show_alert=True)
        return

    parts = q.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    token = parts[2]

    if action == "noop":
        await q.answer("Terlalu banyak subfolder. Buka link subfolder secara terpisah.", show_alert=True)
        return

    offer = context.user_data.get(f"offer_{token}")
    if not offer:
        await q.answer("Menu kedaluwarsa. Kirim link lagi.", show_alert=True)
        return

    chat_id = q.message.chat_id

    if action == "x":
        context.user_data.pop(f"offer_{token}", None)
        await q.edit_message_text("Dibatalkan.")
        return

    if action == "go" and offer.get("type") == "video":
        url = offer.get("url")
        context.user_data.pop(f"offer_{token}", None)
        await q.edit_message_text("⏳ Mengunduh 1 video…")
        if not _spawn_download_job(context, chat_id, [url], "satu video"):
            await context.bot.send_message(
                chat_id,
                "⚠️ Masih ada unduhan berjalan. Tunggu sampai selesai dulu.",
            )
        return

    if action == "fa" and offer.get("type") == "folder":
        scan = offer.get("scan") or {}
        videos = scan.get("videos") or []
        context.user_data.pop(f"offer_{token}", None)
        name = scan.get("name", "Folder")
        await q.edit_message_text(f"⏳ Mengunduh semua video di <b>{name}</b>…", parse_mode=ParseMode.HTML)
        if not _spawn_download_job(context, chat_id, videos, name):
            await context.bot.send_message(
                chat_id,
                "⚠️ Masih ada unduhan berjalan. Tunggu sampai selesai dulu.",
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
            await q.answer("Subfolder tidak valid.", show_alert=True)
            return
        sub_url, sub_name = subs[idx]
        try:
            new_scan = await asyncio.to_thread(_scan_folder, sub_url)
        except Exception as e:
            await q.answer(f"Gagal buka subfolder: {e}", show_alert=True)
            return
        new_tok = secrets.token_hex(4)
        stack = list(offer.get("stack") or [])
        stack.append({"name": scan.get("name"), "url": scan.get("url")})
        context.user_data.pop(f"offer_{token}", None)
        context.user_data[f"offer_{new_tok}"] = {
            "type": "folder",
            "scan": new_scan,
            "stack": stack,
        }
        trail = " → ".join(s["name"] for s in stack) + f" → {sub_name}"
        n_vid = len(new_scan["videos"])
        n_sub = len(new_scan["subfolders"])
        await q.edit_message_text(
            f"📂 <b>{new_scan['name']}</b>\n"
            f"<i>{trail}</i>\n\n"
            f"Video: <b>{n_vid}</b> | Subfolder: <b>{n_sub}</b>",
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
    # Bersihkan sisa folder downloads/ lama (sebelum pakai temp per job)
    if config.DOWNLOAD_DIR.exists():
        cleanup_dir(config.DOWNLOAD_DIR)
    start_health_server(config.PORT)
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(config.TELEGRAM_MEDIA_TIMEOUT)
        .media_write_timeout(config.TELEGRAM_MEDIA_TIMEOUT)
        .get_updates_connect_timeout(100.0)
        .get_updates_read_timeout(100.0)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(callback_vdl, pattern=r"^vdl:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print(f"Vidoy Downloader Bot jalan (port health {config.PORT})…")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=5,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
