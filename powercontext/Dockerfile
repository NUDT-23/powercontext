FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    POWERCONTEXT_HOME=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "powercontext[cli,server]==1.5.0"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1

CMD ["powercontext", "server", "run"]
