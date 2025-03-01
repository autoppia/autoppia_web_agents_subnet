#!/bin/bash
# dump_mongo.sh - Dump current MongoDB state from a running instance
#
# This script:
#   1. Checks that mongodump and mongosh are installed.
#   2. Extracts MongoDB connection details from the .env file.
#   3. Retrieves the list of databases to dump (excluding admin, config, local).
#   4. Dumps each normal database (with optional gzip) into ./data/mongo-dump.
#
# Usage:
#   ./dump_mongo.sh [options]
#   Options:
#     --no-pretty     Disable pretty output formatting
#     --gzip          Compress the dump using gzip
set -euo pipefail

# Parse command line arguments
PRETTY_OUTPUT=true
USE_GZIP=false
for arg in "$@"; do
  case $arg in
    --no-pretty)
      PRETTY_OUTPUT=false
      shift
      ;;
    --gzip)
      USE_GZIP=true
      shift
      ;;
  esac
done

# Color formatting (if pretty output is enabled)
if [ "$PRETTY_OUTPUT" = true ]; then
  GREEN="\033[0;32m"
  RED="\033[0;31m"
  YELLOW="\033[0;33m"
  BLUE="\033[0;34m"
  NC="\033[0m" # No Color
else
  GREEN=""
  RED=""
  YELLOW=""
  BLUE=""
  NC=""
fi

# Helper functions
info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}
warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}
error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
}
debug() {
  echo -e "${BLUE}[DEBUG]${NC} $1"
}

# Find the .env file in the project root (two levels above this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
info "Looking for .env file at: $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  error ".env file not found at $ENV_FILE. Aborting."
  exit 1
fi

# Extract MONGODB_URL from .env (remove surrounding quotes if present)
MONGODB_URL=$(grep -E "^MONGODB_URL=" "$ENV_FILE" | sed 's/^MONGODB_URL=//;s/^"//;s/"$//' || true)
if [ -z "$MONGODB_URL" ]; then
  error "Failed to extract MongoDB connection string (MONGODB_URL) from .env file"
  exit 1
else
  debug "Extracted MONGODB_URL: $MONGODB_URL"
fi

# Create output directory
OUTPUT_DIR="$PROJECT_ROOT/data/mongo-dump"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# Check that mongodump and mongosh are installed
if ! command -v mongodump >/dev/null 2>&1; then
  error "mongodump is not installed. Please install the mongodb-database-tools or similar."
  exit 1
fi
if ! command -v mongosh >/dev/null 2>&1; then
  error "mongosh is not installed. Please install the MongoDB shell."
  exit 1
fi

# Prepare mongodump options
MONGODUMP_OPTS=""
if [ "$USE_GZIP" = true ]; then
  MONGODUMP_OPTS="$MONGODUMP_OPTS --gzip"
  info "Gzip compression enabled for the dump"
fi

# Retrieve normal databases (excluding admin, config, local)
info "Retrieving list of normal databases (excluding admin, config, local)..."
DATABASES=$(mongosh "$MONGODB_URL" --quiet --eval "
  db.adminCommand('listDatabases').databases
    .filter(function(d) { return !(['admin','config','local'].includes(d.name)); })
    .map(function(d) { return d.name; })
    .join(' ');
")
if [ -z "$DATABASES" ]; then
  error "No normal databases found to dump."
  exit 1
fi
info "Databases to be dumped: $DATABASES"

# Dump each normal database - using URI without specifying --db
for DB in $DATABASES; do
  info "Dumping database: $DB"
  # Create a new connection URI for each specific database
  # This replaces any database in the connection string with the current database
  DB_URI=$(echo "$MONGODB_URL" | sed -E 's|/[^/]+\?|/'"$DB"'\?|')
  
  if ! mongodump --uri="$DB_URI" $MONGODUMP_OPTS --out "$OUTPUT_DIR"; then
    error "Dump failed for database: $DB"
    exit 1
  fi
done

info "Dump complete. Data dumped to ${OUTPUT_DIR}"

# Count collections and calculate size
NUM_COLLECTIONS=$(find "$OUTPUT_DIR" -name "*.bson" | wc -l)
DUMP_SIZE=$(du -sh "$OUTPUT_DIR" | cut -f1)
info "Successfully dumped $NUM_COLLECTIONS collections. Total size: $DUMP_SIZE"
info "To use this dump for restoration, you can either:"
info "1) Re-run deploy_mongo_docker.sh (it mounts data/mongo-dump automatically)."
info "2) Manually restore with: mongorestore --uri=\"$MONGODB_URL\" $OUTPUT_DIR"
exit 0