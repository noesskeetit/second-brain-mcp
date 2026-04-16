# FM API (OpenAI-compatible) Embedder — Design Spec

**Date:** 2026-04-16
**Status:** Approved (design)
**Scope:** single implementation plan

## Motivation

Today the only embedder is local `sentence-transformers` via
`chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction`.
That requires ~420 MB–2.3 GB on disk plus CPU/GPU for inference. Users
who run second-brain-mcp on a thin client, a CI box without a GPU, or
who already have an OpenAI-compatible embedding endpoint (e.g. Cloud.ru
Foundation Models API at `https://foundation-models.api.cloud.ru/v1`,
OpenAI proper, a self-hosted Infinity server) want to offload
embeddings to that endpoint instead.

Goal: add a second provider option — generic OpenAI-compatible HTTP —
alongside the existing local provider. The local provider remains the
default; API mode is strictly opt-in. Nothing about the project's
"editorial, offline-by-default" positioning changes.

## Non-goals

- No provider-specific shortcuts (no hardcoded URLs for Cloud.ru,
  OpenAI, etc.). The provider is generic OpenAI-compatible; specific
  endpoints are documented examples.
- No auto-fallback between providers. One index, one provider.
- No background re-embedding when switching providers. User runs
  `rebuild` explicitly (same as when switching local models today).
- No integration tests against real API endpoints. Tests mock the
  OpenAI embedding function; network is never touched in CI.
- No retry/backoff logic beyond what the `openai` SDK ships with
  (`max_retries=2`).

## Public contract — environment variables

Four new env vars; none required in the default (`local`) mode.

| Variable | Default | Purpose |
|---|---|---|
| `OBSIDIAN_EMBED_PROVIDER` | `local` | `local` \| `openai`. Selects embedding source. |
| `OBSIDIAN_EMBED_API_KEY` | — | API key. **Required** when `provider=openai`. |
| `OBSIDIAN_EMBED_API_URL` | — | Base URL (e.g. `https://foundation-models.api.cloud.ru/v1`). **Required** when `provider=openai`. |
| `OBSIDIAN_EMBED_DIMENSIONS` | — | Optional integer override of embedding dimension. Passed through to `OpenAIEmbeddingFunction(dimensions=...)`. When unset, the server returns the model's native dimension. |

Existing variables keep their semantics, with one clarification:

- `OBSIDIAN_EMBED_MODEL` — HuggingFace identifier when `provider=local`
  (e.g. `BAAI/bge-m3`); OpenAI-style `model` string when
  `provider=openai` (e.g. `Qwen/Qwen3-Embedding-0.6B`,
  `text-embedding-3-small`).
- `OBSIDIAN_EMBED_DEVICE` — used only when `provider=local`; silently
  ignored under `provider=openai`.

### Validation (fail-fast at `config.load()`)

- `OBSIDIAN_EMBED_PROVIDER` is normalized to lowercase.
- Unknown provider (anything outside `{"local", "openai"}`) → `RuntimeError`.
- `provider=openai` without `API_KEY` and/or `API_URL` → `RuntimeError`
  listing every missing variable and pointing at `docs/CUSTOMIZE.md`.
- `OBSIDIAN_EMBED_DIMENSIONS`, when present, must parse as a positive integer; otherwise `RuntimeError`.
- `embed_device` is computed (via `_auto_device`) only when
  `provider=local`. In API mode we skip the torch import path entirely.

## Code changes

### `src/second_brain_mcp/config.py` (~+20 lines)

Add to `@dataclass(frozen=True) Config`:

```python
embed_provider: str            # "local" | "openai"
embed_api_key: str | None
embed_api_url: str | None
embed_dimensions: int | None
```

In `load()`:
- Read and normalize `OBSIDIAN_EMBED_PROVIDER` (default `"local"`).
- Validate against the allowed set.
- If `openai`: require `OBSIDIAN_EMBED_API_KEY` and
  `OBSIDIAN_EMBED_API_URL`, raise `RuntimeError` listing every missing
  variable with a pointer to the docs.
- Parse `OBSIDIAN_EMBED_DIMENSIONS` as int when set.
- Skip `_auto_device()` when provider is `openai` — store `embed_device` as
  empty string in that case, since it is unused.

### `src/second_brain_mcp/indexer.py` (~+15 lines in `embed_fn()`)

Branch on provider inside the existing lazy singleton:

```python
def embed_fn():
    global _EMBED_FN
    if _EMBED_FN is None:
        cfg = _get_cfg()
        if cfg.embed_provider == "openai":
            kwargs = {
                "api_key": cfg.embed_api_key,
                "api_base": cfg.embed_api_url,
                "model_name": cfg.embed_model,
            }
            if cfg.embed_dimensions:
                kwargs["dimensions"] = cfg.embed_dimensions
            _EMBED_FN = embedding_functions.OpenAIEmbeddingFunction(**kwargs)
        else:
            _EMBED_FN = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=cfg.embed_model,
                device=cfg.embed_device,
            )
    return _EMBED_FN
```

`stats()` adds `embed_provider` to its returned dict so the active mode
is visible from the `obsidian_overview` tool.

### Collection stamp and compatibility check

Chroma allows arbitrary metadata on a collection. On creation
(`reset_collection` and the `create_collection` fallback in
`get_collection`), write:

```python
{
    "embed_provider": cfg.embed_provider,
    "embed_model": cfg.embed_model,
    "embed_dimensions": str(cfg.embed_dimensions) if cfg.embed_dimensions else "",
}
```

On open of an existing collection, if the stored `embed_provider` or
`embed_model` differ from the current config, raise `RuntimeError` with
the exact remediation command:

```
Index was built with provider=<old_provider>, model=<old_model>, but
current config is provider=<new_provider>, model=<new_model>. Rebuild:
  rm -rf $OBSIDIAN_INDEX_DIR/index && second-brain-mcp rebuild
```

This closes a silent-failure hole that exists today when two local
models happen to share a dimension. `rebuild()` wipes the collection,
so re-running it after the switch is sufficient.

### `pyproject.toml`

Add `openai>=1.0` to the main `dependencies` array. No optional extras
— we decided during brainstorming that the ~few-MB install cost is
not worth the additional install UX complexity.

## Error handling during indexing

No special handling beyond existing patterns.

- The `openai` SDK retries transient failures (default
  `max_retries=2`, exponential backoff).
- On hard failure, the exception propagates through Chroma's `col.add`
  or `col.query` up to the caller (`rebuild`, `index_incremental`,
  `search`, etc.) and surfaces in MCP client logs.
- `parse_note` errors are already caught and logged as `skip {md}: {e}`;
  `_add_note` errors are not — and we keep that behavior. A mid-rebuild
  network failure should abort the rebuild, not silently skip notes.

## First-run UX

- **Local mode (default):** unchanged. First tool call downloads the
  embedder into `~/.cache/huggingface/`.
- **API mode:** no download. First tool call hits the network. If
  `OBSIDIAN_EMBED_API_KEY` or `_URL` is missing, the server fails to
  start with the fail-fast error from `config.load()`. If the key is
  invalid, the `openai` SDK raises `AuthenticationError` on the first
  `col.add`/`col.query`; this appears in the MCP client's stderr
  stream. We don't attempt to pre-flight the endpoint.

## Documentation changes

### `docs/CUSTOMIZE.md` — restructured

1. **`## Environment variables`** — extend the table with the four
   new variables. Add a column (or footnote) marking which apply
   only to `provider=local` (`OBSIDIAN_EMBED_DEVICE`) vs
   `provider=openai` (`OBSIDIAN_EMBED_API_KEY`, `_URL`,
   `_DIMENSIONS`).
2. **`## Local embedder (default)`** — renamed from "Alternative
   embedders". Content unchanged (bge-m3 / mpnet / MiniLM table).
3. **`## API embedder (OpenAI-compatible)`** — new section:
   - When to pick it (no GPU, thin client, self-hosted Infinity, existing API credits).
   - Full working recipe for Cloud.ru FM API (complete `claude mcp add`
     command with all five env vars).
   - Short list of tested endpoints (Cloud.ru FM API with
     `Qwen/Qwen3-Embedding-0.6B`; OpenAI proper as a sanity example).
     Not a registry — just documented-working starting points.
   - Note: switching providers or models invalidates the index; a
     `rebuild` is required.
4. **`## How to switch embedders`** — updated wording to cover the
   provider axis as well as the model axis. Mechanics are identical
   (`rm -rf index && rebuild`).

### `README.md`

One-line pointer in the "30-second quick start" or at the end of
section "Why editorial, not archival": *"Prefer a hosted embedder over
the 2.3 GB local model? See `docs/CUSTOMIZE.md` → API embedder."* The
offline-first narrative stays intact — API mode is presented as
opt-in.

### `ROADMAP.md`

If there is a line about hosted / remote embedders under v1.1 or
later, mark it done (or remove).

## Tests

All pytest, all offline, all in the style of the existing
`test_config.py` and `conftest.py`. No real HTTP calls.

### `tests/test_config.py` — add

- `test_default_provider_is_local` — no provider env var set →
  `cfg.embed_provider == "local"`, `embed_api_key is None`,
  `embed_api_url is None`, `embed_dimensions is None`.
- `test_openai_provider_requires_key_and_url` — set
  `OBSIDIAN_EMBED_PROVIDER=openai` without key/url → `RuntimeError`
  mentioning both missing variables by name.
- `test_openai_provider_loads_fully` — all three required env vars
  set → fields populated correctly on the `Config` dataclass.
- `test_unknown_provider_rejected` — e.g. `anthropic` →
  `RuntimeError`.
- `test_dimensions_parsed` — `OBSIDIAN_EMBED_DIMENSIONS=512` →
  `cfg.embed_dimensions == 512` (int). Non-numeric value, `0`, or
  negative → `RuntimeError`.

### `tests/test_indexer_embed_fn.py` — new file

- `test_embed_fn_local_uses_sentence_transformer` — with the
  default `tmp_vault` fixture, call `indexer.embed_fn()` and check
  the concrete type (`SentenceTransformerEmbeddingFunction`). (The
  existing `tmp_vault` already pins `all-MiniLM-L6-v2` for speed.)
- `test_embed_fn_openai_uses_openai_fn` — monkeypatch
  `indexer.embedding_functions.OpenAIEmbeddingFunction` to a
  recording stub that captures kwargs and returns a sentinel; set
  `OBSIDIAN_EMBED_PROVIDER=openai`, `OBSIDIAN_EMBED_API_KEY=...`,
  `OBSIDIAN_EMBED_API_URL=...`, `OBSIDIAN_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B`;
  clear `indexer._EMBED_FN` and `indexer._get_cfg` cache; assert the
  stub was called with `api_key`, `api_base`, `model_name` and no
  `dimensions` key.
- `test_embed_fn_openai_passes_dimensions_when_set` — same as above,
  plus `OBSIDIAN_EMBED_DIMENSIONS=512`, assert
  `dimensions=512` in kwargs.
- `test_embed_fn_openai_omits_dimensions_when_unset` — companion to
  the above.

### Stamp / compatibility test

Added either to `test_indexer_smoke.py` or a small new
`test_index_stamp.py`:

- Build the index with `tmp_vault` (local, `all-MiniLM-L6-v2`).
- Swap env to `provider=openai` with the `OpenAIEmbeddingFunction`
  stub. Clear `indexer._EMBED_FN` and `_get_cfg` cache.
- Call `indexer.get_collection()` → expect `RuntimeError` whose
  message contains both the old and new model names and the
  `rm -rf ... && ... rebuild` hint.

### Not added

No integration tests against real API endpoints. No tests that
exercise `openai` SDK retry semantics — we trust the SDK and don't
want CI flakes over network.

## Out of scope / future work

- Provider abstraction module (`embedders.py`). Warranted only when a
  third provider is added; for two providers the inline branch in
  `embed_fn()` is clearer.
- Embedder hot-swap without rebuild (e.g. per-query provider
  override). Not useful for this project's workflow — the index is
  single-model by construction.
- Batch-size tuning. Chroma's `OpenAIEmbeddingFunction` handles
  batching; if a specific endpoint imposes tighter payload limits,
  address it when a user actually hits it.
