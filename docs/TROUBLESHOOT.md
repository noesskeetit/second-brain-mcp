# Troubleshoot

Common problems and their fixes, ordered roughly by how often they come
up on first install.

---

### `claude mcp list` shows `second-brain: ... - ✗ Failed to connect`

Run the stdio command yourself to see the actual error on stderr:

```bash
OBSIDIAN_VAULT="$HOME/obsidian/vault" \
OBSIDIAN_EMBED_DEVICE="mps" \
  uvx second-brain-mcp serve
```

Typical errors:

- `ModuleNotFoundError: mcp` — `uvx` failed to install the package
  cleanly. Try `uvx --refresh second-brain-mcp serve` to re-pull.
- `ModuleNotFoundError: sentence_transformers` or `chromadb` — same
  story, force-refresh the uvx cache.
- `OBSIDIAN_VAULT is not set` — export it in the shell that launches
  the client, or pass `-e OBSIDIAN_VAULT=...` through the client's MCP
  config.
- `No such file or directory` for the vault path — typo or wrong
  expansion. Use an absolute path; avoid `~` in non-shell contexts.
- `RuntimeError: MPS backend ...` on macOS — the MPS backend is
  occasionally unstable on older macOS releases. Fall back to
  `OBSIDIAN_EMBED_DEVICE=cpu`.
- Long silence on first run — the bge-m3 model is downloading
  (~2.3 GB). Wait it out; future runs are instant.

---

### `rebuild` completes but `"notes": 0`

Your `OBSIDIAN_VAULT` doesn't point where you think it does. Sanity
checks:

```bash
ls -la "$OBSIDIAN_VAULT" | head
find "$OBSIDIAN_VAULT" -maxdepth 2 -name "*.md" | head
```

If no `.md` files show up, the path is wrong. Common causes: shell
expansion (`~` not expanded in an MCP client's env block), typo in the
directory name, or pointing at the Obsidian config dir instead of the
vault.

---

### `obsidian_search` returns negative similarity numbers

This is normal. ChromaDB with L2 distance on normalised bge-m3 vectors
produces similarity scores in roughly `[-1, 1]`. Ranking is correct
(higher is better); only the absolute numbers look unusual.

Rules of thumb for interpretation:

- `> 0.3` — solid hit, worth reading.
- `0.0 to 0.3` — possible match, skim snippets first.
- `< 0` — weak or irrelevant. If every hit is negative, the vault
  probably has no relevant content on that query.

If everything scores negative for a query you know should hit, see the
"wrong vault" case above before assuming a model issue.

---

### Claude Code doesn't see the tools after `claude mcp add`

MCP servers attach when a client session starts. Already-open sessions
do not pick up servers added afterwards. **Close and restart the
session.**

This is also why an agent installing `second-brain-mcp` inside its own
Claude Code session cannot test the tools in that same session — the
MCP client was initialised before the server was registered. The agent
should hand off to the user with a "please restart" message (see
[INSTALL.md](./INSTALL.md)).

---

### Slow first run

The first `serve`, `search`, `rebuild`, or `index` invocation downloads
the bge-m3 model (~2.3 GB) from HuggingFace. On a typical home
connection this is a few minutes. The download is cached under
`~/.cache/huggingface/` and is never repeated.

Rebuild timings after the model is cached:

- Apple Silicon (MPS) or NVIDIA GPU (CUDA): ~10–30 s for a vault of a
  few hundred notes.
- CPU-only: 1–3 minutes for the same vault.
- Vaults over 1000 notes scale roughly linearly.

Incremental reindex on an unchanged vault is microseconds regardless of
size.

---

### `RuntimeError: MPS backend` on macOS

The MPS (Metal) backend in PyTorch occasionally errors out on older
macOS versions or with specific model kernels. Fall back to CPU:

```bash
claude mcp remove second-brain
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$HOME/obsidian/vault" \
  -e OBSIDIAN_EMBED_DEVICE="cpu" \
  -- uvx second-brain-mcp serve
```

CPU inference is slower on first embed but fine for most vaults. The
only other option is updating macOS / PyTorch; MPS reliability has
improved materially in recent releases.

---

### bge-m3 is too big

Switch to a smaller embedder. See
[CUSTOMIZE.md](./CUSTOMIZE.md#alternative-embedders) for the table and
the three-command recipe. Remember that a model swap requires
`rm -rf $OBSIDIAN_INDEX_DIR/index` followed by `rebuild` — old
embeddings have a different dimension and are not compatible.
