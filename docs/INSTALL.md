# Install

Per-client setup for `second-brain-mcp`. The server speaks two
transports — **stdio** (default, used by `claude mcp add` and
subprocess-style MCP clients) and **streamable HTTP** (for hosting
the server on a remote machine). Client registration is the same
shape either way; only the `command` / `url` changes.

---

## Prerequisites

- **Python 3.10+**.
- **`uvx`** — recommended way to run the package without polluting your
  global Python environment. Install with `brew install uv` on macOS, or
  follow the [uv docs](https://docs.astral.sh/uv/) for other platforms.
- **An Obsidian vault** — any directory with `.md` files works. If you
  don't have one yet, copy the included `template-vault/` to a location
  you like.
- **Disk space** — roughly 3 GB available for the bge-m3 model on first
  run (cached under `~/.cache/huggingface/`). Lighter models are
  available; see [CUSTOMIZE.md](./CUSTOMIZE.md).

---

## Claude Code

Register the server in user scope so it is visible from every Claude Code
session:

```bash
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$HOME/obsidian/vault" \
  -- uvx second-brain-mcp serve
claude mcp list   # expect: second-brain - ✓ Connected
```

**You must restart Claude Code to see the new tools.** MCP servers attach
at session start. An agent that runs `claude mcp add` inside its own
session will not see the new tools in that same session — the MCP client
inside the running `claude` process was already attached to its server
list at startup.

When a Claude Code session installs the server for you, the agent should
hand off to you with a message along these lines:

> Installation complete. To test the setup end-to-end:
>
> 1. **Close this Claude Code session** and start a new one (a fresh
>    `claude` process).
> 2. In the new session ask the agent: *"List the tools from
>    second-brain, then call obsidian_overview."* Expected: the agent
>    lists the five tools (`obsidian_overview`, `obsidian_search`,
>    `obsidian_read`, `obsidian_backlinks`, `obsidian_write`) and
>    `obsidian_overview` returns vault stats plus the contents of
>    `_index.md`.
> 3. Next ask: *"Search my vault for [a topic you know you've written
>    about]."* Expected: the agent calls `obsidian_search`, returns
>    relevant hits, then opens one with `obsidian_read`.
> 4. If the tools are **not** visible in the new session, the
>    `claude mcp add` step never wrote the config. Run
>    `claude mcp list` in the terminal — if `second-brain` is missing or
>    shows `✗ Failed`, see [TROUBLESHOOT.md](./TROUBLESHOOT.md).

The agent that ran the install cannot verify the tools in its own
session. That is a lifecycle property of MCP clients, not a bug in this
package.

---

## Cursor

Add an entry to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "uvx",
      "args": ["second-brain-mcp", "serve"],
      "env": {
        "OBSIDIAN_VAULT": "/absolute/path/to/vault"
      }
    }
  }
}
```

Restart Cursor. The tools appear under the MCP menu.

---

## Zed

Zed follows the same stdio MCP contract. Configure under Zed's MCP
settings — the command is `uvx` with arguments `second-brain-mcp serve`
and the `OBSIDIAN_VAULT` env var. Refer to the current
[Zed docs](https://zed.dev/docs) for the exact config key, which is the
only moving part between Zed releases.

---

## Generic MCP client

Any stdio-capable MCP client works. The command template is:

```
command: uvx
args:    ["second-brain-mcp", "serve"]
env:
  OBSIDIAN_VAULT: "/absolute/path/to/vault"
  # optional:
  # OBSIDIAN_INDEX_DIR: "/custom/index/dir"
  # OBSIDIAN_EMBED_MODEL: "BAAI/bge-m3"
  # OBSIDIAN_EMBED_DEVICE: "mps"   # mps | cuda | cpu
```

---

## Remote / HTTP mode

When you want the server on a different machine from the agent — a VM,
a shared workstation, a homelab box — use the streamable-HTTP
transport instead of stdio.

### On the server host

```bash
export OBSIDIAN_VAULT=$HOME/obsidian/vault
export OBSIDIAN_HTTP_TOKEN=$(openssl rand -hex 32)   # required for non-loopback binds

# Foreground:
uvx second-brain-mcp serve \
  --transport http \
  --host 0.0.0.0 \
  --port 8765

# Or systemd-managed: put the same command in a user unit and
# `systemctl --user enable --now second-brain-mcp`.
```

Safety rail: the server refuses to start on a non-loopback host
without `OBSIDIAN_HTTP_TOKEN` set. You'll see a loud error and a
non-zero exit rather than a quietly open port.

### On the client

Claude Code:

```bash
claude mcp add --transport http second-brain \
  https://vm.example.com:8765/mcp \
  --header "Authorization: Bearer $OBSIDIAN_HTTP_TOKEN"
```

Cursor / Zed: add an HTTP MCP entry with the same URL and
`Authorization` header — consult your client's MCP docs for the exact
config shape.

### Single-user tunnel (no public port)

If the server is behind a firewall and you just want your own laptop
to reach it, skip the public bind and use SSH port forwarding:

```bash
# On the laptop
ssh -L 8765:127.0.0.1:8765 user@vm

# On the VM (started from the SSH session or beforehand)
uvx second-brain-mcp serve --transport http --host 127.0.0.1 --port 8765

# On the laptop (in a separate shell)
claude mcp add --transport http second-brain http://127.0.0.1:8765/mcp
```

Loopback-only binds don't require `OBSIDIAN_HTTP_TOKEN`; the SSH
tunnel is the auth. Terminate TLS in front with nginx / caddy if you
expose the port publicly — uvicorn can serve TLS directly but the
integration is outside what this package wires for you.

Env vars that configure the HTTP transport:
`OBSIDIAN_MCP_TRANSPORT` (`stdio` | `http`), `OBSIDIAN_MCP_HOST`,
`OBSIDIAN_MCP_PORT`, `OBSIDIAN_MCP_PATH`, `OBSIDIAN_HTTP_TOKEN`.

---

## Verify end-to-end

Confirm the chain works at each layer:

1. **CLI search directly through the indexer** (bypasses MCP):

   ```bash
   OBSIDIAN_VAULT=$HOME/obsidian/vault \
     uvx second-brain-mcp search "any familiar query" --n 3
   ```

   You should see 3 hits with `similarity`, `title`, `rel`, and `snippet`.

2. **MCP health check** (Claude Code):

   ```bash
   claude mcp list
   ```

   Expected: `second-brain: ... - ✓ Connected`.

3. **End-to-end through a new session.**

   This step is performed by **the user**, not by the agent that installed
   the server. The installing agent cannot see newly-registered tools in
   its own session — MCP clients attach at session start.

   In a new session:

   1. Ask the agent to *"list the tools from second-brain, then call
      `obsidian_overview`"*. Expected: five tools listed
      (`obsidian_overview`, `obsidian_search`, `obsidian_read`,
      `obsidian_backlinks`, `obsidian_write`), overview returns vault
      stats plus the contents of `_index.md` (or a placeholder if you
      don't have one yet).
   2. Ask the agent to *"search my vault for [a topic you know is in
      there]"*. Expected: `obsidian_search` is called, returns relevant
      hits, and the agent reads one through `obsidian_read`.
   3. If no tools appear, run `claude mcp list`. If `second-brain` is
      missing or failed, see [TROUBLESHOOT.md](./TROUBLESHOOT.md).

---

## Uninstall

```bash
claude mcp remove second-brain
rm -rf $OBSIDIAN_INDEX_DIR   # default ~/.second-brain-mcp/
# optionally free ~2.3 GB of HuggingFace cache:
rm -rf ~/.cache/huggingface/hub/models--BAAI--bge-m3
```

**Your vault is untouched.** Nothing in `$OBSIDIAN_VAULT` is ever modified
by this package.
