#!/bin/bash
# Deploy pipeline for copperwarehouse (doc 007, incl. the 3b in-image test
# gate). Run ON THE SERVER: bash deploy-with-gate.sh <tag> <rollback-tag>
# e.g.: bash deploy-with-gate.sh servers1 v69-rollback
#
# The gate is the reason this script exists: the suite runs INSIDE the
# freshly built image — the only environment whose verdict counts (the
# Windows dev machine fails on cp1252/POSIX-path noise; 2026-08-07 the same
# files passed 37/37 in-image). No green, no swap.
set -euo pipefail

TAG="${1:?usage: deploy-with-gate.sh <tag> <rollback-tag>}"
ROLLBACK="${2:?usage: deploy-with-gate.sh <tag> <rollback-tag>}"
IMAGE="odysseus:${TAG}"
PROD="ghcr.io/odysseus-dev/odysseus:latest"
BUILD_DIR="/tmp/ody-build"

echo "=== 1. sync build checkout"
cd "$BUILD_DIR"
git pull
git log --oneline -1

echo "=== 2. build ${IMAGE}"
docker build -q -t "$IMAGE" .

echo "=== 3b. IN-IMAGE TEST GATE (doc 007) — no green, no swap"
docker run --rm -v "$BUILD_DIR/tests:/srctests:ro" "$IMAGE" \
  sh -c 'cp -r /srctests /app/tests && cd /app && \
         pip install -q pytest >/dev/null 2>&1; \
         python -m pytest tests/ -q --tb=line' \
  || { echo "GATE-FAILED: suite red inside ${IMAGE} — deploy aborted"; exit 1; }

echo "=== 4. preflight: stream activity in last 90s?"
ACT=$(docker logs --since 90s odysseus 2>&1 | grep -cE 'chat_stream|agent_step|\[agent\] round' || true)
if [ "$ACT" -gt 0 ]; then
  echo "DEPLOY-BLOCKED: $ACT active-stream log lines in last 90s"
  exit 1
fi
echo "quiet — proceeding"

echo "=== 5. rollback tag + swap"
docker tag "$PROD" "odysseus:${ROLLBACK}"
docker tag "$IMAGE" "$PROD"
docker rm -f odysseus

docker run -d --name odysseus \
  --net br1 --ip 192.168.1.192 --mac-address c2:32:fc:a0:48:01 \
  --add-host host.docker.internal:host-gateway \
  -e ODYSSEUS_INPROCESS_POLLERS=1 \
  -e DATABASE_URL=sqlite:///./data/app.db \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
  -e CHROMADB_HOST=192.168.1.193 \
  -e FASTEMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  -e TZ=Europe/Berlin \
  -e SEARXNG_INSTANCE=http://192.168.1.194:8080 \
  -e SECURE_COOKIES=false \
  -e "ALLOWED_ORIGINS=http://192.168.1.192,https://odysseus.mercat-jazz.ts.net" \
  -e PUID=99 -e PGID=100 \
  -e ODYSSEUS_ADMIN_USER=admin \
  -e ODYSSEUS_ADMIN_PASSWORD=changed \
  -e LOCALHOST_BYPASS=false \
  -e CLEANUP_INTERVAL_HOURS=24 \
  -e ODYSSEUS_SCRIPT_HOST=localhost \
  -e LLM_HOST=localhost \
  -e CHROMADB_PORT=8000 \
  -e AUTH_ENABLED=true \
  -e ODYSSEUS_INPROCESS_TASKS=1 \
  -e ODYSSEUS_PUBLIC_HOST=192.168.1.192 \
  -v /mnt/user/appdata/odysseus/data/huggingface:/app/.cache/huggingface \
  -v /mnt/user/appdata/odysseus/data/local:/app/.local \
  -v /mnt/user/appdata/odysseus/data:/app/data \
  -v /mnt/user/appdata/odysseus/logs:/app/logs \
  -v /mnt/user/appdata/odysseus/data/ssh:/app/.ssh \
  -l net.unraid.docker.managed=dockerman \
  -l 'net.unraid.docker.webui=http://[IP]' \
  -l net.unraid.docker.icon=https://raw.githubusercontent.com/odysseus-dev/odysseus/dev/static/icons/icon-512.png \
  --sysctl net.ipv4.ip_unprivileged_port_start=0 \
  --restart unless-stopped \
  "$PROD" \
  uvicorn app:app --host 0.0.0.0 --port 80

echo "=== 6. readiness"
for i in $(seq 1 30); do
  sleep 2
  CODE=$(docker exec odysseus curl -s -o /dev/null -w '%{http_code}' http://localhost:80/ 2>/dev/null || echo 000)
  if [ "$CODE" = "200" ] || [ "$CODE" = "302" ]; then
    echo "HTTP-UP ($CODE) after $((i*2))s"
    break
  fi
  if [ "$i" = "30" ]; then
    echo "HTTP-DOWN after 60s"; docker logs --tail 30 odysseus; exit 1
  fi
done

echo "=== 7. skilodge relaunch through the registry (uid 99)"
# Needed until skilodge carries autostart=true; after that, boot
# reconciliation (doc 017 §7) does this by itself.
docker exec -u 99 -w /app odysseus python -c "from src import toolchain, bg_jobs; toolchain.ensure_toolchain_env(); bg_jobs.server_restart('skilodge')" || true

echo "DEPLOYED — ${IMAGE} (rollback: docker tag odysseus:${ROLLBACK} ${PROD} + recreate)"
