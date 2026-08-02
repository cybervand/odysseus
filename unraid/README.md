# Odysseus on Unraid

Docker templates for running Odysseus as a native Unraid app, plus optional
companion services. The main image is published to
`ghcr.io/odysseus-dev/odysseus` (`:latest` from `main`, `:dev` rolling) by CI.

| Template | Container | Purpose |
| --- | --- | --- |
| `odysseus.xml` | Odysseus | The app itself (required) |
| `odysseus-searxng.xml` | SearXNG | Web search for Deep Research (optional) |
| `odysseus-chromadb.xml` | ChromaDB | Long-term memory (optional) |
| `odysseus-ntfy.xml` | ntfy | Push notifications (optional) |

## Installing

### Option A — add this repo as a template repository (recommended)

1. In the Unraid web UI go to the **Docker** tab and scroll to the bottom.
2. In **Template Repositories**, add on its own line:

   ```text
   https://github.com/odysseus-dev/odysseus
   ```

3. Click **Save**, then **Add Container** and pick **Odysseus** from the
   *Template* dropdown (under the repository's user templates).

### Option B — copy the XML to your flash drive

Copy the `.xml` files from this folder to
`/boot/config/plugins/dockerMan/templates-user/` on your Unraid server, then
**Docker → Add Container** and select the template from the dropdown.

### Option C — Community Applications

Publishing to the CA store requires submitting a template repository to the
[Community Applications appFeed](https://forums.unraid.net/topic/57181-docker-faq/)
(see the "Getting your template into CA" moderation thread). These templates
are CA-compatible as-is; until they are accepted, Options A/B give the same
install experience.

## First start

- Open `http://SERVER_IP:7000` once the container is running.
- Login is `admin` plus the password you set in the template. If you left it
  blank, a random password is printed **once** in the container log
  (Docker tab → click the Odysseus icon → **Logs**).
- All data lives under `/mnt/user/appdata/odysseus/` — back up the `data`
  subfolder.

## Wiring up the companions

Unraid's default bridge network has no name resolution between containers, so
point Odysseus at companions via the **server IP and host port**:

| Odysseus variable | Value |
| --- | --- |
| `SEARXNG_INSTANCE` | `http://SERVER_IP:8089` |
| `CHROMADB_HOST` / `CHROMADB_PORT` | `SERVER_IP` / `8100` |
| `LLM_HOST` | `host.docker.internal` (Ollama etc. on the Unraid host) |

**SearXNG needs one manual step**: Odysseus uses its JSON API, which is off by
default. After the SearXNG container's first start, edit
`/mnt/user/appdata/odysseus/searxng/settings.yml` so the formats list includes
`json`:

```yaml
search:
  formats:
    - html
    - json
```

then restart the SearXNG container. (Equivalently, copy this repo's
[`config/searxng/settings.yml`](../config/searxng/settings.yml) there before
first start and replace `__SEARXNG_SECRET__` with any random string.)

## Connecting Ollama (agent tools)

If you use Ollama as a model backend, add it inside Odysseus as an endpoint
pointing at `http://SERVER_IP:11434/v1` — and **enable the endpoint's
"supports tools" toggle** for models that do native tool calling (Qwen 3+,
gpt-oss, Llama 3+, etc.). Without it, Odysseus falls back to a text-based
tool protocol that small models often fail to follow, and agent-mode tools
(web search, shell, notes...) silently never execute.

If Ollama runs in its own container with a memory limit, note that loading a
large model right after pulling one can fail with "model requires more system
memory" even though the host has plenty free — reclaimable page cache counts
against the container's cgroup until it is reclaimed. Restarting the Ollama
container clears it.

## GPU (optional)

For NVIDIA GPUs (Cookbook local model serving):

1. Install the **Nvidia Driver** plugin from Community Applications.
2. On the Odysseus container, add to **Extra Parameters**:
   `--runtime=nvidia`
3. Add variables `NVIDIA_VISIBLE_DEVICES=all` and
   `NVIDIA_DRIVER_CAPABILITIES=compute,utility`.

## Updating

Unraid's built-in **Check for Updates** on the Docker tab pulls the newest
image for the tag in the template (`:latest`). Switch the Repository field to
`ghcr.io/odysseus-dev/odysseus:dev` if you want the rolling dev branch.
