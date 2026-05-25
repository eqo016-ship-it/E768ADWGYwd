# Deploy Bot Vidoy di Koyeb

Bot **bisa dijalankan di Koyeb** lewat Docker. Pyrogram jalan di satu container Python.

## Mode

| Mode | Env | Upload maks |
|------|-----|-------------|
| **Bot** | `TELEGRAM_BOT_TOKEN` | ~50 MB |
| **Userbot** | `SESSION_STRING` (tanpa token) | ~2 GB |

Free tier Koyeb (512 MB RAM): pakai bot + `MAX_TELEGRAM_MB=48`, atau userbot + `MAX_TELEGRAM_MB=400`.

---

## Langkah deploy

1. Push repo GitHub (tanpa `.env` / `*.session` — lihat README).
2. Koyeb → **Create App** → GitHub → pilih repo.
3. **Builder:** Dockerfile (root folder bot).
4. **Port:** `8000`
5. **Health check path:** `/health`
6. **Environment variables** (di dashboard Koyeb):

| Variable | Contoh |
|----------|--------|
| `TELEGRAM_API_ID` | angka dari my.telegram.org |
| `TELEGRAM_API_HASH` | string dari my.telegram.org |
| `TELEGRAM_BOT_TOKEN` | dari @BotFather |
| `PORT` | `8000` |
| `MAX_TELEGRAM_MB` | `48` |
| `MAX_DOWNLOAD_MB` | `48` |
| `DOWNLOAD_DIR` | `downloads` |

Opsional: `ADMIN_IDS`, `SESSION_STRING`, `VIDOY_EXTRACT_DOMAIN`, `MAX_VIDEOS_PER_JOB`.

7. Deploy → buka log, pastikan ada `Health server on 0.0.0.0:8000` dan bot online.

---

## Cek health

`https://NAMA-APP-USER.koyeb.app/health` → harus `OK`

---

## Catatan Koyeb free

- Instance bisa **sleep** jika idle — kirim `/start` ke bot atau ping `/health` berkala.
- Disk ephemeral: folder `downloads/` hilang saat restart (normal).
- Untuk file >50 MB butuh **userbot** (`SESSION_STRING`), bukan bot token saja.

---

## Docker lokal (opsional)

```bash
cp .env.example .env
# isi .env
docker compose up --build
```
