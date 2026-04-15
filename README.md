# second-brain-mcp

Turn your Obsidian vault into semantic memory for any MCP-capable coding agent.

**What it does.** Ships a stdio MCP server with four read-only tools
(`obsidian_overview`, `obsidian_search`, `obsidian_read`, `obsidian_backlinks`)
plus one prompt (`to_obsidian`) that drives a human-in-the-loop write
workflow. Works with Claude Code, Cursor, Zed, or any client that speaks MCP.

**What it is not.** No auto-writes — nothing is written to the vault
without an explicit `/to_obsidian` invocation. No background extraction,
no reflection or compaction loops running on your behalf. The LLM does
the extraction work when you call `/to_obsidian`, but every candidate
note requires your explicit per-note approval before it is written.
You control what enters the vault; the server only reads from it.

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
for lighter models.

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

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) — per-client setup (Claude Code, Cursor, Zed, generic)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, principles
- [docs/WRITE-WORKFLOW.md](docs/WRITE-WORKFLOW.md) — `to_obsidian` explained
- [docs/SECURITY.md](docs/SECURITY.md) — read-only guarantees, path-traversal
- [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md) — alternative embedders, env vars
- [docs/TROUBLESHOOT.md](docs/TROUBLESHOOT.md) — common errors and fixes
- [ROADMAP.md](ROADMAP.md) — v1.1+ planned features

## License

MIT. See [LICENSE](LICENSE).

## Credits

The pattern of embedding a PROTOCOL string in the first read-tool's response
is borrowed from [MemPalace](https://github.com/milla-jovovich/mempalace)'s
`tool_status`. The design was shaped by empirical comparisons with raw
conversation archives — curation beats volume.
