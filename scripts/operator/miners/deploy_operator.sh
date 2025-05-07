#!/usr/bin/env bash
set -euo pipefail

# ensure script is run as root or a user in the docker group
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on your PATH."
  exit 1
fi

# locate this script's directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT_DIR="$BASE_DIR/autoppia_web_operator/agent"

IMAGE_NAME="autoppia-operator"
CONTAINER_NAME="autoppia-operator"

# make sure the Dockerfile exists
if [[ ! -f "$CONTEXT_DIR/Dockerfile" ]]; then
  echo "Dockerfile not found in $CONTEXT_DIR"
  exit 1
fi

# build the Docker image
echo "Building Docker image ${IMAGE_NAME} from context ${CONTEXT_DIR}..."
docker build -t "${IMAGE_NAME}" "${CONTEXT_DIR}"

# stop and remove existing container if present
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}\$"; then
  echo "Stopping existing container ${CONTAINER_NAME}..."
  docker stop "${CONTAINER_NAME}"
  echo "Removing existing container ${CONTAINER_NAME}..."
  docker rm "${CONTAINER_NAME}"
fi

# run the container
echo "Starting container ${CONTAINER_NAME} on port 5000..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p 5000:5000 \
  --restart unless-stopped \
  "${IMAGE_NAME}"

echo "Deployment complete. Operator API is available at http://localhost:5000"
