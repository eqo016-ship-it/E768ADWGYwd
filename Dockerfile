FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py download_worker.py stream_resolver.py progress_ui.py \
    health_server.py vidoy_extract.py vidoy_client.py ./

ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-u", "bot.py"]
