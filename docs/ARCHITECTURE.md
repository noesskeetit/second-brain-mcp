# Architecture

This document describes the components of `second-brain-mcp`, how data
flows through them, and the principles that constrain the design.

---

## 1. Principles

Five principles are inviolable. Everything else is negotiable.

1. **The vault is the single source of truth.** The index is derived
   state; the vault is primary. `obsidian_write` mutates the vault
   directly (atomic tmp-replace) and then triggers an incremental
   reindex. Nothing is stored in the index that does not exist in the
   vault.
2. **The index is disposable.** The ChromaDB collection and the
   backlinks sidecar can be deleted at any moment and rebuilt in
   seconds. No state lives in the index that does not exist in the
   vault.
3. **Writes are deliberate, not autonomous.** The package ships one
   write tool with explicit per-op semantics and `dry_run` support —
   not a reflection loop, not a background extractor, not a
   bulk-apply endpoint. The agent is expected to write when
   instructed (or when a durable fact clearly warrants it) and to
   prefer small ops over rewrites. The tool description itself
   carries this guidance.
4. **Staleness is the server's problem, not the agent's.** The MCP
   server runs an incremental mtime-scan reindex before every read
   tool call and after every successful write. For an unchanged
   vault this takes microseconds. The agent never thinks about index
   freshness.
5. **Semantics are multilingual.** The default embedder is
   `BAAI/bge-m3` because vaults often contain mixed-language content.
   The common English-only default (`all-MiniLM-L6-v2`) is not
   suitable — this was validated empirically. Alternative embedders
   are documented in [CUSTOMIZE.md](./CUSTOMIZE.md).

---

## 2. Data flow

```
                    ╭──────────────────────────────╮
                    │  MCP client                  │
                    │  (Claude Code / Cursor /     │
                    │   Zed / generic MCP client)  │
                    ╰───────────┬──────────────────╯
                                │  stdio  OR  streamable HTTP
                                │  (Bearer auth in HTTP mode)
                                ▼
              ╭──────────────────────────────────────────╮
              │  server.py                               │
              │                                          │
              │  Reads:                                  │
              │   • obsidian_overview                    │
              │   • obsidian_search                      │
              │   • obsidian_read                        │
              │   • obsidian_backlinks                   │
              │                                          │
              │  Writes (single dispatcher tool):        │
              │   • obsidian_write(op=create|append|     │
              │       prepend|replace_body|replace_text| │
              │       set_frontmatter|delete|rename)     │
              ╰──────────┬───────────────────┬───────────╯
                         │ reads             │ writes via writer.py
                         │                   │  (atomic tmp+replace,
                         │                   │   path-traversal guard)
                         │                   ▼
                         │    ╭──────────────────────────────────────╮
                         │    │   $OBSIDIAN_VAULT/                   │
                         │    │   ├─ _index.md  (navigation)         │
                         │    │   ├─ me/                             │
                         │    │   ├─ projects/<name>/                │
                         │    │   ├─ knowledge/<domain>/             │
                         │    │   ├─ insights/                       │
                         │    │   └─ ref/                            │
                         │    ╰──────────────────┬───────────────────╯
                         │                       │ walked by indexer.py
                         │                       │  - YAML frontmatter
                         │                       │  - [[wikilink]] extraction
                         │                       │  - chunking (H2/H3)
                         │                       │  - bge-m3 embedding
                         │                       ▼
                         │    ╭──────────────────────────────────────────╮
                         └───▶│  $OBSIDIAN_INDEX_DIR/                    │
                              │  (default ~/.second-brain-mcp/)          │
                              │  ├─ index/         ← ChromaDB persistent │
                              │  │                   collection:         │
                              │  │                   obsidian_notes      │
                              │  └─ backlinks.json ← {target: [rel,...]} │
                              ╰──────────────────────────────────────────╯
```

Incremental reindex fires at the top of every read tool call and at
the end of every successful write — so search always reflects the
current vault, even immediately after an `obsidian_write`.

---

## 3. Components

### `src/second_brain_mcp/indexer.py`

The vault indexer. Used both by the MCP server (as a library) and the
CLI (as a standalone tool for debugging and offline rebuilds).

- Walks `$OBSIDIAN_VAULT/**/*.md`.
- Skips any file whose name starts with `_index` (both `_index.md`
  and sync-conflict artifacts like `_index 1.md`). `_index.md` is
  not vectorised because it is returned whole through
  `obsidian_overview` and would otherwise dominate keyword-like
  ranking.
- Parses YAML frontmatter with `pyyaml`. Broken frontmatter does not
  crash indexing — the note is indexed without frontmatter metadata.
- Resolves a title: first `# H1` in the first 10 lines, else the
  filename stem.
- Extracts wikilinks via regex:
  `\[\[([^\]\|#^]+)(?:[#^][^\]\|]*)?(?:\|[^\]]*)?\]\]` — catches
  `[[note]]`, `[[note#heading]]`, `[[note^block]]`, and
  `[[note|display]]`.
- Chunks notes: under 1500 characters → one whole chunk; larger →
  split on `##` / `###` headings with a merge target of ~1400 chars,
  falling back to a sliding window with overlap 180.
- Embeds through either
  `SentenceTransformerEmbeddingFunction` (local, default) or
  `OpenAIEmbeddingFunction` (`OBSIDIAN_EMBED_PROVIDER=openai`,
  points at any OpenAI-compatible `/v1/embeddings`).
- Per-chunk metadata: `rel`, `title`, `chunk_index`, `mtime`,
  `fm_type`, `fm_verified`, `fm_confidence`, `outlinks`
  (comma-separated string, since ChromaDB `where`-filters don't
  accept lists).
- Deterministic chunk IDs: `sha256(rel)[:16]_<chunk_index>`.
  Re-indexing the same note overwrites its chunks instead of
  duplicating them.
- Generates `backlinks.json` on the same pass:
  `{wikilink_target: [rel_path_of_linking_note, ...]}`.

### `src/second_brain_mcp/writer.py`

The mutation layer. Each `obsidian_write` op maps to one pure
function here (`op_create`, `op_append`, `op_prepend`,
`op_replace_body`, `op_replace_text`, `op_set_frontmatter`,
`op_delete`, `op_rename`) plus a dispatcher `apply(cfg, op, args)`.
Kept in its own module so it can be unit-tested without the MCP
wrapper — see [`tests/test_writer.py`](../tests/test_writer.py).

Invariants enforced here, not in `server.py`:

- **Path guard.** Every op runs paths through `_safe_path()` which
  does `(vault / rel).resolve().relative_to(vault.resolve())`. Absolute
  paths, `..` escapes, and symlink traps all fail closed.
- **Atomic writes.** Helper `_atomic_write()` writes to a hidden tmp
  file then `os.replace`s into place. Tmp is cleaned on exception.
- **Frontmatter preservation.** Ops that don't target frontmatter
  (`append`, `prepend`, `replace_body`, `replace_text`) parse the
  frontmatter block and re-emit it verbatim in structure, touching
  only the body.
- **`dry_run` semantics.** When `dry_run=true`, every op returns
  `{before, after}` and skips all disk writes. `changed` in the
  result still reflects whether the op would have changed state.

### `src/second_brain_mcp/server.py`

The MCP server, built on the official `mcp` Python SDK. Exposes the
5 tools described below. Every read tool starts by calling
`indexer.index_incremental()` — a no-op for an unchanged vault.
`obsidian_write` dispatches into `writer.apply()` and, on success,
runs the same incremental reindex so the next search reflects the
edit.

Both transports live here:

- **stdio** — `_serve_stdio()` via `mcp.server.stdio.stdio_server`.
  The default; used by `claude mcp add` and subprocess launchers.
- **http** — `_serve_http()` builds a Starlette ASGI app wrapping
  `StreamableHTTPSessionManager` + a Bearer-auth middleware, then
  runs it under uvicorn. Refuses to bind to a non-loopback host
  without `OBSIDIAN_HTTP_TOKEN` set.

### `src/second_brain_mcp/cli.py`

Entry point `second-brain-mcp` with subcommands:

- `serve [--transport stdio|http] [--host --port --path]` — run the
  MCP server (what MCP clients invoke).
- `index` — incremental reindex (debugging).
- `rebuild` — full wipe + reindex.
- `search "query" [--n 5] [--type knowledge]` — CLI search, bypasses
  MCP.
- `stats` — index size, embedder name, device.

### `src/second_brain_mcp/config.py`

Reads env vars and returns a frozen `Config` dataclass with explicit
error messages when a required variable is missing. Covers:

- Vault & index location: `OBSIDIAN_VAULT` (required),
  `OBSIDIAN_INDEX_DIR`.
- Embedder: `OBSIDIAN_EMBED_PROVIDER` (`local` | `openai`),
  `OBSIDIAN_EMBED_MODEL`, `OBSIDIAN_EMBED_DEVICE`,
  `OBSIDIAN_EMBED_API_KEY`, `OBSIDIAN_EMBED_API_URL`,
  `OBSIDIAN_EMBED_DIMENSIONS`.
- HTTP transport: `OBSIDIAN_MCP_HOST`, `OBSIDIAN_MCP_PORT`,
  `OBSIDIAN_MCP_PATH`, `OBSIDIAN_HTTP_TOKEN`.

---

## 4. Tools

| Tool                  | Inputs                                          | Outputs                                                                                              | When to call                                                          |
|-----------------------|-------------------------------------------------|------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| `obsidian_overview`   | —                                               | `protocol`, `vault_path`, `stats`, `reindex`, `index_md`                                             | First call in every new session; returns the PROTOCOL + the vault map |
| `obsidian_search`     | `query: str`, `n: int = 5`, `type_filter?: str` | `query`, `type_filter`, `hits[]` with `rel`, `title`, `fm_type`, `fm_confidence`, `similarity`, `snippet` | Before answering any question about prior context                     |
| `obsidian_read`       | `path: str`                                     | `rel`, `title`, `frontmatter`, `body`, `outlinks`, `backlinks`, `mtime`                              | After a promising hit in `obsidian_search`                            |
| `obsidian_backlinks`  | `note_title: str`                               | `note_title`, `backlinks[]`                                                                          | Graph navigation — discover who references a given note               |
| `obsidian_write`      | `op: str`, `path: str`, plus op-specific args; all ops accept `dry_run: bool` | `ok`, `op`, `path`, `changed`, op-specific extras (`replacements`, `frontmatter`, `before`/`after` when dry-run), `reindex` on successful write | Whenever a durable change to the vault is warranted                   |

Full `obsidian_write` semantics are in [WRITE-WORKFLOW.md](./WRITE-WORKFLOW.md).

---

## 5. PROTOCOL design note

The response of `obsidian_overview` includes a short PROTOCOL string
that tells the agent how to use the five tools in order: read
overview at session start, search before answering, read for full
text, use backlinks for graph navigation, and use `obsidian_write`
deliberately (with dedup via search, preferring small ops). The
point is to deliver behavioural rules in-context through the tool
response itself — no system-prompt patching, no client configuration.

The technique is borrowed from
[MemPalace](https://github.com/milla-jovovich/mempalace), whose
`tool_status` tool returns a `PALACE_PROTOCOL` string for the same
reason. We use the same mechanism in `obsidian_overview`. The
PROTOCOL text is kept under ~700 tokens by design so that it never
competes with the real content of `_index.md` for the agent's
attention.

---

## 6. Incremental reindex

`index_incremental()` is cheap enough to run on every MCP read tool
call and after every successful write:

1. Walk the vault once, collecting `(rel, mtime)` for every `.md`
   file.
2. Query ChromaDB for the max `mtime` per `rel` currently in the
   collection.
3. Compare the two sets:
   - Notes that changed → delete old chunks by
     `where={"rel": ...}`, embed and insert new chunks.
   - Notes that disappeared from disk → delete their chunks.
   - New notes → embed and insert.
4. Untouched notes are skipped entirely — no embedding work, no disk
   I/O beyond the initial walk.

Because chunk IDs are derived deterministically from
`sha256(rel)[:16]_<chunk_index>`, any re-index of the same content
overwrites existing entries rather than duplicating them. A full
`rebuild` is therefore a convenience — `index_incremental()`
converges to the same state.

For a vault of ~100 notes with nothing changed, the scan is on the
order of milliseconds. Agents never need to think about it.

---

## 7. Non-features

Things this package deliberately does **not** do:

- **Automatic or background extraction.** No background process,
  no mid-session side effects, no reflection or compaction loop
  running without the user's knowledge. `obsidian_write` is a
  surgical tool invoked with intent; it is not a pipeline.
- **Reflection loops.** No agent-authored summaries fed back into
  memory on a timer.
- **Compaction.** No summarisation or merging of older notes. The
  vault is append-mostly; supersedes are handled by marking old
  notes `confidence: deprecated` with a `superseded_by` wikilink.
- **Bulk operations.** `obsidian_write` takes one op per call. No
  `apply_many`, no batch rewrite endpoint. Every mutation is a
  separate tool invocation that the client can log and gate.
- **Wikilink rewrite on rename.** `obsidian_write op=rename` moves
  the file only. References `[[old name]]` elsewhere in the vault
  are **not** rewritten automatically; do that with an explicit
  follow-up `replace_text` if you need it. The safety trade-off is
  explained in the tool description.
- **Multi-user / shared memory.** Single-vault, single-user by
  design.
- **LLM-driven consolidation.** No clustering, no deduplication
  beyond what semantic search surfaces to the agent when it
  chooses to check for duplicates before `create`.

These are intentional. See [ROADMAP.md](../ROADMAP.md) for the short
list of features that will ship later, and the explicit non-goals
section there.
