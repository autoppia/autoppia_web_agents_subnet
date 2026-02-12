FROM python:3.11.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as non-root; the miner repo is bind-mounted at runtime.
RUN adduser --disabled-password --gecos '' --uid 10001 app && \
    mkdir -p /app/logs && \
    chown -R app:app /app/logs

ENV SANDBOX_AGENT_PORT=8000

EXPOSE ${SANDBOX_AGENT_PORT}

USER app

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SANDBOX_AGENT_PORT} --log-level debug"]
