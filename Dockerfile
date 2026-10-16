FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INTERNAL_API_HOST=0.0.0.0 \
    INTERNAL_API_PORT=9000 \
    SHAMELESS_DB_PATH=/data/shameless.sqlite3 \
    VOTES_DB_PATH=/data/votes.sqlite3

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /data \
    && chown -R bot:bot /data /app
USER bot

VOLUME ["/data"]
EXPOSE 9000

CMD ["python", "main.py"]
