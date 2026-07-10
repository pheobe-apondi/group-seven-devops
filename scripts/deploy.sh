#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="${1:-}"
if [ -z "$IMAGE_TAG" ]; then
  echo "Usage: ./scripts/deploy.sh sha-<short-commit-hash>"
  echo "Example: ./scripts/deploy.sh sha-a1b2c3d"
  exit 1
fi

if [[ ! "$IMAGE_TAG" =~ ^sha-[0-9a-f]{7,40}$ ]]; then
  echo "Error: IMAGE_TAG must be in the format sha-<commit-hash> (e.g. sha-a1b2c3d)"
  exit 1
fi

if [ -z "${DOCKERHUB_USERNAME:-}" ]; then
  echo "Error: DOCKERHUB_USERNAME is not set"
  exit 1
fi

export IMAGE_TAG
export APP_NAME="${APP_NAME:-group-seven-devops}"

echo "Deploying ${APP_NAME} with image tag: ${IMAGE_TAG}"
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --wait --remove-orphans
docker compose -f docker-compose.prod.yml ps
