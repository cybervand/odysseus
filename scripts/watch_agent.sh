#!/bin/bash
# Live agent observer (design doc 008) — watches Odysseus agent runs through
# the app's own API instead of container logs: full SSE feed (text deltas,
# thinking, tool calls, tool_policy, metrics), replay + live, authenticated.
#
# Usage:  ODY_URL=http://192.168.1.192 ODY_USER=admin ODY_PASS=... \
#           ./watch_agent.sh [session_id]
# With no session_id: polls /api/chat/runs and attaches to the first running
# session it finds. Events append to $OUT (default /tmp/agent-feed.log).
set -u
ODY_URL="${ODY_URL:-http://localhost:80}"
ODY_USER="${ODY_USER:-admin}"
ODY_PASS="${ODY_PASS:?set ODY_PASS}"
OUT="${OUT:-/tmp/agent-feed.log}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

login() {
  curl -s -c "$JAR" -X POST "$ODY_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\": \"$ODY_USER\", \"password\": \"$ODY_PASS\"}" | grep -q '"ok": *true'
}

login || { echo "login failed for $ODY_USER at $ODY_URL" >&2; exit 1; }

SID="${1:-}"
if [ -z "$SID" ]; then
  echo "[watch] polling for a running session..." >&2
  while [ -z "$SID" ]; do
    SID=$(curl -s -b "$JAR" "$ODY_URL/api/chat/runs" \
      | python3 -c 'import json,sys; runs=[r for r in json.load(sys.stdin).get("runs",[]) if r["status"]=="running"]; print(runs[0]["session_id"] if runs else "")' 2>/dev/null)
    [ -z "$SID" ] && sleep 2
  done
fi

echo "[watch] attaching to $SID -> $OUT" >&2
# Replay + live; -N disables buffering so events land as they happen.
curl -s -N -b "$JAR" "$ODY_URL/api/chat/resume/$SID" >> "$OUT"
echo "[watch] stream ended for $SID" >&2
