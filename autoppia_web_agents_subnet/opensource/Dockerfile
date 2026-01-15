FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Create an unprivileged user to run miner code.
RUN groupadd --system sandbox && \
    useradd --system --create-home --gid sandbox sandbox

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Lightweight defaults to run common Python web agents + IWA LLM helpers.
# This is built once by the validator operator; miner repos do not install
# additional dependencies at runtime.
RUN pip install --no-cache-dir fastapi uvicorn httpx "autoppia_iwa @ git+https://github.com/autoppia/autoppia_iwa.git"

WORKDIR /sandbox

RUN chown -R sandbox:sandbox /sandbox
USER sandbox

# Default command is provided by the host when the container is created.
