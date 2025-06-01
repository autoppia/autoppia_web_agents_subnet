#!/usr/bin/env bash
set -euo pipefail

# Ensure the script is run from its own directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Define build context (docker project location)
CONTEXT_DIR="${SCRIPT_DIR}/autoppia_web_operator/backend"
IMAGE_NAME="autoppia-api"
CONTAINER_NAME="autoppia-api"
HOST_PORT=4000
CONTAINER_PORT=4000

# Check for Docker
if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is not installed or not in PATH."
  exit 1
fi

# Verify Dockerfile exists in context
DOCKERFILE_PATH="$CONTEXT_DIR/Dockerfile"
if [[ ! -f "$DOCKERFILE_PATH" ]]; then
  echo "Error: Dockerfile not found in $CONTEXT_DIR"
  exit 1
fi

# Build the Docker image
echo "Building Docker image '${IMAGE_NAME}' from context '${CONTEXT_DIR}'..."
docker build \
  --file "$DOCKERFILE_PATH" \
  --tag "$IMAGE_NAME:latest" \
  "$CONTEXT_DIR"

# Stop and remove any existing container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Stopping existing container '${CONTAINER_NAME}'..."
  docker stop "$CONTAINER_NAME"
  echo "Removing existing container '${CONTAINER_NAME}'..."
  docker rm "$CONTAINER_NAME"
fi

# Run the container
echo "Starting container '${CONTAINER_NAME}' on port ${HOST_PORT}..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p ${HOST_PORT}:${CONTAINER_PORT} \
  --restart unless-stopped \
  "$IMAGE_NAME:latest"

# Wait a bit and show logs to verify startup
sleep 2

echo "Container logs (last 20 lines):"
docker logs --tail 20 "$CONTAINER_NAME"

echo "Deployment complete. API is available at http://localhost:${HOST_PORT}"
