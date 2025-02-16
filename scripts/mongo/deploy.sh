#!/bin/bash
# deploy_mongo.sh - Deploy MongoDB via Docker
# MongoDB Configuration
# MONGODB_URL="mongodb://localhost:27017"

set -e

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

kill_local_mongo_process() {
  echo "[INFO] Checking for local processes using port 27017..."
  pids=$(lsof -t -i:27017 || true)
  if [ -n "$pids" ]; then
    echo "[INFO] Found process(es) on port 27017. Killing process(es): $pids"
    sudo kill -9 $pids || handle_error "Failed to kill local process(es) using port 27017"
  else
    echo "[INFO] No local process using port 27017 found."
  fi
}

close_existing_mongo_container() {
  if [ "$(docker ps -a -f name=^/mongo$ --format '{{.Names}}')" == "mongo" ]; then
    echo "[INFO] Existing MongoDB container found. Stopping and removing..."
    docker stop mongo || handle_error "Failed to stop existing MongoDB container"
    docker rm mongo || handle_error "Failed to remove existing MongoDB container"
  else
    echo "[INFO] No existing MongoDB container found."
  fi
}

start_mongo() {
  echo "[INFO] Starting a new MongoDB container..."
  docker run --name mongo -d -p 27017:27017 mongo:latest || handle_error "Failed to deploy MongoDB container"
}

verify_mongo() {
  echo "[INFO] Verifying MongoDB container status..."
  docker ps -f name=^/mongo$
  echo "[INFO] MongoDB should be accessible at mongodb://localhost:27017"
}

check_mongo_connection() {
  echo "[INFO] Checking MongoDB connection by listing databases..."
  docker exec mongo mongosh --eval "db.adminCommand('listDatabases')" || handle_error "Failed to list databases. MongoDB connection issue."
}

main() {
  kill_local_mongo_process
  close_existing_mongo_container
  start_mongo
  verify_mongo
  check_mongo_connection
  echo "[INFO] MongoDB is running and connection is verified."
}

main "$@"
