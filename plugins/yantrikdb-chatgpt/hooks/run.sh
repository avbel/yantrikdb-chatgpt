#!/usr/bin/env bash
# Resolve the Python installation that owns yantrikdb-mcp, then run a plugin hook.
# Missing dependencies and lookup failures are intentional no-ops: memory must
# never make a Codex session unavailable.

set -uo pipefail

script="${1:-}"
case "$script" in
  session_start.py|user_prompt_submit.py|capture.py) ;;
  *) exit 0 ;;
esac
shift || true

data_dir="${PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-$HOME/.yantrikdb/codex-hooks}}"
cache="$data_dir/interpreter"

ok() {
  [ -n "${1:-}" ] && [ -x "$1" ] && "$1" -c 'import yantrikdb_mcp' >/dev/null 2>&1
}

py=""
if [ -n "${YANTRIKDB_PYTHON:-}" ] && [ -x "$YANTRIKDB_PYTHON" ]; then
  py="$YANTRIKDB_PYTHON"
elif [ -r "$cache" ]; then
  cached="$(head -n 1 "$cache" 2>/dev/null || true)"
  [ -n "$cached" ] && [ -x "$cached" ] && py="$cached"
fi

if [ -z "$py" ]; then
  for candidate in \
    "$HOME/.yantrikdb/venv/bin/python" \
    "$HOME/.yantrikdb/venv/bin/python3" \
    "$HOME/.local/pipx/venvs/yantrikdb-mcp/bin/python"; do
    if ok "$candidate"; then
      py="$candidate"
      break
    fi
  done

  if [ -z "$py" ]; then
    mcp_bin="$(command -v yantrikdb-mcp 2>/dev/null || true)"
    [ -n "$mcp_bin" ] || mcp_bin="$HOME/.local/bin/yantrikdb-mcp"
    if [ -r "$mcp_bin" ]; then
      shebang="$(head -c 256 "$mcp_bin" 2>/dev/null | head -n 1 | sed -n 's|^#!\([^ ]*\).*|\1|p')"
      ok "$shebang" && py="$shebang"
    fi
  fi

  if [ -z "$py" ]; then
    for candidate in python3 python; do
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
      if ok "$resolved"; then
        py="$resolved"
        break
      fi
    done
  fi

  if [ -n "$py" ]; then
    mkdir -p "$data_dir" 2>/dev/null || true
    printf '%s' "$py" > "$cache" 2>/dev/null || true
  fi
fi

[ -n "$py" ] || exit 0
exec "$py" "$(dirname "${BASH_SOURCE[0]}")/$script" "$@"
