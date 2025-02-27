#!/bin/bash
# deploy_mongo.sh - Deploy MongoDB via Docker with custom configuration, initial DB scripts,
# and optional dump restoration.
#
# This script:
#   1. Kills any local process using the specified host port.
#   2. Stops and removes an existing Docker container with the specified name.
#   3. Prompts to delete existing MongoDB data if detected.
#   4. Starts a new MongoDB container using Docker with custom port mapping, persistent volume,
#      and mounts for initialization scripts and a dump (if available).
#   5. Restores the MongoDB dump (if present) after container startup.
#   6. Verifies the container status and checks the MongoDB connection.
#
# Usage:
#   ./deploy_mongo.sh [-y]
#   -y: Skip all interactive prompts and assume "yes" for all questions
set -euo pipefail

# Parse command line arguments
YES_FLAG=false
while getopts "y" opt; do
  case ${opt} in
    y )
      YES_FLAG=true
      ;;
    \? )
      echo "Usage: ./deploy_mongo.sh [-y]"
      exit 1
      ;;
  esac
done

# Custom configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"         # Change this if you want a specific MongoDB version (e.g., 6.0, 5.0, etc.)
HOST_PORT=27017                # Host port to map
CONTAINER_PORT=27017           # Container port (default MongoDB port)
MONGO_VOLUME="$HOME/mongodb_data"
MONGO_INIT_FOLDER="$(pwd)/mongo-init"  # Folder containing initialization scripts
DUMP_FOLDER="$(pwd)/data/mongo-dump"     # Folder containing a MongoDB dump

# MongoDB security configuration
MONGO_USERNAME="admin"
MONGO_PASSWORD="$(openssl rand -base64 24)"  # Generate a secure random password
MONGO_AUTH_DB="admin"

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

prompt_and_clean_data() {
  if [ -d "$MONGO_VOLUME" ] && [ "$(ls -A "$MONGO_VOLUME" 2>/dev/null)" ]; then
    echo "[INFO] Existing MongoDB data detected in $MONGO_VOLUME."
    
    if [ "$YES_FLAG" = true ]; then
      echo "[INFO] Auto-confirming due to -y flag. Deleting existing MongoDB data..."
      rm -rf "$MONGO_VOLUME" || handle_error "Failed to delete MongoDB data"
      mkdir -p "$MONGO_VOLUME"
    else
      read -p "Do you want to delete the current MongoDB data and start fresh? (y/N): " answer
      case "$answer" in
        [yY][eE][sS]|[yY])
          echo "[INFO] Deleting existing MongoDB data..."
          rm -rf "$MONGO_VOLUME" || handle_error "Failed to delete MongoDB data"
          mkdir -p "$MONGO_VOLUME"
          ;;
        *)
          echo "[INFO] Keeping existing MongoDB data."
          ;;
      esac
    fi
  else
    mkdir -p "$MONGO_VOLUME"
  fi
}

create_mongo_init_script() {
  # Create a MongoDB initialization script to set up authentication
  mkdir -p "$MONGO_INIT_FOLDER"
  cat > "$MONGO_INIT_FOLDER/init-mongo.js" << EOF
db = db.getSiblingDB('admin');
db.createUser({
  user: '${MONGO_USERNAME}',
  pwd: '${MONGO_PASSWORD}',
  roles: [{ role: 'root', db: 'admin' }]
});
EOF
  echo "[INFO] Created MongoDB initialization script with authentication setup."
  echo "[INFO] MongoDB username: ${MONGO_USERNAME}"
  echo "[INFO] MongoDB password: ${MONGO_PASSWORD}"
  echo "[INFO] Please save these credentials securely!"
}

start_mongo() {
  echo "[INFO] Starting a new MongoDB container using image 'mongo:${MONGO_VERSION}'..."
  prompt_and_clean_data
  create_mongo_init_script
  
  # Mount dump folder if it exists
  if [ -d "$DUMP_FOLDER" ]; then
    DUMP_VOLUME="-v ${DUMP_FOLDER}:/dump"
    echo "[INFO] Dump folder detected. It will be mounted to /dump in the container."
  else
    DUMP_VOLUME=""
  fi
  
  # Check if dump folder permissions are correct
  if [ -d "$DUMP_FOLDER" ]; then
    echo "[INFO] Setting appropriate permissions on dump folder..."
    chmod -R 755 "$DUMP_FOLDER" || echo "[WARNING] Could not change permissions on dump folder"
  fi
  
  # Make sure the data volume has correct permissions
  mkdir -p "$MONGO_VOLUME"
  chmod -R 777 "$MONGO_VOLUME" || echo "[WARNING] Could not change permissions on data volume"
  
  # Use 127.0.0.1 explicitly to bind only to localhost
  docker run --name "${CONTAINER_NAME}" -d \
    -p "127.0.0.1:$HOST_PORT:$CONTAINER_PORT" \
    -v "$MONGO_VOLUME":/data/db \
    -v "$MONGO_INIT_FOLDER":/docker-entrypoint-initdb.d \
    $DUMP_VOLUME \
    --env MONGO_INITDB_ROOT_USERNAME="${MONGO_USERNAME}" \
    --env MONGO_INITDB_ROOT_PASSWORD="${MONGO_PASSWORD}" \
    --restart unless-stopped \
    mongo:"${MONGO_VERSION}" \
    --bind_ip 127.0.0.1 \
    --auth || handle_error "Failed to deploy MongoDB container"
    
  # Give MongoDB a moment to start before proceeding
  sleep 5
  
  # Check if container is running
  if ! docker ps | grep -q "${CONTAINER_NAME}"; then
    echo "[ERROR] MongoDB container failed to start. Container logs:"
    docker logs "${CONTAINER_NAME}"
    handle_error "MongoDB container failed to start properly"
  fi
}

verify_mongo() {
  echo "[INFO] Verifying MongoDB container status..."
  docker ps -f name=^/${CONTAINER_NAME}$ || handle_error "MongoDB container is not running."
  
  # Check container logs for any obvious errors
  docker logs "${CONTAINER_NAME}" | grep -i "error\|warn" || true
  
  echo "[INFO] MongoDB should be accessible at mongodb://${MONGO_USERNAME}:${MONGO_PASSWORD}@localhost:$HOST_PORT"
}

wait_for_container_ready() {
  local max_attempts=30
  local attempt=1
  
  echo "[INFO] Waiting for MongoDB container to be fully ready..."
  while [ $attempt -le $max_attempts ]; do
    if docker ps | grep -q "${CONTAINER_NAME}"; then
      # Container is running, check if it's ready to accept connections
      if docker exec "${CONTAINER_NAME}" mongosh --quiet --eval "db.adminCommand('ping')" 2>/dev/null; then
        echo "[INFO] MongoDB container is ready."
        return 0
      fi
    else
      echo "[WARNING] MongoDB container is not running. Checking logs..."
      docker logs "${CONTAINER_NAME}"
      handle_error "MongoDB container failed to start or stopped running."
    fi
    
    echo "[INFO] Waiting for MongoDB to initialize (attempt $attempt/$max_attempts)..."
    sleep 5
    ((attempt++))
  done
  
  echo "[WARNING] MongoDB container logs:"
  docker logs "${CONTAINER_NAME}"
  handle_error "MongoDB container did not become ready within the timeout period."
}

restore_dump() {
  if [ -d "$DUMP_FOLDER" ]; then
    wait_for_container_ready
    
    echo "[INFO] Restoring MongoDB dump from /dump with --drop flag..."
    docker exec "${CONTAINER_NAME}" mongorestore --authenticationDatabase admin \
      -u "${MONGO_USERNAME}" -p "${MONGO_PASSWORD}" --drop /dump || handle_error "Failed to restore MongoDB dump"
  else
    echo "[INFO] No dump folder found. Skipping dump restore."
  fi
}

check_mongo_connection() {
  echo "[INFO] Checking MongoDB connection by listing databases..."
  sleep 3
  docker exec "${CONTAINER_NAME}" mongosh --authenticationDatabase admin \
    -u "${MONGO_USERNAME}" -p "${MONGO_PASSWORD}" \
    --eval "db.adminCommand('listDatabases')" || handle_error "Failed to list databases. MongoDB connection issue."
}

generate_connection_string() {
  echo "[INFO] Your secure MongoDB connection string is:"
  echo "mongodb://${MONGO_USERNAME}:${MONGO_PASSWORD}@localhost:${HOST_PORT}/${MONGO_AUTH_DB}?authSource=admin"
  echo "[INFO] Update your application configuration to use this connection string."
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
  generate_connection_string
  echo "[INFO] MongoDB is running securely and connection is verified."
}

main "$@"