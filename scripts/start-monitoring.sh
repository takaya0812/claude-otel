#!/bin/zsh
# Wait for Docker daemon to be available (max 60s)
for i in {1..30}; do
  docker info &>/dev/null && break
  sleep 2
done

cd /Users/takaya/dev/claude-otel

# Start OTel collector and Grafana
docker compose up -d

# Kill any existing ingest.py processes to prevent duplicates
pkill -f "ingest.py --watch" 2>/dev/null || true
sleep 1

# Start ingest watch loop (exec replaces this shell process)
exec /usr/bin/python3 /Users/takaya/dev/claude-otel/scripts/ingest.py --watch
