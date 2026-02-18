FROM python:3.11.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

# Install required packages (pinned for reproducibility)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy gateway application
COPY main.py /app/
COPY models.py /app/
COPY config.py /app/

RUN adduser --disabled-password --gecos '' --uid 10001 app && \
    mkdir -p /app/logs && \
    chown -R app:app /app/logs

ENV SANDBOX_GATEWAY_PORT=8000

EXPOSE ${SANDBOX_GATEWAY_PORT}

USER app

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SANDBOX_GATEWAY_PORT} --log-level debug"]
