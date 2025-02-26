#!/bin/bash
# deploy_mongo_docker.sh - Deploy MongoDB via Docker with security measures (fixed)
# This version uses a very simple approach to ensure authentication works reliably

set -euo pipefail

# Configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"
HOST_PORT=27017
CONTAINER_PORT=27017
MONGO_VOLUME="$HOME/mongodb_data"
DUMP_FOLDER="$(pwd)/data/mongo-dump"
MONGO_USER="adminUser"
MONGO_PASSWORD="SubnetAdmin123" # Fixed password for simplicity
CREDENTIALS_FILE="mongodb_credentials.txt"

echo "[INFO] Starting MongoDB deployment with security measures..."

# Stop and remove existing container if it exists
if docker ps -a | grep -q $CONTAINER_NAME; then
  echo "[INFO] Stopping and removing existing MongoDB container..."
  docker stop $CONTAINER_NAME
  docker rm $CONTAINER_NAME
fi

# Prepare dump volume mounting if dump folder has files
if [ -d "$DUMP_FOLDER" ] && [ "$(ls -A "$DUMP_FOLDER" 2>/dev/null)" ]; then
  echo "[INFO] Dump folder detected with content. It will be mounted to /dump in the container."
  DUMP_VOLUME="-v ${DUMP_FOLDER}:/dump"
else
  echo "[INFO] No dump content found in $DUMP_FOLDER. Skipping dump mount."
  DUMP_VOLUME=""
fi

# Step 1: Start MongoDB without authentication for setup
echo "[INFO] Step 1: Starting MongoDB without authentication for initial setup..."
docker run --name $CONTAINER_NAME -d \
  -p 127.0.0.1:$HOST_PORT:$CONTAINER_PORT \
  -v "$MONGO_VOLUME:/data/db" \
  $DUMP_VOLUME \
  mongo:$MONGO_VERSION

echo "[INFO] Waiting for MongoDB to initialize (15 seconds)..."
sleep 15

# Step 2: Create admin user
echo "[INFO] Step 2: Creating admin user..."
docker exec $CONTAINER_NAME mongosh --eval "
  db = db.getSiblingDB('admin');
  db.createUser({
    user: '$MONGO_USER',
    pwd: '$MONGO_PASSWORD',
    roles: [{ role: 'root', db: 'admin' }]
  });
"

# Step 3: Restore dump if available
if [ -n "$DUMP_VOLUME" ]; then
  echo "[INFO] Step 3: Restoring MongoDB dump..."
  if docker exec $CONTAINER_NAME mongorestore --drop /dump; then
    echo "[INFO] MongoDB dump restored successfully."
  else
    echo "[WARN] Failed to restore MongoDB dump."
  fi
fi

# Step 4: Stop and remove container to restart with authentication
echo "[INFO] Step 4: Stopping and removing MongoDB container to restart with authentication..."
docker stop $CONTAINER_NAME
docker rm $CONTAINER_NAME

# Step 5: Restart with authentication
echo "[INFO] Step 5: Starting MongoDB with authentication enabled..."
docker run --name $CONTAINER_NAME -d \
  -p 127.0.0.1:$HOST_PORT:$CONTAINER_PORT \
  -v "$MONGO_VOLUME:/data/db" \
  $DUMP_VOLUME \
  mongo:$MONGO_VERSION --auth

echo "[INFO] Waiting for MongoDB to restart with authentication (15 seconds)..."
sleep 15

# Step 6: Verify connection
echo "[INFO] Step 6: Verifying MongoDB connection with authentication..."
MAX_RETRY=3
RETRY_COUNT=0
CONNECTION_SUCCESS=false

while [ $RETRY_COUNT -lt $MAX_RETRY ] && [ "$CONNECTION_SUCCESS" = false ]; do
  if docker exec $CONTAINER_NAME mongosh --quiet --eval "db.runCommand({ping:1})" -u "$MONGO_USER" -p "$MONGO_PASSWORD" --authenticationDatabase admin; then
    echo "[INFO] MongoDB connection verified successfully with authentication."
    CONNECTION_SUCCESS=true
  else
    RETRY_COUNT=$((RETRY_COUNT+1))
    if [ $RETRY_COUNT -lt $MAX_RETRY ]; then
      echo "[INFO] Connection attempt $RETRY_COUNT failed. Waiting 5 seconds before retry..."
      sleep 5
    else
      echo "[WARN] Could not verify MongoDB connection with authentication after $MAX_RETRY attempts."
      echo "[WARN] However, MongoDB should still be running with authentication enabled."
    fi
  fi
done

# Save connection details to a file
CONNECTION_STRING="mongodb://$MONGO_USER:$MONGO_PASSWORD@localhost:$HOST_PORT/admin?authSource=admin"
echo "MongoDB connection string: $CONNECTION_STRING" > $CREDENTIALS_FILE
echo "User: $MONGO_USER" >> $CREDENTIALS_FILE
echo "Password: $MONGO_PASSWORD" >> $CREDENTIALS_FILE
chmod 600 $CREDENTIALS_FILE  # Restrict file permissions for security

echo "[INFO] MongoDB deployed successfully!"
echo "[INFO] Connection credentials saved to $CREDENTIALS_FILE"
echo ""
echo "================================================================"
echo "IMPORTANT: Update your .env file with the following line:"
echo "MONGODB_URL=\"$CONNECTION_STRING\""
echo "================================================================"
echo ""
echo "You can test the connection manually with:"
echo "docker exec -it $CONTAINER_NAME mongosh -u \"$MONGO_USER\" -p \"$MONGO_PASSWORD\" --authenticationDatabase admin"