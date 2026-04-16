# FM API (OpenAI-compatible) Embedder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second embedder provider — generic OpenAI-compatible HTTP — alongside the existing local `sentence-transformers` one. Opt-in via `OBSIDIAN_EMBED_PROVIDER=openai` plus `OBSIDIAN_EMBED_API_KEY`/`_URL`. Local mode stays the default; nothing about offline-first positioning changes.

**Architecture:** All decisions branch on a single `cfg.embed_provider` value. `config.py::load()` validates the env surface fail-fast; `indexer.py::embed_fn()` instantiates either `SentenceTransformerEmbeddingFunction` or `OpenAIEmbeddingFunction` (both shipped by `chromadb.utils.embedding_functions`). A small collection-metadata stamp prevents silent dim-match cross-provider searches after a switch.

**Tech Stack:** Python 3.10+, `chromadb>=0.5`, `openai>=1.0` (new dep), `pytest`, `uv` for installs, existing `hatchling` build system.

**Spec:** `docs/superpowers/specs/2026-04-16-fm-api-embedder-design.md`

---

## File Map

- **Modify:** `pyproject.toml` — add `openai>=1.0` dependency
- **Modify:** `src/second_brain_mcp/config.py` — extend `Config`, add validation
- **Modify:** `src/second_brain_mcp/indexer.py` — branch `embed_fn()`, stamp-write in `get_collection`/`reset_collection`, stamp-check on open, surface `embed_provider` in `stats()`
- **Modify:** `tests/test_config.py` — add cases for new env vars
- **Create:** `tests/test_indexer_embed_fn.py` — verify provider dispatch
- **Create:** `tests/test_index_stamp.py` — verify cross-provider switch blocked
- **Modify:** `docs/CUSTOMIZE.md` — restructure + new API-embedder section
- **Modify:** `README.md` — one-line pointer to API embedder
- **Modify:** `ROADMAP.md` — mark "remote embedders" done if listed

---

## Task 1: Add `openai` dependency

**Files:**
- Modify: `pyproject.toml:21-27` (the `dependencies` array)

- [ ] **Step 1: Edit `pyproject.toml`**

Replace:

```toml
dependencies = [
    "mcp>=1.0",
    "chromadb>=0.5",
    "sentence-transformers>=3.0",
    "torch>=2.2",
    "pyyaml>=6.0",
]
```

with:

```toml
dependencies = [
    "mcp>=1.0",
    "chromadb>=0.5",
    "sentence-transformers>=3.0",
    "torch>=2.2",
    "pyyaml>=6.0",
    "openai>=1.0",
]
```

- [ ] **Step 2: Sync deps and verify import**

Run:
```bash
uv sync --extra dev
uv run python -c "from openai import OpenAI; from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add openai>=1.0 for OpenAI-compatible embedder provider"
```

---

## Task 2: Extend `Config` and validation (TDD)

**Files:**
- Modify: `src/second_brain_mcp/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_default_provider_is_local(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    cfg = config.load()
    assert cfg.embed_provider == "local"
    assert cfg.embed_api_key is None
    assert cfg.embed_api_url is None
    assert cfg.embed_dimensions is None


def test_openai_provider_requires_key_and_url(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_API_KEY"):
        config.load()
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_API_URL"):
        config.load()


def test_openai_provider_loads_fully(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    cfg = config.load()
    assert cfg.embed_provider == "openai"
    assert cfg.embed_api_key == "sk-test"
    assert cfg.embed_api_url == "https://example.com/v1"
    assert cfg.embed_model == "Qwen/Qwen3-Embedding-0.6B"


def test_provider_is_normalized_to_lowercase(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "OpenAI")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    cfg = config.load()
    assert cfg.embed_provider == "openai"


def test_unknown_provider_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match="anthropic"):
        config.load()


def test_dimensions_parsed_as_positive_int(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "512")
    cfg = config.load()
    assert cfg.embed_dimensions == 512


def test_dimensions_rejects_non_numeric(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "abc")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()


def test_dimensions_rejects_zero_and_negative(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")

    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "0")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()

    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "-5")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: 8 new tests FAIL with `AttributeError: 'Config' object has no attribute 'embed_provider'` (or similar). Existing tests still pass.

- [ ] **Step 3: Extend `Config` and `load()`**

Replace the entire contents of `src/second_brain_mcp/config.py` with:

```python
"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEX_DIR = Path.home() / ".second-brain-mcp"
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"
DEFAULT_PROVIDER = "local"
ALLOWED_PROVIDERS = {"local", "openai"}


def _auto_device() -> str:
    # Lazy-import torch so a missing torch during config inspection doesn't crash.
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


@dataclass(frozen=True)
class Config:
    vault: Path
    index_dir: Path
    embed_model: str
    embed_device: str
    embed_provider: str
    embed_api_key: str | None
    embed_api_url: str | None
    embed_dimensions: int | None


def _parse_dimensions(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "OBSIDIAN_EMBED_DIMENSIONS must be a positive integer, "
            f"got {raw!r}. See docs/CUSTOMIZE.md."
        ) from exc
    if value <= 0:
        raise RuntimeError(
            "OBSIDIAN_EMBED_DIMENSIONS must be a positive integer, "
            f"got {value}. See docs/CUSTOMIZE.md."
        )
    return value


def load() -> Config:
    vault_raw = os.environ.get("OBSIDIAN_VAULT")
    if not vault_raw:
        raise RuntimeError(
            "OBSIDIAN_VAULT is required. Set it to the absolute path of your vault, "
            "e.g. OBSIDIAN_VAULT=$HOME/obsidian/vault"
        )
    vault = Path(vault_raw).expanduser().resolve()
    index_dir = Path(os.environ.get("OBSIDIAN_INDEX_DIR", str(DEFAULT_INDEX_DIR))).expanduser()
    embed_model = os.environ.get("OBSIDIAN_EMBED_MODEL", DEFAULT_EMBED_MODEL)

    provider = os.environ.get("OBSIDIAN_EMBED_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise RuntimeError(
            f"OBSIDIAN_EMBED_PROVIDER={provider!r} is not supported. "
            f"Allowed values: {sorted(ALLOWED_PROVIDERS)}. See docs/CUSTOMIZE.md."
        )

    api_key = os.environ.get("OBSIDIAN_EMBED_API_KEY") or None
    api_url = os.environ.get("OBSIDIAN_EMBED_API_URL") or None
    dimensions = _parse_dimensions(os.environ.get("OBSIDIAN_EMBED_DIMENSIONS"))

    if provider == "openai":
        missing = []
        if not api_key:
            missing.append("OBSIDIAN_EMBED_API_KEY")
        if not api_url:
            missing.append("OBSIDIAN_EMBED_API_URL")
        if missing:
            raise RuntimeError(
                f"OBSIDIAN_EMBED_PROVIDER=openai requires: {', '.join(missing)}. "
                "See docs/CUSTOMIZE.md → API embedder."
            )
        embed_device = ""  # unused in API mode
    else:
        embed_device = os.environ.get("OBSIDIAN_EMBED_DEVICE") or _auto_device()

    return Config(
        vault=vault,
        index_dir=index_dir,
        embed_model=embed_model,
        embed_device=embed_device,
        embed_provider=provider,
        embed_api_key=api_key,
        embed_api_url=api_url,
        embed_dimensions=dimensions,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: ALL tests pass (existing 3 + new 8).

- [ ] **Step 5: Commit**

```bash
git add src/second_brain_mcp/config.py tests/test_config.py
git commit -m "feat(config): add OBSIDIAN_EMBED_PROVIDER + openai provider env vars"
```

---

## Task 3: Branch `embed_fn()` on provider (TDD)

**Files:**
- Create: `tests/test_indexer_embed_fn.py`
- Modify: `src/second_brain_mcp/indexer.py:51-62` (the `_EMBED_FN` singleton and `embed_fn()` function)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_indexer_embed_fn.py`:

```python
# tests/test_indexer_embed_fn.py
"""Provider dispatch in indexer.embed_fn()."""
from unittest.mock import MagicMock

import pytest

from second_brain_mcp import indexer


def _reset_caches():
    indexer._get_cfg.cache_clear()
    indexer._EMBED_FN = None


def test_embed_fn_local_uses_sentence_transformer(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("OBSIDIAN_EMBED_DEVICE", "cpu")
    _reset_caches()
    fn = indexer.embed_fn()
    assert type(fn).__name__ == "SentenceTransformerEmbeddingFunction"


def test_embed_fn_openai_uses_openai_fn(monkeypatch, tmp_path):
    sentinel = object()
    stub = MagicMock(return_value=sentinel)
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)

    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    _reset_caches()

    fn = indexer.embed_fn()

    assert fn is sentinel
    stub.assert_called_once()
    kwargs = stub.call_args.kwargs
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["api_base"] == "https://example.com/v1"
    assert kwargs["model_name"] == "Qwen/Qwen3-Embedding-0.6B"
    assert "dimensions" not in kwargs


def test_embed_fn_openai_passes_dimensions_when_set(monkeypatch, tmp_path):
    stub = MagicMock(return_value=object())
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)

    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "512")
    _reset_caches()

    indexer.embed_fn()

    kwargs = stub.call_args.kwargs
    assert kwargs["dimensions"] == 512
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_indexer_embed_fn.py -v`
Expected: The two `openai` tests FAIL (`embed_fn()` ignores provider today). The `local` test may PASS already.

- [ ] **Step 3: Update `embed_fn()` in `src/second_brain_mcp/indexer.py`**

Replace lines ~51–62:

```python
_EMBED_FN = None


def embed_fn():
    global _EMBED_FN
    if _EMBED_FN is None:
        cfg = _get_cfg()
        _EMBED_FN = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=cfg.embed_model,
            device=cfg.embed_device,
        )
    return _EMBED_FN
```

with:

```python
_EMBED_FN = None


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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_indexer_embed_fn.py tests/test_indexer_smoke.py -v`
Expected: All new tests PASS; existing smoke tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add src/second_brain_mcp/indexer.py tests/test_indexer_embed_fn.py
git commit -m "feat(indexer): branch embed_fn() on embed_provider (local|openai)"
```

---

## Task 4: Collection stamp + compatibility check (TDD)

**Files:**
- Create: `tests/test_index_stamp.py`
- Modify: `src/second_brain_mcp/indexer.py` — `get_collection()` and `reset_collection()`

- [ ] **Step 1: Write the failing test**

Create `tests/test_index_stamp.py`:

```python
# tests/test_index_stamp.py
"""Collection provider/model stamp blocks cross-provider searches."""
from unittest.mock import MagicMock

import pytest

from second_brain_mcp import indexer


def _reset_caches():
    indexer._get_cfg.cache_clear()
    indexer._EMBED_FN = None


def test_stamp_written_on_rebuild(tmp_vault):
    _reset_caches()
    indexer.rebuild()
    col = indexer.get_collection()
    meta = col.metadata or {}
    assert meta.get("embed_provider") == "local"
    assert meta.get("embed_model") == "sentence-transformers/all-MiniLM-L6-v2"


def test_switching_provider_blocks_open(monkeypatch, tmp_vault):
    _reset_caches()
    indexer.rebuild()  # stamped as provider=local

    # Swap to openai with a stub so embed_fn() does not attempt real HTTP.
    stub = MagicMock(return_value=object())
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    _reset_caches()

    with pytest.raises(RuntimeError, match="rebuild"):
        indexer.get_collection()


def test_switching_model_within_local_blocks_open(monkeypatch, tmp_vault):
    _reset_caches()
    indexer.rebuild()  # stamped with all-MiniLM-L6-v2

    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "BAAI/bge-m3")
    _reset_caches()

    with pytest.raises(RuntimeError, match="rebuild"):
        indexer.get_collection()


def test_legacy_collection_without_stamp_is_tolerated(monkeypatch, tmp_vault):
    """Collections created before this change have no stamp metadata — don't
    break existing users on upgrade. They'll only hit an error if they also
    change provider/model, which re-index fixes anyway."""
    _reset_caches()
    indexer.rebuild()
    col = indexer.get_collection()
    # Simulate a pre-stamp collection by wiping metadata in place.
    col.modify(metadata={})
    _reset_caches()

    # Should not raise — legacy collections are tolerated.
    indexer.get_collection()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_index_stamp.py -v`
Expected: FAIL on all four — no stamp is written, no check exists yet.

- [ ] **Step 3: Implement stamp write + check in `indexer.py`**

Add a helper near the other small utilities (right after `embed_fn()`):

```python
def _current_stamp() -> dict[str, str]:
    cfg = _get_cfg()
    return {
        "embed_provider": cfg.embed_provider,
        "embed_model": cfg.embed_model,
        "embed_dimensions": str(cfg.embed_dimensions) if cfg.embed_dimensions else "",
    }


def _check_stamp(col) -> None:
    cfg = _get_cfg()
    meta = col.metadata or {}
    stored_provider = meta.get("embed_provider")
    stored_model = meta.get("embed_model")
    # Legacy collections (pre-stamp) are tolerated.
    if not stored_provider and not stored_model:
        return
    if stored_provider != cfg.embed_provider or stored_model != cfg.embed_model:
        raise RuntimeError(
            "Index was built with "
            f"provider={stored_provider!r}, model={stored_model!r}, but current "
            f"config is provider={cfg.embed_provider!r}, model={cfg.embed_model!r}. "
            "Rebuild with:\n"
            "  rm -rf $OBSIDIAN_INDEX_DIR/index && second-brain-mcp rebuild"
        )
```

Replace `get_collection()`:

```python
def get_collection():
    cfg = _get_cfg()
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(cfg.index_dir / "index"))
    try:
        col = client.get_collection(COLLECTION, embedding_function=embed_fn())
        _check_stamp(col)
        return col
    except RuntimeError:
        raise
    except Exception:
        return client.create_collection(
            COLLECTION,
            embedding_function=embed_fn(),
            metadata=_current_stamp(),
        )
```

Replace `reset_collection()`:

```python
def reset_collection():
    cfg = _get_cfg()
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(cfg.index_dir / "index"))
    with contextlib.suppress(Exception):
        client.delete_collection(COLLECTION)
    return client.create_collection(
        COLLECTION,
        embedding_function=embed_fn(),
        metadata=_current_stamp(),
    )
```

Note on the `try/except` in `get_collection`: the `except RuntimeError: raise` clause is essential. Chroma raises a bare `Exception` when the collection is absent, but our own `_check_stamp` raises `RuntimeError` when the stamp mismatches. Without the re-raise, the outer `except Exception` would swallow the stamp error and silently create a new collection.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_index_stamp.py tests/test_indexer_smoke.py -v`
Expected: ALL pass. Smoke tests keep working because the stamp is written and read against the same `cfg`.

- [ ] **Step 5: Commit**

```bash
git add src/second_brain_mcp/indexer.py tests/test_index_stamp.py
git commit -m "feat(indexer): stamp collection with provider/model, block cross-provider opens"
```

---

## Task 5: Surface `embed_provider` in `stats()`

**Files:**
- Modify: `src/second_brain_mcp/indexer.py` — `stats()`
- Modify: `tests/test_indexer_smoke.py` — extend assertion

- [ ] **Step 1: Extend an existing smoke test**

Append to `tests/test_indexer_smoke.py`:

```python
def test_stats_reports_provider(tmp_vault):
    indexer.rebuild()
    s = indexer.stats()
    assert s["embed_provider"] == "local"
    assert s["embed_model"] == "sentence-transformers/all-MiniLM-L6-v2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_indexer_smoke.py::test_stats_reports_provider -v`
Expected: FAIL with `KeyError: 'embed_provider'`.

- [ ] **Step 3: Update `stats()` in `indexer.py`**

In the `stats()` function, the returned dict currently has `embed_model`, `embed_device`. Add `embed_provider`:

```python
    return {
        "notes": len(by_rel),
        "chunks": len(metas),
        "vault": str(cfg.vault),
        "index_dir": str(cfg.index_dir),
        "embed_provider": cfg.embed_provider,
        "embed_model": cfg.embed_model,
        "embed_device": cfg.embed_device,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_indexer_smoke.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add src/second_brain_mcp/indexer.py tests/test_indexer_smoke.py
git commit -m "feat(indexer): surface embed_provider in stats()"
```

---

## Task 6: Update `docs/CUSTOMIZE.md`

**Files:**
- Modify: `docs/CUSTOMIZE.md`

- [ ] **Step 1: Rewrite the env-vars table**

Replace the table under `## Environment variables` with:

```markdown
| Variable                       | Default                      | Purpose                                                                               |
|--------------------------------|------------------------------|---------------------------------------------------------------------------------------|
| `OBSIDIAN_VAULT`               | —                            | **Required.** Absolute path to your Obsidian vault.                                   |
| `OBSIDIAN_INDEX_DIR`           | `~/.second-brain-mcp/`       | Where the ChromaDB persistent dir and `backlinks.json` live.                          |
| `OBSIDIAN_EMBED_PROVIDER`      | `local`                      | `local` or `openai`. Selects embedding backend.                                       |
| `OBSIDIAN_EMBED_MODEL`         | `BAAI/bge-m3`                | Local: HuggingFace model id. API: OpenAI-style `model` string.                        |
| `OBSIDIAN_EMBED_DEVICE`        | auto (`mps`/`cuda`/`cpu`)    | Local-only. Torch device for embedding. Ignored when `provider=openai`.               |
| `OBSIDIAN_EMBED_API_KEY`       | —                            | **Required when `provider=openai`.** API key for the endpoint.                        |
| `OBSIDIAN_EMBED_API_URL`       | —                            | **Required when `provider=openai`.** Base URL of the OpenAI-compatible endpoint.      |
| `OBSIDIAN_EMBED_DIMENSIONS`    | —                            | Optional (provider=openai). Override embedding dimension if the model supports it.    |
```

- [ ] **Step 2: Rename the "Alternative embedders" section**

Rename the heading `## Alternative embedders` to `## Local embedder (default)`. Content (the table of `bge-m3` / `mpnet` / `MiniLM`) stays the same.

- [ ] **Step 3: Add the "API embedder" section**

Insert before `## How to switch embedders`:

````markdown
---

## API embedder (OpenAI-compatible)

If you'd rather not keep the embedder on disk (thin client, no GPU,
CI, or you already pay for an embeddings API), point `second-brain-mcp`
at any OpenAI-compatible `/v1/embeddings` endpoint.

**Recipe — Cloud.ru Foundation Models API + Qwen3-Embedding-0.6B:**

```bash
claude mcp remove second-brain  # if re-registering
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$HOME/obsidian/vault" \
  -e OBSIDIAN_EMBED_PROVIDER=openai \
  -e OBSIDIAN_EMBED_API_URL=https://foundation-models.api.cloud.ru/v1 \
  -e OBSIDIAN_EMBED_API_KEY="$FM_API_KEY" \
  -e OBSIDIAN_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B \
  -- uvx second-brain-mcp serve
```

After registering, drop the old local index and rebuild:

```bash
rm -rf $OBSIDIAN_INDEX_DIR/index
uvx second-brain-mcp rebuild
```

**Tested endpoints:**

| Provider                           | Base URL                                             | Known-good model                 |
|------------------------------------|------------------------------------------------------|----------------------------------|
| Cloud.ru Foundation Models API     | `https://foundation-models.api.cloud.ru/v1`          | `Qwen/Qwen3-Embedding-0.6B`      |
| OpenAI                             | `https://api.openai.com/v1`                          | `text-embedding-3-small`         |

Any OpenAI-compatible endpoint should work — these are just the ones
we've run `rebuild` against. If your endpoint's model returns a
non-standard dimension, set `OBSIDIAN_EMBED_DIMENSIONS` to match.

**Index compatibility.** Switching providers or models invalidates the
existing Chroma index — embeddings from different models are not
comparable, and `second-brain-mcp` refuses to open a collection stamped
with a different provider/model. The fix is always the same: remove
`$OBSIDIAN_INDEX_DIR/index` and `rebuild`.
````

- [ ] **Step 4: Update the "How to switch embedders" section**

In `## How to switch embedders`, reword the intro paragraph to cover both axes:

```markdown
Switching to a different model — or to a different provider — changes
the embedding semantics (and often the dimensionality), so the old
index is unusable. The recipe is the same either way:
```

The example block below stays; keep the existing `OBSIDIAN_EMBED_MODEL` example, and add a second example right below it switching provider:

````markdown
Switch to an API-backed embedder:

```bash
claude mcp remove second-brain
claude mcp add -s user second-brain \
  -e OBSIDIAN_VAULT="$HOME/obsidian/vault" \
  -e OBSIDIAN_EMBED_PROVIDER=openai \
  -e OBSIDIAN_EMBED_API_URL=https://foundation-models.api.cloud.ru/v1 \
  -e OBSIDIAN_EMBED_API_KEY="$FM_API_KEY" \
  -e OBSIDIAN_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B \
  -- uvx second-brain-mcp serve

rm -rf $OBSIDIAN_INDEX_DIR/index
uvx second-brain-mcp rebuild
```
````

- [ ] **Step 5: Commit**

```bash
git add docs/CUSTOMIZE.md
git commit -m "docs: document OpenAI-compatible API embedder provider"
```

---

## Task 7: Update `README.md` and `ROADMAP.md`

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Add a one-line pointer in `README.md`**

Find the line in the "30-second quick start" that reads:

```
First run downloads the bge-m3 embedder (~2.3 GB) on the first tool call
— roughly 5 seconds after that. See [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md)
for lighter models.
```

Replace with:

```
First run downloads the bge-m3 embedder (~2.3 GB) on the first tool call
— roughly 5 seconds after that. See [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md)
for lighter models, or to point at an OpenAI-compatible embeddings API
(Cloud.ru FM API, OpenAI, self-hosted Infinity) instead of the local
model.
```

- [ ] **Step 2: Update `ROADMAP.md`**

Read the file. If there's a line mentioning "remote embedders", "API embedders", "OpenAI-compatible embedder", or similar, mark it done (e.g. move under a `## Done in v1.1` section or strike it) and note the date `2026-04-16`. If no such line exists, skip this file.

- [ ] **Step 3: Commit**

```bash
git add README.md ROADMAP.md
git commit -m "docs: pointer to API embedder in README; mark roadmap item done"
```

---

## Task 8: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: ALL tests PASS. No warnings about missing imports.

- [ ] **Step 2: Lint**

Run: `uv run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Smoke-run local mode**

```bash
export OBSIDIAN_VAULT=$(mktemp -d)
echo "# Hello" > "$OBSIDIAN_VAULT/hello.md"
export OBSIDIAN_INDEX_DIR=$(mktemp -d)
export OBSIDIAN_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
export OBSIDIAN_EMBED_DEVICE=cpu
uv run second-brain-mcp rebuild
uv run python -c "from second_brain_mcp import indexer; print(indexer.stats())"
```
Expected: stats dict includes `'embed_provider': 'local'` and `'notes': 1`.

- [ ] **Step 4: Smoke-check fail-fast for openai misconfig**

```bash
unset OBSIDIAN_EMBED_MODEL OBSIDIAN_EMBED_DEVICE
export OBSIDIAN_EMBED_PROVIDER=openai
uv run python -c "from second_brain_mcp import config; config.load()" 2>&1 | head -3
```
Expected: `RuntimeError` mentioning both `OBSIDIAN_EMBED_API_KEY` and `OBSIDIAN_EMBED_API_URL`.

- [ ] **Step 5: Clean up smoke artifacts**

```bash
rm -rf "$OBSIDIAN_VAULT" "$OBSIDIAN_INDEX_DIR"
unset OBSIDIAN_VAULT OBSIDIAN_INDEX_DIR OBSIDIAN_EMBED_PROVIDER
```

No commit needed — verification only.

---

## Self-review checklist (done inline)

- **Spec coverage:** every section of the spec maps to a task.
  - env vars + validation → Task 2
  - `embed_fn()` branching → Task 3
  - collection stamp → Task 4
  - `stats()` surfacing provider → Task 5
  - dep on `openai` → Task 1
  - CUSTOMIZE.md restructure → Task 6
  - README pointer + roadmap → Task 7
  - tests for all the above → Tasks 2/3/4/5
  - error-handling policy (no retry wrapper) → reflected by absence of any such task
- **Placeholders:** none. Every code step contains the actual code. Every command has expected output.
- **Type consistency:** `embed_provider`, `embed_model`, `embed_api_key`, `embed_api_url`, `embed_dimensions` — same names in `Config`, validation, tests, `embed_fn()`, stamp, and `stats()`.
