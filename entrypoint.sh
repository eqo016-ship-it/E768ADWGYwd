#!/bin/sh
set -e

API_ID="${TELEGRAM_API_ID:-${API_ID}}"
API_HASH="${TELEGRAM_API_HASH:-${API_HASH}}"
LOCAL_PORT="${LOCAL_BOT_API_HTTP_PORT:-8081}"
USE_LOCAL="${USE_LOCAL_BOT_API:-true}"

mkdir -p /var/lib/telegram-bot-api

start_local_api() {
  if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
    echo "ERROR: TELEGRAM_API_ID dan TELEGRAM_API_HASH wajib untuk Local Bot API Server."
    exit 1
  fi

  echo "Memulai Local Bot API Server (port ${LOCAL_PORT}, mode --local)..."
  telegram-bot-api \
    --api-id="$API_ID" \
    --api-hash="$API_HASH" \
    --local \
    --http-port="$LOCAL_PORT" \
    --dir=/var/lib/telegram-bot-api \
    &
  TGB_PID=$!

  echo "Menunggu Local Bot API siap..."
  i=0
  while [ "$i" -lt 90 ]; do
    if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
      if curl -sf -m 5 -X POST \
        "http://127.0.0.1:${LOCAL_PORT}/bot${TELEGRAM_BOT_TOKEN}/getMe" \
        -H "Content-Type: application/json" \
        -d '{}' >/dev/null 2>&1; then
        echo "Local Bot API siap (getMe OK)."
        return 0
      fi
    else
      if curl -sf -m 2 "http://127.0.0.1:${LOCAL_PORT}/" >/dev/null 2>&1; then
        echo "Local Bot API merespons."
        return 0
      fi
    fi
    if ! kill -0 "$TGB_PID" 2>/dev/null; then
      echo "ERROR: proses telegram-bot-api berhenti mendadak."
      exit 1
    fi
    i=$((i + 1))
    sleep 1
  done

  echo "ERROR: Local Bot API tidak siap dalam 90 detik."
  kill "$TGB_PID" 2>/dev/null || true
  exit 1
}

case "$USE_LOCAL" in
  1|true|TRUE|yes|YES)
    start_local_api
    ;;
  *)
    echo "USE_LOCAL_BOT_API=$USE_LOCAL — lewati Local Bot API (mode cloud Bot API)."
    ;;
esac

exec python3 -u bot.py
