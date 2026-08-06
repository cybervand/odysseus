"""Shared toolchain tier (doc 015) — the persistent home for frameworks.

The container FS is lava; the volume is land. This module points npm's
global prefix/cache and pip's user-base/cache at DATA_DIR/toolchain so
anything installed globally survives deploys and is visible to every chat
(same volume, same PATH). On top of that substrate: a resolver that turns
a framework NAME into the right install command (the decision models get
wrong), a manifest that records what should exist, and a boot reconciler
that reinstalls what an image bump broke.

Location is deliberately not a parameter anywhere here — the shared tier
has exactly one right place and this module owns it.
"""
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

TOOLCHAIN_DIR = Path(DATA_DIR) / "toolchain"
MANIFEST_FILE = TOOLCHAIN_DIR / "toolchain.json"
_MANIFEST_LOCK = threading.Lock()

_INSTALL_TIMEOUT_S = 300

# ── The persistent prefixes ──


def ensure_toolchain_env() -> Dict[str, str]:
    """Point npm/pip at the volume and put the tier's bins on PATH.

    Idempotent; call at app startup BEFORE any tool subprocess spawns —
    children (bash/python tools, bg_jobs, servers) inherit os.environ, so
    this one call makes even untaught `pip install` land on the volume.
    Returns the vars it set (for tests and exec-side scripts).
    """
    npm_prefix = TOOLCHAIN_DIR / "npm"
    py_base = TOOLCHAIN_DIR / "py"
    env = {
        "NPM_CONFIG_PREFIX": str(npm_prefix),
        "NPM_CONFIG_CACHE": str(TOOLCHAIN_DIR / "npm-cache"),
        "PYTHONUSERBASE": str(py_base),
        "PIP_CACHE_DIR": str(TOOLCHAIN_DIR / "pip-cache"),
    }
    for d in (npm_prefix, TOOLCHAIN_DIR / "npm-cache", py_base, TOOLCHAIN_DIR / "pip-cache"):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("toolchain: cannot create %s: %s", d, e)
    os.environ.update(env)
    # npm puts global bins in <prefix>/bin on POSIX and <prefix> on Windows;
    # pip --user puts them in <base>/bin (POSIX) / <base>/Scripts (Windows).
    bin_dirs = [npm_prefix / "bin", npm_prefix, py_base / "bin", py_base / "Scripts"]
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    for b in bin_dirs:
        if str(b) not in path_parts:
            path_parts.insert(0, str(b))
    os.environ["PATH"] = os.pathsep.join(path_parts)
    env["PATH"] = os.environ["PATH"]
    return env


# ── The resolver ──
#
# KNOWN maps a friendly name to how it actually installs. `redirect`
# entries are things models ASK for globally that are really project deps
# — the honest answer is teaching, not an install.

KNOWN: Dict[str, Dict[str, str]] = {
    "vite":         {"manager": "npm", "package": "vite", "bin": "vite"},
    "create-vite":  {"manager": "npm", "package": "create-vite", "bin": "create-vite"},
    "tailwind":     {"manager": "npm", "package": "tailwindcss", "bin": "tailwindcss"},
    "tailwindcss":  {"manager": "npm", "package": "tailwindcss", "bin": "tailwindcss"},
    "typescript":   {"manager": "npm", "package": "typescript", "bin": "tsc"},
    "sass":         {"manager": "npm", "package": "sass", "bin": "sass"},
    "serve":        {"manager": "npm", "package": "serve", "bin": "serve"},
    "degit":        {"manager": "npm", "package": "degit", "bin": "degit"},
    "prettier":     {"manager": "npm", "package": "prettier", "bin": "prettier"},
    "eslint":       {"manager": "npm", "package": "eslint", "bin": "eslint"},
    "flask":        {"manager": "pip", "package": "flask", "bin": "flask"},
    "fastapi":      {"manager": "pip", "package": "fastapi"},
    "uvicorn":      {"manager": "pip", "package": "uvicorn", "bin": "uvicorn"},
    "gunicorn":     {"manager": "pip", "package": "gunicorn", "bin": "gunicorn"},
    "django":       {"manager": "pip", "package": "django", "bin": "django-admin"},
    "requests":     {"manager": "pip", "package": "requests"},
    "pillow":       {"manager": "pip", "package": "pillow"},
    "pandas":       {"manager": "pip", "package": "pandas"},
    "numpy":        {"manager": "pip", "package": "numpy"},
    # Project deps, not global tools — redirect instead of installing.
    "react":     {"redirect": "react is a PROJECT dependency — run `npm install react react-dom` inside your project folder (bash), not manage_framework."},
    "react-dom": {"redirect": "react-dom is a PROJECT dependency — `npm install react react-dom` inside your project folder."},
    "vue":       {"redirect": "vue is a PROJECT dependency — `npm install vue` inside your project folder (or scaffold with `npm create vue@latest`)."},
    "svelte":    {"redirect": "svelte is a PROJECT dependency — scaffold with `npm create vite@latest myapp -- --template svelte` and it arrives with the project."},
    "next":      {"redirect": "next is a PROJECT dependency — `npx create-next-app` scaffolds a project that carries its own copy."},
    "nextjs":    {"redirect": "next is a PROJECT dependency — `npx create-next-app` scaffolds a project that carries its own copy."},
}


def resolve(name: str, manager: Optional[str] = None) -> Dict[str, Any]:
    """Turn a framework name into an install spec, or an honest error.

    Known names resolve alone. Unknown names REQUIRE an explicit manager
    (npm|pip) — cross-registry name collisions and typosquats make silent
    guessing a supply-chain hazard, and the refusal message teaches the fix.
    """
    key = (name or "").strip().lower()
    if not key:
        return {"error": "framework name is required"}
    known = KNOWN.get(key)
    if known and "redirect" in known:
        return {"redirect": known["redirect"]}
    if known:
        spec = dict(known)
        if manager and manager != spec["manager"]:
            spec["manager"] = manager  # explicit model choice wins, honestly logged
            logger.info("toolchain: manager override %s for known '%s'", manager, key)
        return spec
    if manager in ("npm", "pip"):
        return {"manager": manager, "package": key}
    return {
        "error": (
            f"'{name}' is not in the known framework set, so I need to know its "
            'package manager: resend with "manager": "npm" or "manager": "pip". '
            "Exact package name matters — a typo installs someone else's package."
        )
    }


# ── Manifest ──


def _load_manifest() -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(m: Dict[str, Dict[str, Any]]) -> None:
    TOOLCHAIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_FILE)


def manifest_list() -> Dict[str, Dict[str, Any]]:
    with _MANIFEST_LOCK:
        return _load_manifest()


def _record(name: str, spec: Dict[str, Any], version: Optional[str], session_id: str) -> None:
    with _MANIFEST_LOCK:
        m = _load_manifest()
        m[name] = {
            "manager": spec["manager"],
            "package": spec["package"],
            "version": version or "latest",
            "bin": spec.get("bin"),
            "by_session": session_id,
            "at": time.time(),
        }
        _save_manifest(m)


def _unrecord(name: str) -> bool:
    with _MANIFEST_LOCK:
        m = _load_manifest()
        if name not in m:
            return False
        del m[name]
        _save_manifest(m)
        return True


# ── Install / remove / verify ──


def _run(cmd: List[str]) -> Dict[str, Any]:
    """Run an install-tier command with the toolchain env. Never raises."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_S,
            env=os.environ.copy(),
        )
        return {"rc": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "out": f"timed out after {_INSTALL_TIMEOUT_S}s"}
    except FileNotFoundError as e:
        return {"rc": -1, "out": str(e)}


def _install_cmd(spec: Dict[str, Any], version: Optional[str]) -> List[str]:
    pkg = spec["package"]
    if spec["manager"] == "npm":
        target = f"{pkg}@{version}" if version else f"{pkg}@latest"
        return ["npm", "install", "-g", target]
    target = f"{pkg}=={version}" if version else pkg
    cmd = ["pip", "install", "--user", target]
    if not version:
        cmd.insert(2, "--upgrade")
    return cmd


def _verify(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Post-install proof: the bin answers, or the package is importable/listed."""
    b = spec.get("bin")
    if b:
        path = shutil.which(b)
        if not path:
            return {"ok": False, "detail": f"'{b}' not on PATH after install"}
        v = _run([b, "--version"])
        ver = (v["out"] or "").strip().splitlines()[0] if v["out"] else ""
        return {"ok": v["rc"] == 0, "detail": ver or path}
    if spec["manager"] == "pip":
        r = _run(["pip", "show", spec["package"]])
        for line in (r["out"] or "").splitlines():
            if line.lower().startswith("version:"):
                return {"ok": r["rc"] == 0, "detail": line.split(":", 1)[1].strip()}
        return {"ok": r["rc"] == 0, "detail": ""}
    r = _run(["npm", "ls", "-g", "--depth=0", spec["package"]])
    return {"ok": r["rc"] == 0, "detail": (r["out"] or "").strip()[-200:]}


def install(name: str, version: Optional[str] = None, manager: Optional[str] = None,
            session_id: str = "") -> Dict[str, Any]:
    """Resolve → install to the persistent tier → verify → record."""
    spec = resolve(name, manager)
    if "error" in spec or "redirect" in spec:
        return spec
    ensure_toolchain_env()
    r = _run(_install_cmd(spec, version))
    if r["rc"] != 0:
        return {"error": f"install failed (rc={r['rc']}): {r['out'][-800:]}"}
    check = _verify(spec)
    if not check["ok"]:
        return {"error": f"installed but verification failed: {check['detail']}"}
    # Manifest key is the CANONICAL package, never the alias — otherwise
    # "tailwind" and "tailwindcss" double-record and the context line lies.
    _record(spec["package"], spec, version, session_id)
    logger.info("toolchain: installed %s (%s/%s) session=%s",
                name, spec["manager"], spec["package"], session_id)
    return {"installed": spec["package"], "manager": spec["manager"],
            "version": check["detail"] or (version or "latest")}


def remove(name: str, session_id: str = "") -> Dict[str, Any]:
    key = (name or "").strip().lower()
    known = KNOWN.get(key)
    if known and "package" in known:
        key = known["package"]          # alias → canonical manifest key
    entry = manifest_list().get(key)
    spec = entry or known
    if not spec or "redirect" in spec:
        return {"error": f"unknown framework '{name}' — nothing recorded to remove"}
    ensure_toolchain_env()
    if spec["manager"] == "npm":
        r = _run(["npm", "uninstall", "-g", spec["package"]])
    else:
        r = _run(["pip", "uninstall", "-y", spec["package"]])
    _unrecord(key)
    if r["rc"] != 0:
        return {"error": f"uninstall reported rc={r['rc']}: {r['out'][-400:]}"}
    logger.info("toolchain: removed %s session=%s", key, session_id)
    return {"removed": spec["package"], "manager": spec["manager"]}


def info(name: str) -> Dict[str, Any]:
    key = (name or "").strip().lower()
    spec = resolve(key)
    entry = manifest_list().get(spec.get("package", key))
    out: Dict[str, Any] = {"name": key}
    if "redirect" in spec:
        out["note"] = spec["redirect"]
        return out
    if "error" not in spec:
        out.update({"manager": spec["manager"], "package": spec["package"]})
        out["installed"] = _verify(spec)
    if entry:
        out["manifest"] = entry
    return out


# ── Context line + boot reconciler ──


def context_line() -> str:
    """One line for the agent context: what the shared tier already has.
    Empty string when nothing is installed (no noise for fresh installs)."""
    m = manifest_list()
    if not m:
        return ""
    parts = []
    for name, entry in sorted(m.items()):
        v = entry.get("version") or ""
        parts.append(f"{name} {v}".strip() if v not in ("", "latest") else name)
    return ("Shared toolchain (already installed, do NOT reinstall): "
            + ", ".join(parts)
            + ". Need another framework everywhere? manage_framework. "
            "Project-local deps: plain npm install in the project.")


def reconcile() -> Dict[str, Any]:
    """Reinstall manifest entries the image swap broke. Run at boot, in a
    thread — never blocks startup, never raises."""
    ensure_toolchain_env()
    results = {"ok": [], "reinstalled": [], "failed": []}
    for name, entry in manifest_list().items():
        spec = {"manager": entry["manager"], "package": entry["package"], "bin": entry.get("bin")}
        try:
            if _verify(spec)["ok"]:
                results["ok"].append(name)
                continue
            version = entry.get("version")
            r = _run(_install_cmd(spec, None if version in (None, "latest") else version))
            if r["rc"] == 0 and _verify(spec)["ok"]:
                results["reinstalled"].append(name)
            else:
                results["failed"].append(name)
        except Exception as e:  # a broken entry must not sink the rest
            logger.warning("toolchain reconcile: %s failed: %s", name, e)
            results["failed"].append(name)
    if results["reinstalled"] or results["failed"]:
        logger.info("toolchain reconcile: %s", results)
    return results


def start_reconciler() -> None:
    t = threading.Thread(target=reconcile, name="toolchain-reconcile", daemon=True)
    t.start()
