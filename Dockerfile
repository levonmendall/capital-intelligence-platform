FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN groupadd --gid 10001 capital && \
    useradd --uid 10001 --gid capital --create-home --shell /usr/sbin/nologin capital

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install --requirement requirements.txt

COPY . .
RUN mkdir -p /app/database /app/backups /app/reports && \
    chown -R capital:capital /app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
