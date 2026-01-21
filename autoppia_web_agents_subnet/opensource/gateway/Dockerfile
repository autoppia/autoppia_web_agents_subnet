FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install required packages
RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

WORKDIR /app

# Copy gateway application
COPY main.py /app/
COPY models.py /app/
COPY config.py /app/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]