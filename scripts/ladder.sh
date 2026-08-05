#!/bin/bash
# Prompt-ladder harness (design doc 013).
#
# Usage:  ladder.sh MODEL [CLARIFIER...]
#   e.g.  ladder.sh deepseek-r1:14b            # R0 — lazy prompt only
#         ladder.sh deepseek-r1:14b C1 C2      # R1 — one rung per NEW clarifier set
#
# Protocol (doc 012 measurement rules): preflight asserts no live runs,
# stream capped, then drain /api/chat/runs before grading. Results append
# to $RESULTS as one JSON line per run — the seed of the model-prompt
# compatibility database.
#
# The R0 prompt is deliberately lazy (verbatim user phrasing, typos kept)
# with a rotating business so models can't pattern-match a burned-in theme.

TOKEN="${ODY_TOKEN:?set ODY_TOKEN}"
URL="${ODY_URL:-http://192.168.1.192}"
RESULTS="${LADDER_RESULTS:-/tmp/ladder-results.jsonl}"

MODEL="${1:?usage: ladder.sh MODEL [CLARIFIER...]}"; shift
CLARIFIERS=("$@")

BUSINESSES=("barbershop" "bike repair shop" "bakery" "plant nursery" \
  "tattoo studio" "used bookstore" "climbing gym" "ramen bar" \
  "record store" "pet grooming salon")
BIZ="${BUSINESSES[$((RANDOM % ${#BUSINESSES[@]}))]}"

SLUG=$(echo "$MODEL" | tr ":./ " "----"); RND=$RANDOM
RUNG="R${#CLARIFIERS[@]}"

# R0 base — the lazy human, verbatim shape:
PROMPT="build me a website for my local business, i want to have it pretty its for a $BIZ so i want you to get open source images from the net, i also want you make it with react etc"

# Clarifier catalog (doc 013 rung table). Add ONE new clarifier per rung.
for C in "${CLARIFIERS[@]}"; do
  case "$C" in
    C1)  PROMPT="$PROMPT. put everything in ONE folder named site_${SLUG}_${RND}" ;;
    C2)  PROMPT="$PROMPT. content first: write the actual pages before any toolchain setup" ;;
    C3)  PROMPT="$PROMPT. make sure they are files i can access on the filesystem" ;;
    C4)  PROMPT="$PROMPT. do not use documents - a document is not a file" ;;
    C5)  PROMPT="$PROMPT. verify for real: run ls and show the output" ;;
    C6)  PROMPT="$PROMPT. do not stop until the files exist" ;;
    C7)  PROMPT="$PROMPT. use your bash and write_file tools" ;;
    C8)  PROMPT="$PROMPT. plain html/css/js is fine instead of react" ;;
    C9)  PROMPT="$PROMPT. linking images by url is fine, no need to download them" ;;
    C10) PROMPT="$PROMPT. do not ask questions" ;;
    *) echo "unknown clarifier: $C" >&2; exit 1 ;;
  esac
done

# --- preflight: no live runs (doc 012 contamination rule) ---
PRE=$(curl -s -H "Authorization: Bearer $TOKEN" "$URL/api/chat/runs" | grep -c session_id)
[ "$PRE" != "0" ] && { echo "PREFLIGHT-BUSY: $PRE live run(s) — aborting" >&2; exit 1; }

SID=$(curl -s -X POST "$URL/api/session" -H "Authorization: Bearer $TOKEN" \
  -F "name=ladder-$RUNG-$SLUG-$RND" -F "model=$MODEL" \
  -F "endpoint_id=e6e2154e" -F "skip_validation=true" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))")
[ -z "$SID" ] && { echo "SESSION-FAIL" >&2; exit 1; }

docker exec odysseus sh -c "touch /tmp/laddermark"
MARK=$(date -Iseconds)
echo ">> $MODEL $RUNG biz='$BIZ' prompt: $PROMPT" >&2

curl -s -N --max-time 420 -X POST "$URL/api/chat_stream" \
  -H "Authorization: Bearer $TOKEN" --form-string "message=$PROMPT" \
  -F "session=$SID" -F "chat_mode=agent" -F "allow_bash=true" >/dev/null 2>&1

# --- drain before grading (doc 012: buffered runs outlive the stream) ---
W=0
until [ "$(curl -s -H "Authorization: Bearer $TOKEN" "$URL/api/chat/runs" | grep -c session_id)" = "0" ] || [ $W -ge 90 ]; do
  W=$((W+1)); sleep 10
done

LOG=$(docker logs odysseus --since "$MARK" 2>&1)
NEWF=$(docker exec odysseus sh -c "find /app/data -newer /tmp/laddermark -type f \
  -not -path '*/node_modules/*' -not -path '*/.*' \
  -not -path '*/logs/*' -not -name 'app.db*' -not -name 'memory.json' \
  -not -name '_usage.json' 2>/dev/null")
CONTENT=$(echo "$NEWF" | grep -cE "\.(html|css|js|jsx|tsx|ts)$")
ROOTS=$(echo "$NEWF" | sed "s|/app/data/||" | cut -d/ -f1 | sort -u | wc -l)
SCAFFOLD=$(echo "$NEWF" | grep -c "package.json")
NPM=$(echo "$LOG" | grep -cE "Tool executed: bash: (npm|npx|yarn)")
WEB=$(echo "$LOG" | grep -cE "Tool executed: (web_search|web_fetch)|Tool executed: bash: (curl|wget)")
TOOLS=$(echo "$LOG" | grep -c "Tool executed")
DOCS=$(echo "$LOG" | grep -c "Tool executed: create_document")

python3 - "$MODEL" "$RUNG" "$BIZ" "$RND" <<PYEOF >> "$RESULTS"
import json, sys
print(json.dumps({
  "model": sys.argv[1], "rung": sys.argv[2], "business": sys.argv[3],
  "run_id": sys.argv[4], "clarifiers": "${CLARIFIERS[*]}",
  "prompt": """$PROMPT""",
  "drain_s": $((W*10)), "tools": $TOOLS, "npm_calls": $NPM,
  "web_calls": $WEB, "doc_escapes": $DOCS, "content_files": $CONTENT,
  "new_roots": $ROOTS, "scaffolds": $SCAFFOLD,
}))
PYEOF
echo "=== NEW FILES (content) ==="
echo "$NEWF" | grep -E "\.(html|css|js|jsx|tsx|ts)$" | head -15
tail -1 "$RESULTS"
echo "LADDER DONE"
