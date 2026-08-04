#!/bin/bash
# Live agent observer (design doc 008) — watches Odysseus agent runs through
# the app's own API instead of container logs: full SSE feed (text deltas,
# thinking, tool calls, tool_policy, metrics), replay + live, authenticated.
#
# Usage (preferred — API token created in Odysseus settings):
#   ODY_URL=http://192.168.1.192 ODY_TOKEN=ody_... ./watch_agent.sh [session_id]
# Or with password login:
#   ODY_URL=... ODY_USER=admin ODY_PASS=... ./watch_agent.sh [session_id]
# With no session_id: polls /api/chat/runs and attaches to the first running
# session it finds. Events append to $OUT (default /tmp/agent-feed.log).
set -u
ODY_URL="${ODY_URL:-http://localhost:80}"
ODY_TOKEN="${ODY_TOKEN:-}"
OUT="${OUT:-/tmp/agent-feed.log}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

if [ -n "$ODY_TOKEN" ]; then
  AUTH=(-H "Authorization: Bearer $ODY_TOKEN")
else
  ODY_USER="${ODY_USER:-admin}"
  ODY_PASS="${ODY_PASS:?set ODY_TOKEN or ODY_PASS}"
  curl -s -c "$JAR" -X POST "$ODY_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\": \"$ODY_USER\", \"password\": \"$ODY_PASS\"}" \
    | grep -q '"ok": *true' || { echo "login failed for $ODY_USER at $ODY_URL" >&2; exit 1; }
  AUTH=(-b "$JAR")
fi

# Explicit session: single-shot attach (old behavior).
if [ -n "${1:-}" ]; then
  echo "[watch] attaching to $1 -> $OUT" >&2
  curl -s -N "${AUTH[@]}" "$ODY_URL/api/chat/resume/$1" >> "$OUT"
  echo "[watch] stream ended for $1" >&2
  exit 0
fi

# Continuous mode: run forever. Prefer LIVE runs; also replay finished runs
# still in the retention buffer that we haven't captured (a short turn that
# ends between polls is not lost). SEEN prevents duplicate replays; a session
# that runs AGAIN gets a fresh run object and is re-captured live.
SEEN="${SEEN:-$OUT.seen}"
touch "$SEEN"
echo "[watch] continuous mode -> $OUT (seen: $SEEN)" >&2
while true; do
  SID=$(curl -s "${AUTH[@]}" "$ODY_URL/api/chat/runs" | SEEN="$SEEN" python3 -c '
import json, os, sys
try:
    runs = json.load(sys.stdin).get("runs", [])
except Exception:
    runs = []
seen = set(open(os.environ["SEEN"]).read().split())
running = [r for r in runs if r["status"] == "running"]
done = [r for r in runs if r["status"] != "running" and r["session_id"] not in seen]
pick = running or done
print(pick[0]["session_id"] if pick else "")' 2>/dev/null)
  if [ -z "$SID" ]; then sleep 2; continue; fi
  echo "[watch] attaching to $SID" >&2
  printf "\n: ==== run %s @ %s ====\n\n" "$SID" "$(date -Iseconds)" >> "$OUT"
  curl -s -N "${AUTH[@]}" "$ODY_URL/api/chat/resume/$SID" >> "$OUT"
  echo "$SID" >> "$SEEN"
  echo "[watch] stream ended for $SID" >&2
done
