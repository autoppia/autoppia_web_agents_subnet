#!/bin/bash
# dump_mongo.sh - Dump current MongoDB state from a running instance to a local folder.
#
# This script:
#   1. Checks that mongodump is installed.
#   2. Dumps MongoDB data from localhost:27017 into ./mongo-dump.
#
# Usage:
#   ./dump_mongo.sh

set -euo pipefail

HOST="localhost"
PORT="27017"
OUTPUT_DIR="$(pwd)/data/mongo-dump"

if ! command -v mongodump >/dev/null 2>&1; then
  echo "[ERROR] mongodump is not installed. Aborting." >&2
  exit 1
fi

echo "[INFO] Dumping MongoDB data from ${HOST}:${PORT} to ${OUTPUT_DIR}..."
rm -rf "$OUTPUT_DIR"
mongodump --host "$HOST" --port "$PORT" --out "$OUTPUT_DIR"
echo "[INFO] Dump complete. Data dumped to ${OUTPUT_DIR}"
