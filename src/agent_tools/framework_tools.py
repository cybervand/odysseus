"""manage_framework — the shared toolchain as a first-class tool (doc 015).

Location is the decision models get wrong (installs into the ephemeral
container tier die on deploy), so this tool removes it: one right place,
tool-owned. The resolver decides npm-vs-pip, the manifest remembers for
every future chat, and unknown names require an explicit manager because
a typo installs someone else's package.
"""
import json

from src import toolchain


class ManageFrameworkTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        session_id = ctx.get("session_id") or ""
        raw = (content or "").strip()
        try:
            args = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        action = str(args.get("action", "list")).strip().lower()
        name = str(args.get("name") or "").strip()
        version = str(args.get("version") or "").strip() or None
        manager = str(args.get("manager") or "").strip().lower() or None

        if action == "list":
            m = toolchain.manifest_list()
            if not m:
                return {"output": ("Shared toolchain is empty. Install one: "
                                   '{"action": "install", "name": "tailwindcss"} — '
                                   "it persists across restarts and every chat can use it."),
                        "exit_code": 0}
            lines = [f"{k}: {v['package']} ({v['manager']}, {v.get('version', 'latest')})"
                     for k, v in sorted(m.items())]
            return {"output": "Shared toolchain (available in every chat):\n" + "\n".join(lines),
                    "exit_code": 0}

        if not name:
            return {"error": "manage_framework: 'name' is required for this action", "exit_code": 1}

        if action in ("install", "upgrade"):
            r = toolchain.install(name, version=version, manager=manager, session_id=session_id)
            if "redirect" in r:
                return {"error": r["redirect"], "exit_code": 1}
            if "error" in r:
                return {"error": f"manage_framework: {r['error']}", "exit_code": 1}
            verb = "Upgraded" if action == "upgrade" else "Installed"
            return {"output": (f"{verb} {r['installed']} ({r['manager']}, {r['version']}) to the "
                               "shared tier — it persists across restarts and every chat can use "
                               "it. It is on PATH now."),
                    "exit_code": 0}

        if action == "remove":
            r = toolchain.remove(name, session_id=session_id)
            if "error" in r:
                return {"error": f"manage_framework: {r['error']}", "exit_code": 1}
            return {"output": f"Removed {r['removed']} ({r['manager']}) from the shared tier.",
                    "exit_code": 0}

        if action == "info":
            r = toolchain.info(name)
            return {"output": json.dumps(r, indent=2, default=str), "exit_code": 0}

        return {"error": f"manage_framework: unknown action '{action}' "
                         "(install | upgrade | remove | list | info)", "exit_code": 1}
