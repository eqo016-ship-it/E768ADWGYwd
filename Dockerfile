# Satu container: Local Bot API Server + bot Python (cocok Koyeb 1 service)
FROM aiogram/telegram-bot-api:latest AS tgapi

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tgapi /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py download_worker.py stream_resolver.py health_server.py \
    vidoy_extract.py vidoy_client.py entrypoint.sh ./

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /var/lib/telegram-bot-api

ENV PORT=8000
ENV USE_LOCAL_BOT_API=true
ENV LOCAL_BOT_API_HTTP_PORT=8081
ENV PYTHONUNBUFFERED=1

# Koyeb probe health di PORT; Local Bot API hanya di 127.0.0.1:8081
EXPOSE 8000

CMD ["/app/entrypoint.sh"]
