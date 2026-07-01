#!/bin/bash
set -euo pipefail

SERVER="156.67.27.164"
PASSWORD="arinedge"
USER="root"
IMAGE="arinedge_backend"
PORT="8000"
REMOTE_DIR="/opt/portal/backend"

SSH="sshpass -p $PASSWORD ssh -o StrictHostKeyChecking=no $USER@$SERVER"
SCP="sshpass -p $PASSWORD scp -o StrictHostKeyChecking=no"
RSYNC="sshpass -p $PASSWORD rsync -avz --delete -e \"ssh -o StrictHostKeyChecking=no\""

echo "============================================"
echo "  Portal Backend - Deploy Script"
echo "============================================"

echo ""
echo ">>> [1/5] Analyzing existing Docker containers on $SERVER..."
$SSH "docker ps -a --filter name=arinedge_backend"

echo ""
echo ">>> [2/5] Stopping and removing old container..."
$SSH "docker stop $IMAGE 2>/dev/null && echo 'Stopped: $IMAGE' || echo 'No running container: $IMAGE'"
$SSH "docker rm $IMAGE 2>/dev/null && echo 'Removed: $IMAGE' || echo 'No container to remove'"

echo ""
echo ">>> [3/5] Preserving old image for build cache..."
echo "  (docker rmi removed — layer caching speeds up subsequent deploys)"

echo ""
echo ">>> [4/5] Copying project files and .env to server..."
$SSH "mkdir -p $REMOTE_DIR"
eval $RSYNC \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude 'env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'logs' \
  --exclude 'docs' \
  --exclude '.DS_Store' \
  --exclude 'support_files' \
  ./ "$USER@$SERVER:$REMOTE_DIR/"
$SCP .env "$USER@$SERVER:$REMOTE_DIR/.env"

echo ""
echo ">>> [5/5] Building and starting new container on server..."
$SSH "cd $REMOTE_DIR && \
  docker build -t $IMAGE:latest . && \
  docker run -d \
    --name $IMAGE \
    -p $PORT:$PORT \
    --restart unless-stopped \
    --env-file $REMOTE_DIR/.env \
    -v portal_api_logs:/app/logs \
    --network portal-net \
    $IMAGE:latest"

echo ""
echo ">>> Verifying deployment..."
sleep 3
$SSH "docker ps --filter name=$IMAGE --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

echo ""
echo ">>> Checking health endpoint..."
sleep 3
curl -s http://$SERVER:$PORT/health || echo "Health check failed - container may still be starting"

echo ""
echo "============================================"
echo "  Deploy complete!"
echo "  Container: $IMAGE"
echo "  URL: http://$SERVER:$PORT"
echo "  Docs: http://$SERVER:$PORT/docs"
echo "============================================"
