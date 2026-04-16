# tests/test_index_stamp.py
"""Collection provider/model stamp blocks cross-provider searches."""
from unittest.mock import MagicMock

import pytest

from second_brain_mcp import indexer


def test_stamp_written_on_rebuild(tmp_vault, reset_indexer_caches):
    indexer.rebuild()
    col = indexer.get_collection()
    meta = col.metadata or {}
    assert meta.get("embed_provider") == "local"
    assert meta.get("embed_model") == "sentence-transformers/all-MiniLM-L6-v2"


def test_switching_provider_blocks_open(monkeypatch, tmp_vault, reset_indexer_caches):
    indexer.rebuild()  # stamped as provider=local

    stub = MagicMock(return_value=object())
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)
    monkeypatch.setenv("OBSIDIAN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    reset_indexer_caches()

    with pytest.raises(RuntimeError, match="rebuild") as exc_info:
        indexer.get_collection()

    # Message must surface both the stored and current provider/model so the
    # user knows what changed without digging through env.
    msg = str(exc_info.value)
    assert "local" in msg
    assert "openai" in msg
    assert "all-MiniLM-L6-v2" in msg
    assert "Qwen" in msg


def test_dimensions_only_change_is_not_blocked(monkeypatch, tmp_vault, reset_indexer_caches):
    """Stamp records dimensions but _check_stamp compares only provider+model.
    A dimensions-only override is harmless for the same model, so it must not
    raise. This test pins that behavior so a future refactor doesn't quietly
    start comparing dimensions."""
    indexer.rebuild()

    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "512")
    reset_indexer_caches()

    indexer.get_collection()  # must not raise


def test_switching_model_within_local_blocks_open(monkeypatch, tmp_vault, reset_indexer_caches):
    indexer.rebuild()  # stamped with all-MiniLM-L6-v2

    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "BAAI/bge-m3")
    reset_indexer_caches()

    with pytest.raises(RuntimeError, match="rebuild"):
        indexer.get_collection()


def test_legacy_collection_without_stamp_is_tolerated(tmp_vault, reset_indexer_caches):
    """Collections created before this change have no stamp metadata — don't
    break existing users on upgrade. They'll only hit an error if they also
    change provider/model, which re-index fixes anyway."""
    indexer.rebuild()
    col = indexer.get_collection()
    # Empty dict rejected by Chroma; _legacy key simulates a pre-stamp collection.
    col.modify(metadata={"_legacy": "true"})
    reset_indexer_caches()

    indexer.get_collection()  # must not raise
