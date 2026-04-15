# Architecture

This document describes the components of `second-brain-mcp`, how data
flows through them, and the principles that constrain the design.

---

## 1. Non-goals and guarantees

Five principles are inviolable. Everything else is negotiable.

1. **The vault is the single source of truth.** No automatic process ever
   writes to the vault. Writes happen only through the `to_obsidian`
   workflow, under explicit user approval for each note.
2. **The index is disposable.** The ChromaDB collection and the backlinks
   sidecar can be deleted at any moment and rebuilt in seconds. No state
   lives in the index that does not exist in the vault.
3. **MCP is read-only.** The server exposes zero write tools. An agent
   cannot create, update, or delete notes during a session. All writes
   go through the `to_obsidian` prompt, which instructs the agent to use
   its own client's write tool.
4. **Staleness is the server's problem, not the agent's.** The MCP server
   runs an incremental mtime-scan reindex before every tool call. For an
   unchanged vault this takes microseconds. The agent never thinks about
   index freshness.
5. **Semantics are multilingual.** The default embedder is `BAAI/bge-m3`
   because vaults often contain mixed-language content. The common
   English-only default (`all-MiniLM-L6-v2`) is not suitable — this was
   validated empirically. Alternative embedders are documented in
   [CUSTOMIZE.md](./CUSTOMIZE.md).

---

## 2. Data flow

```
                  ╭───────────────────────────────╮
                  │  to_obsidian  (write path)    │
                  │  invoked by the user at the   │
                  │  end of a session, with       │
                  │  explicit approval for each   │
                  │  note and an _index.md update │
                  ╰──────────────┬────────────────╯
                                 │ writes .md with YAML frontmatter + [[wikilinks]]
                                 ▼
              ╭──────────────────────────────────────────╮
              │   $OBSIDIAN_VAULT/                       │  ← source of truth
              │   ├─ _index.md (navigation)              │
              │   ├─ me/                                 │
              │   ├─ projects/<name>/                    │
              │   ├─ knowledge/<domain>/                 │
              │   ├─ insights/                           │
              │   └─ ref/                                │
              ╰──────────────────────┬───────────────────╯
                                     │ walked by indexer.py
                                     │  - YAML frontmatter parsing
                                     │  - [[wikilink]] extraction
                                     │  - chunking (small whole, big by H2/H3)
                                     │  - bge-m3 embedding (MPS / CUDA / CPU)
                                     ▼
        ╭────────────────────────────────────────────────────╮
        │  $OBSIDIAN_INDEX_DIR/  (default ~/.second-brain-mcp/)│
        │  ├─ index/         ← ChromaDB persistent            │
        │  │                    collection: obsidian_notes    │
        │  │                    embedding_fn: bge-m3          │
        │  └─ backlinks.json ← {wikilink_target: [rel, ...]}  │
        ╰───────────────────┬────────────────────────────────╯
                            │ read by server.py
                            │  - staleness check on every call
                            │  - 4 stdio MCP tools
                            │  - 1 MCP prompt (to_obsidian)
                            ▼
             ╭──────────────────────────────────────╮
             │  MCP client (Claude Code / Cursor /  │
             │  Zed / any stdio MCP consumer)       │
             │                                      │
             │  Tools (read-only):                  │
             │  • obsidian_overview                 │
             │  • obsidian_search                   │
             │  • obsidian_read                     │
             │  • obsidian_backlinks                │
             │                                      │
             │  Prompts:                            │
             │  • to_obsidian                       │
             ╰──────────────────────────────────────╯
```

---

## 3. Components

### `src/second_brain_mcp/indexer.py`

The vault indexer. Used both by the MCP server (as a library) and the CLI
(as a standalone tool for debugging and offline rebuilds).

- Walks `$OBSIDIAN_VAULT/**/*.md`.
- Skips any file whose name starts with `_index` (both `_index.md` and
  sync-conflict artifacts like `_index 1.md`). `_index.md` is not vectorised
  because it is returned whole through `obsidian_overview` and would
  otherwise dominate keyword-like ranking.
- Parses YAML frontmatter with `pyyaml`. Broken frontmatter does not crash
  indexing — the note is indexed without frontmatter metadata.
- Resolves a title: first `# H1` in the first 10 lines, else the filename
  stem.
- Extracts wikilinks via regex:
  `\[\[([^\]\|#^]+)(?:[#^][^\]\|]*)?(?:\|[^\]]*)?\]\]` — catches
  `[[note]]`, `[[note#heading]]`, `[[note^block]]`, and `[[note|display]]`.
- Chunks notes: under 1500 characters → one whole chunk; larger → split on
  `##` / `###` headings with a merge target of ~1400 chars, falling back
  to a sliding window with overlap 180.
- Embeds through
  `chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction`.
  Model cached in `~/.cache/huggingface/`. First call is cold (~5 s from
  cache), subsequent calls instantaneous.
- Per-chunk metadata: `rel`, `title`, `chunk_index`, `mtime`, `fm_type`,
  `fm_verified`, `fm_confidence`, `outlinks` (comma-separated string, since
  ChromaDB `where`-filters don't accept lists).
- Deterministic chunk IDs: `sha256(rel)[:16]_<chunk_index>`. Re-indexing the
  same note overwrites its chunks instead of duplicating them.
- Generates `backlinks.json` on the same pass:
  `{wikilink_target: [rel_path_of_linking_note, ...]}`.

### `src/second_brain_mcp/server.py`

The stdio MCP server, built on the official `mcp` Python SDK. Exposes the
4 tools and the 1 prompt described below. Every tool starts by calling
`indexer.index_incremental()` — a no-op for an unchanged vault.

### `src/second_brain_mcp/prompts.py`

Holds the text of the `to_obsidian` MCP prompt. Re-exported to clients via
`prompt/get`. Full rationale per step lives in
[WRITE-WORKFLOW.md](./WRITE-WORKFLOW.md).

### `src/second_brain_mcp/cli.py`

Entry point `second-brain-mcp` with subcommands:

- `serve` — run the stdio MCP server (what MCP clients invoke)
- `index` — incremental reindex (debugging)
- `rebuild` — full wipe + reindex
- `search "query" [--n 5] [--type knowledge]` — CLI search, bypasses MCP
- `stats` — index size, embedder name, device

### `src/second_brain_mcp/config.py`

Reads env vars (`OBSIDIAN_VAULT`, `OBSIDIAN_INDEX_DIR`,
`OBSIDIAN_EMBED_MODEL`, `OBSIDIAN_EMBED_DEVICE`) with defaults and explicit
error messages when a required variable is missing.

---

## 4. Tools

| Tool                  | Inputs                                          | Outputs                                                                                              | When to call                                                       |
|-----------------------|-------------------------------------------------|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| `obsidian_overview`   | —                                               | `protocol`, `vault_path`, `stats` (notes/chunks/by_type/by_top_dir), `reindex` status, `index_md`    | First call in every new session; returns the PROTOCOL + the vault map |
| `obsidian_search`     | `query: str`, `n: int = 5`, `type_filter?: str` | `query`, `type_filter`, `hits[]` with `rel`, `title`, `fm_type`, `fm_confidence`, `similarity`, `snippet` | Before answering any question about prior context                  |
| `obsidian_read`       | `rel: str`                                      | `rel`, `title`, `frontmatter` (dict), `body` (fresh from disk), `outlinks`, `backlinks`, `mtime`     | After a promising hit in `obsidian_search`, to read the full text  |
| `obsidian_backlinks`  | `note_title: str`                               | `note_title`, `backlinks[]` (rel paths that link to this note)                                       | Graph navigation — discover who references a given note            |

---

## 5. PROTOCOL design note

The response of `obsidian_overview` includes a short PROTOCOL string that
tells the agent how to use the four tools in order: read overview at
session start, search before answering, read for full text, use backlinks
for graph navigation, never write through MCP, and prefer a clean miss
over fabrication. The point is to deliver behavioural rules in-context
through the tool response itself — no system-prompt patching, no client
configuration.

The technique is borrowed from
[MemPalace](https://github.com/milla-jovovich/mempalace), whose
`tool_status` tool returns a `PALACE_PROTOCOL` string for the same reason.
We use the same mechanism in `obsidian_overview`. The PROTOCOL text is
kept under ~600 tokens by design so that it never competes with the real
content of `_index.md` for the agent's attention.

---

## 6. Incremental reindex

`index_incremental()` is cheap enough to run on every MCP tool call:

1. Walk the vault once, collecting `(rel, mtime)` for every `.md` file.
2. Query ChromaDB for the max `mtime` per `rel` currently in the
   collection.
3. Compare the two sets:
   - Notes that changed → delete old chunks by `where={"rel": ...}`, embed
     and insert new chunks.
   - Notes that disappeared from disk → delete their chunks.
   - New notes → embed and insert.
4. Untouched notes are skipped entirely — no embedding work, no disk I/O
   beyond the initial walk.

Because chunk IDs are derived deterministically from
`sha256(rel)[:16]_<chunk_index>`, any re-index of the same content
overwrites existing entries rather than duplicating them. A full `rebuild`
is therefore a convenience — `index_incremental()` converges to the same
state.

For a vault of ~100 notes with nothing changed, the scan is on the order
of milliseconds. Agents never need to think about it.

---

## 7. Non-features

Things this package deliberately does **not** do:

- **Automatic or background extraction** — no background process, no
  mid-session writes, no reflection or compaction loop running without
  the user's knowledge. Extraction does happen during an explicit
  `/to_obsidian` invocation: the LLM walks the session, identifies
  candidates, and checks for duplicates. But every candidate note
  requires explicit per-note approval before it is written to the vault.
- **Reflection loops** — no agent-authored reflections that get fed back
  into memory. `to_obsidian` is the reflection step, but the human is in
  the loop for every accepted entry.
- **Compaction** — no summarisation or merging of older notes. The vault
  is append-mostly; supersedes are handled by marking old notes
  `confidence: deprecated` with a `superseded_by` wikilink.
- **Multi-user / shared memory** — single-vault, single-user by design.
- **Write tools over MCP** — see [SECURITY.md](./SECURITY.md).
- **LLM-driven consolidation** — no clustering, no deduplication beyond
  what semantic search surfaces to the user during `to_obsidian`.

These are intentional. See [ROADMAP.md](../ROADMAP.md) for the short list
of features that will ship later, and the explicit non-goals section
there.
