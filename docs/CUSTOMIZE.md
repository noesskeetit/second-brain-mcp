# Customize

All configuration is driven by environment variables passed to the MCP
server (typically via `claude mcp add -e ...` or the equivalent in your
client's config). No config files, no flags.

---

## Environment variables

| Variable                | Default                   | Purpose                                                         |
|-------------------------|---------------------------|-----------------------------------------------------------------|
| `OBSIDIAN_VAULT`        | —                         | **Required.** Absolute path to your Obsidian vault.             |
| `OBSIDIAN_INDEX_DIR`    | `~/.second-brain-mcp/`    | Where the ChromaDB persistent dir and `backlinks.json` live.    |
| `OBSIDIAN_EMBED_MODEL`  | `BAAI/bge-m3`             | `sentence-transformers` model identifier used for embeddings.   |
| `OBSIDIAN_EMBED_DEVICE` | auto (`mps` / `cuda` / `cpu`) | Torch device for embedding. Override when auto-detect is wrong. |

When `OBSIDIAN_VAULT` is missing, the server fails fast with a readable
error pointing to this doc.

---

## Alternative embedders

The default embedder — `BAAI/bge-m3` — is the right choice for most
vaults because it handles mixed-language content well. If you need a
smaller model (disk, download bandwidth, or CPU-only inference), pick
from the table below and switch via `OBSIDIAN_EMBED_MODEL`.

| Model                                                         | Size    | Multilinguality           | Recommendation                                                                 |
|---------------------------------------------------------------|---------|---------------------------|--------------------------------------------------------------------------------|
| `BAAI/bge-m3`                                                 | 2.3 GB  | 100+ languages            | **Default.** Best quality on mixed-language vaults.                            |
| `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | 970 MB  | 50+ languages             | Good compromise between size and quality when bge-m3 is too heavy.             |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 420 MB  | moderate                  | Fast and small; noticeably weaker on nuanced semantic queries.                 |
| `sentence-transformers/all-MiniLM-L6-v2`                      | 90 MB   | English only              | Pick this only if your vault is entirely English.                              |

---

## How to switch embedders

Changing the embedder changes the embedding dimensionality, which makes
your old index incompatible. The recipe is:

```bash
# 1. Re-register the server with the new model env var
claude mcp remove second-brain
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$HOME/obsidian/vault" \
  -e OBSIDIAN_EMBED_MODEL="sentence-transformers/paraphrase-multilingual-mpnet-base-v2" \
  -- uvx second-brain-mcp serve

# 2. Drop the old index — old embeddings have a different dimension
rm -rf $OBSIDIAN_INDEX_DIR/index

# 3. Rebuild with the new model
uvx second-brain-mcp rebuild
```

The first `rebuild` after a model switch triggers a download of the new
model from HuggingFace (unless already cached under
`~/.cache/huggingface/`). Subsequent rebuilds hit only the local cache.

Restart your MCP client (e.g. Claude Code) after step 1 so that the
re-registered server picks up the new environment variable.

---

## Data-dir layout

Everything the server writes lives under `$OBSIDIAN_INDEX_DIR` (default
`~/.second-brain-mcp/`):

```
$OBSIDIAN_INDEX_DIR/
├── index/           ChromaDB persistent directory (collection: obsidian_notes)
└── backlinks.json   {wikilink_target: [rel_path_of_linking_note, ...]}
```

Both are **safe to delete**. A `rebuild` regenerates them from the vault.
Your vault is never touched.

If disk usage is a concern, `index/` is usually a few hundred kilobytes
to a few megabytes for vaults under a thousand notes. The bulk of disk
cost is the embedder in `~/.cache/huggingface/`, not the index itself.
