# tests/test_indexer_embed_fn.py
"""embed_fn() wires the OpenAI-compatible API embedder.

The server is API-only; there's no local/sentence-transformers branch
left to exercise.
"""
from unittest.mock import MagicMock

from second_brain_mcp import indexer


def _api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")


def test_embed_fn_uses_openai(monkeypatch, tmp_path, reset_indexer_caches):
    sentinel = object()
    stub = MagicMock(return_value=sentinel)
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)

    _api_env(monkeypatch, tmp_path)
    reset_indexer_caches()

    fn = indexer.embed_fn()

    assert fn is sentinel
    stub.assert_called_once()
    kwargs = stub.call_args.kwargs
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["api_base"] == "https://example.com/v1"
    assert kwargs["model_name"] == "Qwen/Qwen3-Embedding-0.6B"
    assert "dimensions" not in kwargs


def test_embed_fn_passes_dimensions_when_set(monkeypatch, tmp_path, reset_indexer_caches):
    stub = MagicMock(return_value=object())
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)

    _api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "512")
    reset_indexer_caches()

    indexer.embed_fn()

    kwargs = stub.call_args.kwargs
    assert kwargs["dimensions"] == 512


def test_embed_fn_cached_across_calls(monkeypatch, tmp_path, reset_indexer_caches):
    stub = MagicMock(return_value=object())
    monkeypatch.setattr(indexer.embedding_functions, "OpenAIEmbeddingFunction", stub)

    _api_env(monkeypatch, tmp_path)
    reset_indexer_caches()

    a = indexer.embed_fn()
    b = indexer.embed_fn()
    assert a is b
    assert stub.call_count == 1
