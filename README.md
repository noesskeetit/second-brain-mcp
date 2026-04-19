# second-brain-mcp

[![PyPI version](https://img.shields.io/pypi/v/second-brain-mcp.svg)](https://pypi.org/project/second-brain-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/second-brain-mcp.svg)](https://pypi.org/project/second-brain-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/noesskeetit/second-brain-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/noesskeetit/second-brain-mcp/actions/workflows/ci.yml)

Turn your Obsidian vault into semantic memory for any MCP-capable coding agent.

> **v1.0.0 — early release.** Works end-to-end on macOS and Linux; published on PyPI on 2026-04-15. Windows is untested. Feedback, bug reports, and testing notes are very welcome — please [open an issue](https://github.com/noesskeetit/second-brain-mcp/issues) if anything misbehaves or if the docs are unclear.

**What it does.** Ships an MCP server with five tools:
four read tools (`obsidian_overview`, `obsidian_search`, `obsidian_read`,
`obsidian_backlinks`) and one flexible write tool (`obsidian_write` —
create / append / prepend / replace_body / replace_text / set_frontmatter
/ delete / rename, one `op` field picks the mutation). Works with
Claude Code, Cursor, Zed, or any client that speaks MCP. Runs on stdio
by default, or on streamable HTTP when you want to host it on a remote
VM and connect across the network.

**Editorial, not archival.** Writes are allowed, but the tool is small
and deliberate, not a compaction loop. Nothing is captured automatically
from your session — the agent only writes when you tell it to, and it
is prompted to check for duplicates and prefer small ops (bump a
frontmatter date, append an addendum) over rewriting whole notes. The
vault stays dense and curated; the agent stays a guest, not a gardener.

**How this is different from other Obsidian MCP servers.** Existing
Obsidian MCP servers (e.g. variants of `mcp-obsidian`) typically talk
to the running Obsidian app through its Local-REST plugin and expose
file-level tools — `list_files`, `get_file`, `append_to_note`, etc.
`second-brain-mcp` is offline and plugin-free: it reads the vault as
plain files from disk, builds a local semantic index with bge-m3, and
exposes **semantic search** first. Obsidian does not need to be running.
The write path is one dispatcher tool with atomic per-op semantics,
not a sprawl of per-action tools.

## 30-second quick start

```bash
# 1. Install (uvx — no venv pollution)
uvx second-brain-mcp serve --help

# 2. Point at your vault
export OBSIDIAN_VAULT=$HOME/obsidian/vault

# 3. Register with Claude Code
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$OBSIDIAN_VAULT" \
  -- uvx second-brain-mcp serve

# 4. Restart Claude Code, then ask: "call obsidian_overview"
```

First run downloads the bge-m3 embedder (~2.3 GB) on the first tool call
— roughly 5 seconds after that. See [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md)
for lighter models, or to point at an OpenAI-compatible embeddings API
(Cloud.ru FM API, OpenAI, self-hosted Infinity) instead of the local
model.

## Remote mode (streamable HTTP)

Host the server on a VM and connect your local MCP client over HTTP. The
same process, just a different transport.

```bash
# On the VM — bind to 0.0.0.0 and require a Bearer token
export OBSIDIAN_VAULT=$HOME/obsidian/vault
export OBSIDIAN_HTTP_TOKEN=$(openssl rand -hex 32)
uvx second-brain-mcp serve --transport http --host 0.0.0.0 --port 8765

# On your laptop — register as a remote MCP
claude mcp add --transport http second-brain \
  https://vm.example.com:8765/mcp \
  --header "Authorization: Bearer $OBSIDIAN_HTTP_TOKEN"
```

The server refuses to bind to a non-loopback host without
`OBSIDIAN_HTTP_TOKEN` set — no quietly open ports. For loopback
(`--host 127.0.0.1`) the token is optional; combine with an SSH tunnel
for remote use. Terminate TLS in front with nginx/caddy for anything
beyond a trusted network.

Env vars: `OBSIDIAN_MCP_TRANSPORT`, `OBSIDIAN_MCP_HOST`, `OBSIDIAN_MCP_PORT`,
`OBSIDIAN_MCP_PATH`, `OBSIDIAN_HTTP_TOKEN`.

## The `obsidian_write` tool

One tool, many ops — pick with the `op` field:

| `op` | use for |
|---|---|
| `create` | new note (fails on collision unless `overwrite=true`) |
| `append` / `prepend` | insert text at the end / start of a note's body |
| `replace_body` | swap the whole body, keep frontmatter |
| `replace_text` | literal or regex find/replace inside a note's body |
| `set_frontmatter` | merge / remove frontmatter keys without touching body |
| `delete` | delete a note |
| `rename` | move/rename a note (does NOT rewrite wikilinks elsewhere) |

Every op:
- takes a vault-relative `path`, path-traversal guarded,
- supports `dry_run=true` → returns `{before, after}` without touching disk,
- writes atomically (tmp + `os.replace`) so a crash never leaves half files,
- triggers an incremental reindex on success, so search reflects the edit
  immediately.

The tool description itself nudges the model toward small, targeted ops
over whole-note rewrites, and toward `obsidian_search` before `create` to
avoid duplicates.

## Vault requirements

**Hard minimum:** a directory with `.md` files somewhere (any nesting).

Everything else is optional:
- YAML frontmatter (`type`, `verified`, `confidence`) enables filtering
- `[[wikilinks]]` enable backlinks navigation
- `_index.md` at the vault root is returned whole in `obsidian_overview`

Start with your existing vault — unused features simply stay inactive
until you add the relevant structure.

| Feature                            | No frontmatter | No wikilinks | No `_index.md` |
|------------------------------------|:--------------:|:------------:|:--------------:|
| semantic search                    |       ✅        |      ✅       |       ✅        |
| `type_filter` in search            |       ❌        |      ✅       |       ✅        |
| `obsidian_read` body               |       ✅        |      ✅       |       ✅        |
| `obsidian_read` frontmatter        |   empty dict   |      ✅       |       ✅        |
| `obsidian_read` outlinks/backlinks |       ✅        |    empty     |       ✅        |
| `obsidian_backlinks` tool          |       ✅        |    empty     |       ✅        |
| `obsidian_overview` index_md       |       ✅        |      ✅       |  placeholder   |

## Why editorial, not archival

Most agent-memory systems default to the **archival** model: capture
everything — raw conversation turns, every tool call, every message —
then rely on semantic search to pull the right thing back later.
Comparative retrieval tests against one such system (MemPalace, with
its exchange-pair chunking and multi-layer palace) surfaced a clear
trade-off: on realistic queries a small set of human-approved notes
outperformed a much larger raw conversation archive sitting in the
same index.

The reason is simple. In any given session roughly 95% of what's said
is working noise — code, syntactic back-and-forth, tactical detail
that expires with the task. The 5% that survives — atomic facts,
decisions, insights — is what you actually want to find six months
later. Archival memory keeps both and leans on the embedder to
separate them, and that separation is hard to get right in practice.

`second-brain-mcp` takes the **editorial** position: memory is what
you chose to remember. The agent gets a small, explicit write tool
(`obsidian_write`) rather than an archival firehose, and the tool
description itself steers the model toward atomic, deduplicated,
small-op edits rather than dumping every session turn into the vault.
You stay the editor — the agent assists.

The vault ends up small, dense, and almost entirely signal. That
curated remnant is what makes retrieval surface the right thing
instead of the loudest thing.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) — per-client setup (Claude Code, Cursor, Zed, generic, HTTP remote)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, principles
- [docs/WRITE-WORKFLOW.md](docs/WRITE-WORKFLOW.md) — `obsidian_write` ops, conventions, supersedes
- [docs/SECURITY.md](docs/SECURITY.md) — path-traversal guard, atomic writes, HTTP auth, memory-poisoning notes
- [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md) — alternative embedders, env vars
- [docs/TROUBLESHOOT.md](docs/TROUBLESHOOT.md) — common errors and fixes
- [ROADMAP.md](ROADMAP.md) — v1.2+ planned features

## License

MIT. See [LICENSE](LICENSE).

## Credits

The pattern of embedding a PROTOCOL string in the first read-tool's response
is borrowed from [MemPalace](https://github.com/milla-jovovich/mempalace)'s
`tool_status`. The design was shaped by empirical comparisons with raw
conversation archives — curation beats volume.
