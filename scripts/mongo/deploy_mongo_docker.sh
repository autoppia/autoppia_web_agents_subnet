#!/bin/bash
# deploy_mongo_docker.sh - Deploy MongoDB via Docker with security measures
#
# This script:
#   1. Stops and removes existing MongoDB container if present
#   2. Creates a secure MongoDB with authentication that only binds to localhost
#   3. Restores from dump if available
#   4. Saves connection credentials to a file for reference

set -euo pipefail

# Configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"
HOST_PORT=27017
CONTAINER_PORT=27017
MONGO_VOLUME="$HOME/mongodb_data"
MONGO_INIT_FOLDER="$(pwd)/mongo-init"
DUMP_FOLDER="$(pwd)/data/mongo-dump"
MONGO_USER="adminUser"
MONGO_PASSWORD="$(openssl rand -base64 12)"  # Generate random password
CREDENTIALS_FILE="mongodb_credentials.txt"

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

check_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    handle_error "Required command '$1' is not installed."
  fi
}

# Check for required commands
check_command docker
check_command openssl

# Create directories if they don't exist
mkdir -p "$MONGO_VOLUME"
mkdir -p "$MONGO_INIT_FOLDER"
mkdir -p "$DUMP_FOLDER"

# Create MongoDB init script to set up authentication
cat > "$MONGO_INIT_FOLDER/mongo-init.js" << EOF
db = db.getSiblingDB('admin');
db.createUser({
  user: '$MONGO_USER',
  pwd: '$MONGO_PASSWORD',
  roles: [{ role: 'root', db: 'admin' }]
});
EOF

echo "[INFO] Created MongoDB initialization script with authentication"

# Stop and remove existing container if it exists
if docker ps -a | grep -q $CONTAINER_NAME; then
  echo "[INFO] Stopping and removing existing MongoDB container..."
  docker stop $CONTAINER_NAME || true
  docker rm $CONTAINER_NAME || true
fi

# Prepare dump volume mounting if dump folder has files
if [ -d "$DUMP_FOLDER" ] && [ "$(ls -A "$DUMP_FOLDER" 2>/dev/null)" ]; then
  echo "[INFO] Dump folder detected with content. It will be mounted to /dump in the container."
  DUMP_VOLUME="-v ${DUMP_FOLDER}:/dump"
else
  echo "[INFO] No dump content found in $DUMP_FOLDER. Skipping dump mount."
  DUMP_VOLUME=""
fi

# Run MongoDB container with security measures
echo "[INFO] Starting MongoDB container with authentication and localhost binding..."
docker run --name $CONTAINER_NAME -d \
  -p 127.0.0.1:$HOST_PORT:$CONTAINER_PORT \
  -v "$MONGO_VOLUME:/data/db" \
  -v "$MONGO_INIT_FOLDER:/docker-entrypoint-initdb.d" \
  $DUMP_VOLUME \
  mongo:$MONGO_VERSION --auth

# Save connection details to a file
CONNECTION_STRING="mongodb://$MONGO_USER:$MONGO_PASSWORD@localhost:$HOST_PORT/admin?authSource=admin"
echo "MongoDB connection string: $CONNECTION_STRING" > $CREDENTIALS_FILE
echo "User: $MONGO_USER" >> $CREDENTIALS_FILE
echo "Password: $MONGO_PASSWORD" >> $CREDENTIALS_FILE
chmod 600 $CREDENTIALS_FILE  # Restrict file permissions for security

# Wait for MongoDB to initialize completely (important for auth to be set up)
echo "[INFO] Waiting for MongoDB to initialize completely (30 seconds)..."
sleep 30

# Check if MongoDB is ready with authentication
echo "[INFO] Verifying MongoDB connection..."
MAX_RETRY=5
RETRY_COUNT=0
CONNECTION_SUCCESS=false

while [ $RETRY_COUNT -lt $MAX_RETRY ] && [ "$CONNECTION_SUCCESS" = false ]; do
  if docker exec $CONTAINER_NAME mongosh --quiet --eval "db.adminCommand('ping')" -u "$MONGO_USER" -p "$MONGO_PASSWORD" --authenticationDatabase admin &>/dev/null; then
    echo "[INFO] MongoDB connection verified successfully."
    CONNECTION_SUCCESS=true
  else
    RETRY_COUNT=$((RETRY_COUNT+1))
    if [ $RETRY_COUNT -lt $MAX_RETRY ]; then
      echo "[INFO] Connection attempt $RETRY_COUNT failed. Waiting 5 seconds before retry..."
      sleep 5
    else
      echo "[WARN] Could not verify MongoDB connection after $MAX_RETRY attempts."
    fi
  fi
done

# Restore dump if available and connection is successful
if [ -n "$DUMP_VOLUME" ] && [ "$CONNECTION_SUCCESS" = true ]; then
  echo "[INFO] Attempting to restore MongoDB dump with admin credentials..."
  if docker exec $CONTAINER_NAME mongorestore --drop -u "$MONGO_USER" -p "$MONGO_PASSWORD" --authenticationDatabase admin /dump; then
    echo "[INFO] MongoDB dump restored successfully."
  else
    echo "[WARN] Failed to restore MongoDB dump. You may need to restore manually using:"
    echo "docker exec -it $CONTAINER_NAME mongorestore --drop -u \"$MONGO_USER\" -p \"$MONGO_PASSWORD\" --authenticationDatabase admin /dump"
  fi
elif [ -n "$DUMP_VOLUME" ]; then
  echo "[WARN] Skipping dump restoration due to connection issues. You can restore manually using:"
  echo "docker exec -it $CONTAINER_NAME mongorestore --drop -u \"$MONGO_USER\" -p \"$MONGO_PASSWORD\" --authenticationDatabase admin /dump"
fi

echo "[INFO] MongoDB deployed successfully!"
echo "[INFO] Connection credentials saved to $CREDENTIALS_FILE"

# Display instructions for .env file
echo ""
echo "================================================================"
echo "IMPORTANT: Update your .env file with the following line:"
echo "MONGODB_URL=\"$CONNECTION_STRING\""
echo "================================================================"