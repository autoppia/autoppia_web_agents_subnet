#!/bin/bash
# deploy_mongo_docker.sh - Deploy MongoDB via Docker with enhanced security
# Automatically generates a secure random password and updates .env file

set -euo pipefail

# Configuration variables
CONTAINER_NAME="mongodb"
MONGO_VERSION="latest"
HOST_PORT=27017
CONTAINER_PORT=27017
MONGO_VOLUME="$HOME/mongodb_data"
DUMP_FOLDER="$(pwd)/data/mongo-dump"
MONGO_USER="adminUser"
# Generate a secure random password (32 characters)
MONGO_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
ENV_FILE=".env"

# Ask user if they want to clean all data
clean_data=false
read -p "[PROMPT] Do you want to clean all MongoDB data and start fresh? (y/N): " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
  clean_data=true
  echo "[INFO] Will clean all MongoDB data before starting."
else
  echo "[INFO] Will keep existing MongoDB data."
fi

echo "[INFO] Starting MongoDB deployment with security measures..."

# Stop and remove existing container if it exists
if docker ps -a | grep -q $CONTAINER_NAME; then
  echo "[INFO] Stopping and removing existing MongoDB container..."
  docker stop $CONTAINER_NAME
  docker rm $CONTAINER_NAME
fi

# Clean data volume if requested
if [ "$clean_data" = true ]; then
  echo "[INFO] Cleaning MongoDB data volume at $MONGO_VOLUME..."
  rm -rf "$MONGO_VOLUME"
  mkdir -p "$MONGO_VOLUME"
  echo "[INFO] MongoDB data volume cleaned."
else
  # Create data directory if it doesn't exist
  mkdir -p "$MONGO_VOLUME"
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

# Step 2: Create admin user with secure random password
echo "[INFO] Step 2: Creating admin user with secure random password..."
if docker exec $CONTAINER_NAME mongosh --eval "
  db = db.getSiblingDB('admin');
  db.createUser({
    user: '$MONGO_USER',
    pwd: '$MONGO_PASSWORD',
    roles: [{ role: 'root', db: 'admin' }]
  });
"; then
  echo "[INFO] Admin user created successfully with secure random password."
else
  echo "[WARN] Failed to create admin user. It might already exist."
  if [ "$clean_data" = false ]; then
    echo "[WARN] Your existing MongoDB may have a different password."
    echo "[WARN] If connection fails, rerun this script with clean data option."
  fi
fi

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
  if docker exec $CONTAINER_NAME mongosh --quiet --eval "db.runCommand({ping:1})" -u "$MONGO_USER" -p "$MONGO_PASSWORD" --authenticationDatabase admin &>/dev/null; then
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

# Create connection string with URL encoding for special characters in password
ENCODED_PASSWORD=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$MONGO_PASSWORD'))")
CONNECTION_STRING="mongodb://$MONGO_USER:$ENCODED_PASSWORD@localhost:$HOST_PORT/admin?authSource=admin"

# Update .env file with new connection string if it exists
if [ -f "$ENV_FILE" ]; then
  echo "[INFO] Updating .env file with MongoDB connection string..."
  # Check if MONGODB_URL exists in .env file
  if grep -q "MONGODB_URL=" "$ENV_FILE"; then
    # Replace existing MONGODB_URL line
    sed -i "s|MONGODB_URL=.*|MONGODB_URL=\"$CONNECTION_STRING\"|" "$ENV_FILE"
  else
    # Add MONGODB_URL line at the end
    echo "MONGODB_URL=\"$CONNECTION_STRING\"" >> "$ENV_FILE"
  fi
  echo "[INFO] .env file updated successfully."
else
  echo "[WARN] .env file not found. Creating a new one with MongoDB connection string."
  echo "MONGODB_URL=\"$CONNECTION_STRING\"" > "$ENV_FILE"
fi

echo "[INFO] MongoDB deployed successfully with secure configuration!"
echo "[INFO] Your MongoDB is now accessible only from localhost and requires authentication."
echo "[INFO] Your connection string has been automatically added to the .env file."
echo ""
echo "================================================================"
echo "IMPORTANT: Your MongoDB is now secured with a randomly generated"
echo "password that has been stored in your .env file. You don't need"
echo "to know the actual password since the connection string is all"
echo "your application needs."
echo "================================================================"