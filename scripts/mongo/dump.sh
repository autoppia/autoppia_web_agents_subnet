#!/bin/bash
# dump_mongo.sh - Dump current MongoDB state from a running instance to a local folder.
#
# This script:
#   1. Checks that mongodump is installed.
#   2. Extracts MongoDB connection details from .env file.
#   3. Dumps MongoDB data with authentication into ./mongo-dump.
#
# Usage:
#   ./dump_mongo.sh
set -euo pipefail

# Find the .env file in the project root
ENV_FILE="$(pwd)/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "[ERROR] .env file not found at $ENV_FILE. Aborting." >&2
  exit 1
fi

# Extract MongoDB connection details from .env file
MONGODB_URL=$(grep -E "^MONGODB_URL=" "$ENV_FILE" | cut -d'"' -f2 || true)
if [ -z "$MONGODB_URL" ]; then
  echo "[ERROR] MONGODB_URL not found in .env file. Aborting." >&2
  exit 1
fi

# Parse the MongoDB URL to extract connection details
HOST=$(echo "$MONGODB_URL" | grep -oP '(?<=mongodb://)[^:@]+:[^@]+@\K[^:]+' || echo "localhost")
PORT=$(echo "$MONGODB_URL" | grep -oP '(?<=mongodb://)[^:@]+:[^@]+@[^:]+:\K\d+' || echo "27017")
USERNAME=$(echo "$MONGODB_URL" | grep -oP '(?<=mongodb://)\K[^:@]+' || echo "")
PASSWORD=$(echo "$MONGODB_URL" | grep -oP '(?<=mongodb://)[^:@]+:\K[^@]+' || echo "")
AUTH_DB=$(echo "$MONGODB_URL" | grep -oP '(?<=authSource=)\w+' || echo "admin")

OUTPUT_DIR="$(pwd)/data/mongo-dump"

if ! command -v mongodump >/dev/null 2>&1; then
  echo "[ERROR] mongodump is not installed. Aborting." >&2
  exit 1
fi

echo "[INFO] Dumping MongoDB data from ${HOST}:${PORT} to ${OUTPUT_DIR}..."
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

mongodump --host "$HOST" --port "$PORT" --username "$USERNAME" --password "$PASSWORD" --authenticationDatabase "$AUTH_DB" --out "$OUTPUT_DIR"

echo "[INFO] Dump complete. Data dumped to ${OUTPUT_DIR}"