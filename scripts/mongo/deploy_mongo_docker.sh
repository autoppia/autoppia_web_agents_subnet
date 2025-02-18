#!/bin/bash
# deploy_mongo.sh - Deploy MongoDB via Docker with custom configuration, initial DB scripts,
# and optional dump restoration.
#
# This script:
#   1. Kills any local process using the specified host port.
#   2. Stops and removes an existing Docker container with the specified name.
#   3. Starts a new MongoDB container using Docker with custom port mapping, persistent volume,
#      and mounts for initialization scripts and a dump (if available).
#   4. Restores the MongoDB dump (if present) after container startup.
#   5. Verifies the container status and checks the MongoDB connection.
#
# Usage:
#   ./deploy_mongo.sh

set -euo pipefail

# Custom configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"         # Change this if you want a specific MongoDB version (e.g., 6.0, 5.0, etc.)
HOST_PORT=27017                # Host port to map
CONTAINER_PORT=27017           # Container port (default MongoDB port)
MONGO_VOLUME="$HOME/mongodb_data"
MONGO_INIT_FOLDER="$(pwd)/mongo-init"  # Folder containing initialization scripts
DUMP_FOLDER="$(pwd)/data/mongo-dump"         # Folder containing a MongoDB dump

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

check_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    handle_error "Required command '$1' is not installed."
  fi
}

check_docker_installed() {
  check_command docker
  echo "[INFO] Docker is installed."
}

kill_local_mongo_process() {
  echo "[INFO] Checking for local processes using port $HOST_PORT..."
  local pids
  pids=$(lsof -t -i:"$HOST_PORT" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "[INFO] Found process(es) on port $HOST_PORT: $pids"
    echo "[INFO] Killing process(es): $pids"
    sudo kill -9 $pids || handle_error "Failed to kill local process(es) using port $HOST_PORT"
  else
    echo "[INFO] No local process using port $HOST_PORT found."
  fi
}

close_existing_container() {
  if [ "$(docker ps -a -f name=^/${CONTAINER_NAME}$ --format '{{.Names}}')" == "${CONTAINER_NAME}" ]; then
    echo "[INFO] Existing container '${CONTAINER_NAME}' found. Stopping and removing..."
    docker stop "${CONTAINER_NAME}" || handle_error "Failed to stop existing MongoDB container"
    docker rm "${CONTAINER_NAME}" || handle_error "Failed to remove existing MongoDB container"
  else
    echo "[INFO] No existing container named '${CONTAINER_NAME}' found."
  fi
}

start_mongo() {
  echo "[INFO] Starting a new MongoDB container using image 'mongo:${MONGO_VERSION}'..."
  mkdir -p "$MONGO_VOLUME"
  mkdir -p "$MONGO_INIT_FOLDER"
  
  # Mount dump folder if it exists
  if [ -d "$DUMP_FOLDER" ]; then
    DUMP_VOLUME="-v ${DUMP_FOLDER}:/dump"
    echo "[INFO] Dump folder detected. It will be mounted to /dump in the container."
  else
    DUMP_VOLUME=""
  fi

  docker run --name "${CONTAINER_NAME}" -d -p "$HOST_PORT":"$CONTAINER_PORT" \
    -v "$MONGO_VOLUME":/data/db \
    -v "$MONGO_INIT_FOLDER":/docker-entrypoint-initdb.d \
    $DUMP_VOLUME \
    mongo:"${MONGO_VERSION}" || handle_error "Failed to deploy MongoDB container"
}

verify_mongo() {
  echo "[INFO] Verifying MongoDB container status..."
  docker ps -f name=^/${CONTAINER_NAME}$ || handle_error "MongoDB container is not running."
  echo "[INFO] MongoDB should be accessible at mongodb://localhost:$HOST_PORT"
}

restore_dump() {
  if [ -d "$DUMP_FOLDER" ]; then
    echo "[INFO] Restoring MongoDB dump from /dump with --drop flag..."
    docker exec "${CONTAINER_NAME}" mongorestore --drop /dump || handle_error "Failed to restore MongoDB dump"
  else
    echo "[INFO] No dump folder found. Skipping dump restore."
  fi
}

check_mongo_connection() {
  echo "[INFO] Checking MongoDB connection by listing databases..."
  sleep 3
  docker exec "${CONTAINER_NAME}" mongosh --eval "db.adminCommand('listDatabases')" || handle_error "Failed to list databases. MongoDB connection issue."
}

main() {
  check_command lsof
  check_docker_installed

  kill_local_mongo_process
  close_existing_container
  start_mongo
  verify_mongo
  restore_dump
  check_mongo_connection

  echo "[INFO] MongoDB is running and connection is verified."
}

main "$@"
