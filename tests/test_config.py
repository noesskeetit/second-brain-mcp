# tests/test_config.py
from pathlib import Path

import pytest

from second_brain_mcp import config


def test_vault_required(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    with pytest.raises(RuntimeError, match="OBSIDIAN_VAULT"):
        config.load()


def test_vault_resolves(monkeypatch, tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    cfg = config.load()
    assert cfg.vault == vault.resolve()
    assert cfg.index_dir == Path.home() / ".second-brain-mcp"
    assert cfg.embed_model == "BAAI/bge-m3"
    assert cfg.embed_device in {"mps", "cuda", "cpu"}


def test_custom_index_dir_and_embedder(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_INDEX_DIR", str(tmp_path / "idx"))
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("OBSIDIAN_EMBED_DEVICE", "cpu")
    cfg = config.load()
    assert cfg.index_dir == tmp_path / "idx"
    assert cfg.embed_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert cfg.embed_device == "cpu"


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
