# YantrikDB Memory for Codex and ChatGPT

This plugin bundles the [`yantrikdb-mcp`](https://yantrikdb.com/guides/mcp/)
server and makes its memory lifecycle deterministic in hook-capable Codex and
ChatGPT Work runtimes.

## Install

```bash
codex plugin marketplace add avbel/yantrikdb-chatgpt
codex plugin add yantrikdb-chatgpt@yantrikdb-chatgpt
```

Review and trust the four bundled lifecycle hooks when Codex prompts you, then
start a new conversation so the MCP tools and hook definitions are loaded.

The MCP server already tells the model when memory is useful, but the host can
choose not to call it. These hooks cover the points where memory should not
depend on that choice:

| Event | Action |
| --- | --- |
| `SessionStart` | Inject `session_digest()` (or recent-memory fallback) and open a tracked YantrikDB session. |
| `UserPromptSubmit` | Recall against the prompt, inject unseen relevant hits, and record the redacted user turn. |
| `PreCompact` | Draft memories from the user-authored transcript tail before context is discarded. |
| `SessionEnd` | Capture anything not already watermarked, close the tracked session, and run one maintenance pass. |

The bundled MCP connection remains available for explicit `remember`, `recall`,
`correct`, `forget`, `think`, graph, conflict, task, and session calls.

## Requirements

- Python 3.10+
- `bash`
- `yantrikdb-mcp` installed in an environment the plugin can find:

```bash
pipx install yantrikdb-mcp
# or
python3 -m venv ~/.yantrikdb/venv
~/.yantrikdb/venv/bin/pip install yantrikdb-mcp
```

The plugin discovers the interpreter from `YANTRIKDB_PYTHON`, its plugin-data
cache, `~/.yantrikdb/venv`, the usual pipx installation, the
`yantrikdb-mcp` shebang, then `python3`/`python`. If none imports
`yantrikdb_mcp`, hooks silently do nothing; the MCP process will report its own
startup error separately.

Local stdio MCP and command hooks require a local hook-capable runtime. Hosted
ChatGPT web does not run a local executable; use a remotely hosted,
streamable-HTTP YantrikDB MCP package for that deployment model.

## How it shares the YantrikDB store

The hooks mirror the MCP server's backend selection:

- `YANTRIKDB_SERVER_URL` set: use the authenticated YantrikDB HTTP cluster.
- Otherwise: use the embedded database at `YANTRIKDB_DB_PATH` (default
  `~/.yantrikdb/memory.db`).

Set backend variables in the environment that launches Codex or ChatGPT so the
bundled MCP server and hooks inherit identical values. For development against
an external MCP definition, hooks can also adopt `YANTRIKDB_*` values from the
plugin `.mcp.json`. Project and user MCP configs require separate opt-ins;
explicit environment values always win.

Example:

```bash
export YANTRIKDB_DB_PATH="$HOME/.yantrikdb/memory.db"
export YANTRIKDB_EMBEDDER=bundled
export YANTRIKDB_HOOKS_NAMESPACE=auto
codex
```

After installing or changing the plugin, review and trust its hooks in Codex.
Plugin hooks are intentionally not trusted automatically.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `YANTRIKDB_HOOKS_NAMESPACE` | `default` | Memory namespace. `auto` derives it from the Git origin or project path. Keep `default` when explicit MCP calls do not pass a project namespace. |
| `YANTRIKDB_HOOKS_ADOPT_MCP_ENV` | `1` | Adopt missing `YANTRIKDB_*` values from nearby MCP configuration. |
| `YANTRIKDB_HOOKS_ADOPT_PROJECT_MCP_ENV` | `0` | Also read `<cwd>/.mcp.json` and `<cwd>/.codex/config.toml`. Enable only for trusted projects. |
| `YANTRIKDB_HOOKS_ADOPT_USER_MCP_ENV` | `0` | Also read the external `yantrikdb` entry in `~/.codex/config.toml`. |
| `YANTRIKDB_HOOKS_MCP_SERVER` | `yantrikdb` | MCP entry name used during config adoption. |
| `YANTRIKDB_HOOKS_CLIENT_ID` | derived | Tracked-session client id; defaults to `codex-<session-id>`. |
| `YANTRIKDB_HOOKS_DIGEST` | `1` | Inject the boot digest on startup, resume, and clear. |
| `YANTRIKDB_HOOKS_GAPS` | `1` | Include known gaps when supported by the HTTP backend. |
| `YANTRIKDB_HOOKS_FALLBACK` | `1` | Inject recent records when the digest is empty. |
| `YANTRIKDB_HOOKS_RECENT` | `6` | Maximum recent records in the fallback. |
| `YANTRIKDB_HOOKS_TRACK_SESSION` | `1` | Open and close a YantrikDB session. |
| `YANTRIKDB_HOOKS_RECALL` | `1` | Recall before substantive user prompts. |
| `YANTRIKDB_HOOKS_TOP_K` | `5` | Maximum recall hits per prompt. |
| `YANTRIKDB_HOOKS_MIN_SCORE` | `0.10` | Absolute score floor for injected hits. |
| `YANTRIKDB_HOOKS_MIN_PROMPT_CHARS` | `24` | Skip shorter prompts and slash commands. |
| `YANTRIKDB_HOOKS_RECORD_TURNS` | `1` | Mirror redacted user prompts into the embedded working-memory ring. |
| `YANTRIKDB_HOOKS_RING_SIZE` | `20` | Working-memory ring size. |
| `YANTRIKDB_HOOKS_CAPTURE` | `1` | Draft memories at compaction and session end. |
| `YANTRIKDB_HOOKS_CAPTURE_ROLES` | `user` | Capture `user` turns only, or `all` to include assistant text. |
| `YANTRIKDB_HOOKS_CAPTURE_TURNS` | `40` | Maximum transcript turns considered. |
| `YANTRIKDB_HOOKS_CAPTURE_CHARS` | `6000` | Maximum drafted transcript characters. |
| `YANTRIKDB_HOOKS_MAINTENANCE` | `1` | Run one bounded maintenance pass at session end. |
| `YANTRIKDB_HOOKS_REDACT` | `1` | Mask common credential shapes before storage. |
| `YANTRIKDB_HOOKS_HTTP_TIMEOUT` | `3` | Cluster health-probe and request timeout in seconds. |
| `YANTRIKDB_HOOKS_UNREACHABLE_TTL` | `60` | Cache a failed cluster probe for this many seconds. |
| `YANTRIKDB_HOOKS_TIMEOUT` | `25` | Self-deadline for fast hooks. |
| `YANTRIKDB_HOOKS_CAPTURE_TIMEOUT` | `110` | Self-deadline for capture hooks. |
| `YANTRIKDB_HOOKS_DEBUG` | `0` | Write diagnostics to stderr. |
| `YANTRIKDB_PYTHON` | unset | Explicit Python interpreter containing `yantrikdb_mcp`. |

## Safety and behavior

- Every failure path is fail-open: hooks exit successfully without protocol
  output instead of blocking the conversation.
- Recalled text is labeled as untrusted background context, not instructions.
- Capture defaults to user-authored text. Persisting assistant claims by default
  would turn guesses into future "facts."
- Codex-injected `AGENTS.md` and environment-context transcript records are
  excluded when their metadata identifies them as configuration rather than
  user text.
- Capture is watermarked per session so `PreCompact` and `SessionEnd` do not
  draft the same lines twice.
- Secret redaction is a conservative filter, not a DLP guarantee. Do not put
  secrets in prompts expecting this plugin to make that safe.
- Codex documents `transcript_path`, but the transcript file format is not a
  stable hook API. The parser is defensive and covered with representative
  Codex and compatibility fixtures.

## Development

```bash
python3 -m unittest discover -s tests -v
bash -n plugins/yantrikdb-chatgpt/hooks/run.sh
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/yantrikdb-chatgpt
```

The end-to-end test uses a temporary embedded database and skips only when no
discoverable Python installation contains `yantrikdb_mcp`.

## License

MIT
