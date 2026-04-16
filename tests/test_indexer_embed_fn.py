# tests/test_indexer_embed_fn.py
"""Provider dispatch in indexer.embed_fn()."""
from unittest.mock import MagicMock

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
