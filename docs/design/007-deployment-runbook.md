# 007 — copperwarehouse deployment runbook

**Status:** Living document

Production: Unraid server `copperwarehouse` (`root@192.168.1.113`),
container `odysseus` on br1 macvlan `192.168.1.192`, data at
`/mnt/user/appdata/odysseus/data`. Ollama on the host at `:11434`
(gpt-oss:20b, qwen3-coder:30b, etc.).

## Deploy flow (git-based — the only sanctioned flow)

1. Commit on local `dev`; run the relevant tests.
2. `git push fork dev:deploy/pipfix` (fork = github.com/cybervand/odysseus).
3. On the server: `cd /tmp/ody-build && git pull && docker build -t
   odysseus:<name> .`
3b. **In-image test gate** (2026-08-07): run the suite INSIDE the freshly
   built image before any swap — the image excludes `tests/`, so mount them
   from the build checkout and copy into /app (a straight mount is
   root-owned and unwritable for the dropped uid; DATA_DIR mkdir fails):

   ```sh
   docker run --rm -v /tmp/ody-build/tests:/srctests:ro odysseus:<name> \
     sh -c 'cp -r /srctests /app/tests && cd /app && \
            pip install -q pytest >/dev/null 2>&1; \
            python -m pytest tests/ -q --tb=line'
   ```

   Abort the deploy on any failure. This is the AUTHORITATIVE run: the
   Windows dev machine reports environment noise — cp1252 default encoding
   (webhook route-scanner test), POSIX /tmp assumptions (path confinement),
   fuzz-fixture setup errors — all of which pass 37/37 in the image
   (verified 2026-08-07 against odysseus:ledger1). Throwaway container, no
   volumes beyond the ro tests mount, so it cannot touch production data.
4. Tag rollback chain, retag, recreate:
   `docker tag ghcr.io/odysseus-dev/odysseus:latest odysseus:vN-rollback`
   → `docker tag odysseus:<name> ghcr.io/odysseus-dev/odysseus:latest`
   → `docker rm -f odysseus` → full `docker run` (canonical arg list lives
   in shell history / container inspect; labels, mounts, env, sysctl,
   `--add-host host.docker.internal:host-gateway`, restart unless-stopped).
5. Verify: grep a marker of the change inside the running container; HTTP
   probe returns 302 (auth redirect); `docker logs` clean.

Why git-based: the image provably matches committed code (file-copy patching
drifted and is also blocked by the local permission tooling). `docker
restart` does NOT pick up a new image — always recreate.

## Blue/green lab

`odysseus-v2test` on `192.168.1.195`, `AUTH_ENABLED=false`, data COPY
(`cp -a data data-v2test`); remove container + copy after use. Smoke via
`docker exec curl -N -X POST http://localhost:80/api/chat_stream ...`.

### Lab pitfalls (all learned the hard way)

- **Unauthenticated curl has NO owner** → every owner-scoped query
  (documents, library) returns empty. Model behavior involving documents is
  INVALID in curl smokes; use direct tool invocation with
  `ctx={"owner": "admin"}` inside the container instead.
- Data copies reset state — don't assume yesterday's lab edits exist.
- `--max-time` on smoke curls kills long runs; a "failed" run may have been
  mid-work (count it honestly or raise the cap).
- Tool results are NOT in `chat_messages.content`; per-call truth lives in
  `chat_messages.metadata` JSON → `tool_events[].output`.

## Frontend changes

**Always bump the `?v=` cache-buster in `static/index.html`** for any
changed JS/CSS file. No build pipeline does this; a stale buster means
deploys silently never reach browsers (document.js was stale July 22 →
Aug 4).

## Rollback

`docker tag odysseus:vN-rollback ghcr.io/odysseus-dev/odysseus:latest` +
recreate. Chain kept: v1 (pre-upstream-merge era) … v12 (owner library
manifest). Ollama model blobs can silently break across Ollama upgrades —
re-pull the model, don't debug the runtime (cost a day once:
`tensor size overflow`).

## Decision log

- 2026-08-03 — switched file-copy → git-based builds.
- 2026-08-04 — lab owner pitfall + cache-buster rule recorded.
- 2026-08-07 — in-image test gate added (step 3b, user's idea): the suite
  runs in the built image before the swap; the Windows dev machine's suite
  is advisory only (3 test files fail there on cp1252/POSIX-path/fixture
  environment issues yet pass 37/37 in the image).
