FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SANDBOX_AGENT_PORT=8000

EXPOSE ${SANDBOX_AGENT_PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SANDBOX_AGENT_PORT} --log-level debug"]