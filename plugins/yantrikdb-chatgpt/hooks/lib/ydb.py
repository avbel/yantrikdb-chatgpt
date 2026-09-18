"""Shared, fail-open runtime for the YantrikDB plugin hooks."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr


def emit(payload: dict | None = None) -> None:
    """Write the only protocol output produced by a hook, then exit cleanly."""
    if payload:
        _REAL_STDOUT.write(json.dumps(payload))
        _REAL_STDOUT.flush()
    _REAL_STDOUT.close()
    os._exit(0)


def emit_context(event: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        emit()
    emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (AttributeError, TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except (AttributeError, TypeError, ValueError):
        return default


_ADOPTABLE_PREFIX = "YANTRIKDB_"


def mcp_env_from_json(path: Path, server: str) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
        entry = (data.get("mcpServers") or {}).get(server) or {}
        env = entry.get("env") or {}
    except Exception:
        return {}
    if not isinstance(env, dict):
        return {}
    return {
        key: os.path.expandvars(str(value))
        for key, value in env.items()
        if isinstance(key, str) and key.startswith(_ADOPTABLE_PREFIX)
    }


def mcp_env_from_toml(path: Path, server: str) -> dict[str, str]:
    try:
        import tomllib

        data = tomllib.loads(path.read_text())
        entry = (data.get("mcp_servers") or {}).get(server) or {}
        env = entry.get("env") or {}
    except Exception:
        return {}
    if not isinstance(env, dict):
        return {}
    return {
        key: os.path.expandvars(str(value))
        for key, value in env.items()
        if isinstance(key, str) and key.startswith(_ADOPTABLE_PREFIX)
    }


def adopt_mcp_env(cwd: str | None) -> None:
    """Adopt YantrikDB settings from nearby MCP definitions when available.

    Explicit process variables always win. The bundled server normally shares
    the Codex process environment. Project-local definitions are opt-in because
    a repository must not be able to redirect globally installed memory hooks.
    """
    if not env_flag("YANTRIKDB_HOOKS_ADOPT_MCP_ENV", True):
        return
    server = os.environ.get("YANTRIKDB_HOOKS_MCP_SERVER", "").strip() or "yantrikdb"
    plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    sources: list[tuple[Path, object]] = []
    if plugin_root:
        sources.append((Path(plugin_root) / ".mcp.json", mcp_env_from_json))
    if cwd and env_flag("YANTRIKDB_HOOKS_ADOPT_PROJECT_MCP_ENV", False):
        root = Path(cwd)
        sources.extend(
            [
                (root / ".mcp.json", mcp_env_from_json),
                (root / ".codex" / "config.toml", mcp_env_from_toml),
            ]
        )
    if env_flag("YANTRIKDB_HOOKS_ADOPT_USER_MCP_ENV", False):
        sources.append((Path.home() / ".codex" / "config.toml", mcp_env_from_toml))

    for path, reader in sources:
        found = reader(path, server)  # type: ignore[operator]
        if not found:
            continue
        adopted: list[str] = []
        for key, value in found.items():
            if key not in os.environ:
                os.environ[key] = value
                adopted.append(key)
        log(f"MCP env from {path}: found {sorted(found)}, adopted {sorted(adopted)}")
        return


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.").lower()


def _git_remote_name(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    url = (result.stdout or "").strip()
    if result.returncode or not url:
        return ""
    tail = re.split(r"[/:]", url.rstrip("/"))[-1]
    return _slug(tail[:-4] if tail.endswith(".git") else tail)


def namespace_for(cwd: str | None) -> str:
    namespace = os.environ.get("YANTRIKDB_HOOKS_NAMESPACE", "default").strip() or "default"
    if namespace != "auto":
        return namespace
    root = Path(cwd or os.getcwd())
    remote = _git_remote_name(root)
    if remote:
        return remote
    with contextlib.suppress(Exception):
        root = root.resolve()
    digest = hashlib.sha1(str(root).encode()).hexdigest()[:6]
    return f"{_slug(root.name) or 'project'}-{digest}"


def client_id_for(session_id: str | None) -> str:
    explicit = os.environ.get("YANTRIKDB_HOOKS_CLIENT_ID", "").strip()
    if explicit:
        return explicit
    session = _slug(session_id or "")[:48]
    return f"codex-{session}" if session else "codex"


_MARKER = "unreachable.json"
_INTERPRETER = "interpreter"


def state_dir() -> Path:
    root = (
        os.environ.get("PLUGIN_DATA")
        or os.environ.get("CLAUDE_PLUGIN_DATA")
        or str(Path.home() / ".yantrikdb" / "codex-hooks")
    )
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(session_id: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", session_id or "unknown")[:64]
    return state_dir() / f"{slug}.json"


def read_state(session_id: str) -> dict:
    try:
        value = json.loads(state_path(session_id).read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def write_state(session_id: str, **fields) -> None:
    try:
        state = read_state(session_id)
        state.update(fields)
        target = state_path(session_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(target)
    except Exception:
        pass


def drop_state(session_id: str) -> None:
    with contextlib.suppress(Exception):
        state_path(session_id).unlink()


def sweep_state() -> None:
    cutoff = time.time() - env_int("YANTRIKDB_HOOKS_STATE_MAX_AGE_DAYS", 7) * 86400
    try:
        for path in state_dir().glob("*.json"):
            if path.name == _MARKER:
                continue
            with contextlib.suppress(Exception):
                if path.stat().st_mtime < cutoff:
                    path.unlink()
    except Exception:
        pass


def merge_rids(seen: list, fresh: list, cap: int = 400) -> list:
    merged: list = []
    for rid in [*(seen or []), *(fresh or [])]:
        if rid and rid not in merged:
            merged.append(rid)
    return merged[-cap:]


def unreachable_marker_path() -> Path:
    return state_dir() / _MARKER


def cluster_marked_down(url: str) -> bool:
    try:
        marker = json.loads(unreachable_marker_path().read_text())
        return marker.get("url") == url and float(marker.get("until", 0)) > time.time()
    except Exception:
        return False


def mark_cluster_down(url: str) -> None:
    ttl = max(1, env_int("YANTRIKDB_HOOKS_UNREACHABLE_TTL", 60))
    with contextlib.suppress(Exception):
        unreachable_marker_path().write_text(
            json.dumps({"url": url, "until": time.time() + ttl})
        )


def _probe_cluster(nodes: list[str], token: str, timeout: float) -> bool:
    import requests

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for node in nodes:
        try:
            if requests.get(f"{node}/v1/health", headers=headers, timeout=timeout).ok:
                return True
        except Exception:
            continue
    return False


def read_event() -> dict:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw) if raw.strip() else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _evict_interpreter_cache() -> None:
    with contextlib.suppress(Exception):
        (state_dir() / _INTERPRETER).unlink()


def open_db():
    try:
        server_url = os.environ.get("YANTRIKDB_SERVER_URL", "").strip()
        return _open_http(server_url) if server_url else _open_embedded()
    except ModuleNotFoundError as error:
        if (error.name or "").startswith("yantrikdb"):
            _evict_interpreter_cache()
        log(f"engine unavailable: {error}")
    except Exception as error:
        log(f"engine unavailable: {error}")
    return None


def _open_http(server_url: str):
    if cluster_marked_down(server_url):
        log("cluster marked unreachable, skipping")
        return None
    from yantrikdb_mcp.http_backend import HttpBackend

    nodes = [url.strip().rstrip("/") for url in server_url.split(",") if url.strip()]
    token = os.environ.get("YANTRIKDB_TOKEN", "")
    timeout = max(1, env_int("YANTRIKDB_HOOKS_HTTP_TIMEOUT", 3))
    if not _probe_cluster(nodes, token, timeout):
        mark_cluster_down(server_url)
        log(f"cluster unreachable: {server_url}")
        return None
    return HttpBackend(server_urls=nodes, token=token, timeout=timeout)


def _open_embedded():
    from yantrikdb_mcp.embedder import load_engine

    db_path = os.environ.get(
        "YANTRIKDB_DB_PATH", str(Path.home() / ".yantrikdb" / "memory.db")
    )
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("YANTRIKDB_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return load_engine(db_path, model_name=model)
        except ModuleNotFoundError:
            raise
        except Exception as error:
            last_error = error
            time.sleep(0.4 * (attempt + 1))
    assert last_error is not None
    raise last_error


def is_http(db) -> bool:
    return type(db).__name__ == "HttpBackend"


def close_db(db) -> None:
    with contextlib.suppress(Exception):
        db.close()


def as_obj(value) -> dict:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def as_id(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("{"):
            value = as_obj(value)
        else:
            return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return str(value.get("session_id") or value.get("id") or "")
    return str(getattr(value, "session_id", "") or getattr(value, "id", ""))


def flex(function, **kwargs):
    """Retry after removing keyword arguments rejected by older engines."""
    remaining = dict(kwargs)
    for _ in range(len(remaining) + 1):
        try:
            return function(**remaining)
        except TypeError as error:
            match = re.search(r"unexpected keyword argument ['\"]([^'\"]+)['\"]", str(error))
            if not match or match.group(1) not in remaining:
                raise
            log(f"dropping unsupported kwarg {match.group(1)}")
            remaining.pop(match.group(1))
    return function()


def is_weak(why) -> str:
    markers = ("aged", "rarely confirmed", "superseded", "stale", "disputed")
    items = why if isinstance(why, (list, tuple)) else [why]
    for item in items:
        text = " ".join(str(item).split())
        if any(marker in text.lower() for marker in markers):
            return text[:80]
    return ""


def recent_records(db, namespace: str, limit: int) -> tuple[list, str]:
    namespace_arg = None if namespace == "default" else namespace
    try:
        rows = flex(db.list_memories, limit=limit, namespace=namespace_arg)
        rows = rows.get("memories", []) if isinstance(rows, dict) else (rows or [])
        return list(rows), "most recent records"
    except Exception as error:
        log(f"list_memories failed: {error}")
    try:
        rows = flex(
            db.recall,
            query="recent decisions, preferences and project context",
            top_k=limit,
            namespace=namespace_arg,
            expand_entities=True,
        )
        return list(rows or []), "most relevant records"
    except Exception as error:
        log(f"fallback recall failed: {error}")
    return [], ""


def log(message: str) -> None:
    if env_flag("YANTRIKDB_HOOKS_DEBUG", False):
        sys.stderr.write(f"[yantrikdb-hooks] {message}\n")


def guard(seconds: int) -> None:
    def bail(_signal, _frame):
        os._exit(0)

    with contextlib.suppress(Exception):
        signal.signal(signal.SIGALRM, bail)
        signal.alarm(max(1, seconds))


def run(function) -> None:
    try:
        function()
    except SystemExit:
        raise
    except BaseException as error:
        log(f"hook failed: {type(error).__name__}: {error}")
    emit()
