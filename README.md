# Bot Telegram — Unduh Video Vidoy (Pyrogram)

Bot mengunduh video dari link share Vidoy, simpan sementara di folder `downloads/`, lalu kirim ke chat Telegram.

**Stack:** Pyrogram + requests

## Fitur

| Link | Perilaku |
|------|----------|
| `/d/ID`, `/e/ID` | Unduh 1 video |
| `/f/ID` | Unduh semua video di folder + navigasi subfolder |

Progress di chat: `proses download 1/30` + bar `⏱️━━━━● 88%`

## Setup lokal

1. https://my.telegram.org/apps → `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
2. @BotFather → `TELEGRAM_BOT_TOKEN`
3. `pip install -r requirements.txt`
4. Salin `.env.example` → `.env` (isi token/API)
5. `python bot.py`

## Upload file besar

- **Bot token:** ~50 MB
- **Userbot:** isi `SESSION_STRING` di `.env` → hingga ~2 GB

## Deploy Koyeb

**Ya, bot ini bisa jalan di Koyeb** (Docker + health check).

Panduan lengkap: [`DEPLOY_KOYEB.md`](DEPLOY_KOYEB.md)

Ringkas:

| Setting Koyeb | Nilai |
|---------------|--------|
| Builder | Dockerfile |
| Port | `8000` |
| Health check | `/health` |
| Env | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`, `PORT=8000` |

## Push ke GitHub (aman)

**Jangan commit:**

- `.env` (token & rahasia)
- `*.session` (login Pyrogram)
- folder `downloads/` (file video lokal)

File di atas sudah ada di `.gitignore`.

```bash
git init
git add .
git status   # pastikan .env & *.session TIDAK muncul
git commit -m "Vidoy downloader bot"
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

## Struktur repo

```
bot.py              # Handler Telegram
config.py           # Env & batas ukuran
download_worker.py  # Unduh ke disk
stream_resolver.py  # Ambil link CDN dari halaman Vidoy
progress_ui.py      # Bar progress di chat
vidoy_extract.py    # Parser folder
vidoy_client.py     # API Vidoy (folder/link)
health_server.py    # GET /health (Koyeb)
Dockerfile
requirements.txt
.env.example
```
