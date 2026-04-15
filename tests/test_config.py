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
