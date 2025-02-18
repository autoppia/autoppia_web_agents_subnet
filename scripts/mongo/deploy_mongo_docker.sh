#!/bin/bash
# deploy_mongo.sh - Deploy MongoDB via Docker with custom configuration
#
# This script:
#   1. Kills any local process using the specified host port.
#   2. Stops and removes an existing Docker container with the specified name.
#   3. Starts a new MongoDB container using Docker with custom port mapping and persistent volume.
#   4. Verifies the container status and checks the MongoDB connection.
#
# Usage:
#   ./deploy_mongo_docker.sh
#

set -euo pipefail

# Custom configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"         # Change this if you want a specific MongoDB version (e.g., 6.0, 5.0, etc.)
HOST_PORT=27017                # Host port to map (you can change this as needed)
CONTAINER_PORT=27017           # Container port (default MongoDB port)
MONGO_VOLUME="$HOME/mongodb_data"

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
  docker run --name "${CONTAINER_NAME}" -d -p "$HOST_PORT":"$CONTAINER_PORT" -v "$MONGO_VOLUME":/data/db mongo:"${MONGO_VERSION}" || handle_error "Failed to deploy MongoDB container"
}

verify_mongo() {
  echo "[INFO] Verifying MongoDB container status..."
  docker ps -f name=^/${CONTAINER_NAME}$ || handle_error "MongoDB container is not running."
  echo "[INFO] MongoDB should be accessible at mongodb://localhost:$HOST_PORT"
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
  check_mongo_connection

  echo "[INFO] MongoDB is running and connection is verified."
}

main "$@"
