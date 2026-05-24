FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py download_worker.py stream_resolver.py health_server.py vidoy_extract.py vidoy_client.py ./

ENV PORT=8081
EXPOSE 8081

CMD ["python", "-u", "bot.py"]
