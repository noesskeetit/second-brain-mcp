# tests/test_config.py
"""Config tests — API-only embedder, no local/device knobs."""
from pathlib import Path

import pytest

from second_brain_mcp import config

# All API-mode tests need the same three creds. Centralising keeps them
# from drifting and from hiding regressions behind copy-paste.
API_ENV = {
    "OBSIDIAN_EMBED_API_KEY": "sk-test",
    "OBSIDIAN_EMBED_API_URL": "https://example.com/v1",
    "OBSIDIAN_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B",
}


def _set_api_env(monkeypatch):
    for k, v in API_ENV.items():
        monkeypatch.setenv(k, v)


def test_vault_required(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    with pytest.raises(RuntimeError, match="OBSIDIAN_VAULT"):
        config.load()


def test_vault_resolves(monkeypatch, tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    _set_api_env(monkeypatch)
    cfg = config.load()
    assert cfg.vault == vault.resolve()
    assert cfg.index_dir == Path.home() / ".second-brain-mcp"
    assert cfg.embed_provider == "openai"  # only supported provider
    assert cfg.embed_model == "Qwen/Qwen3-Embedding-0.6B"


def test_api_requires_all_three(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    # No API_KEY/URL/MODEL — should list all three missing.
    with pytest.raises(RuntimeError) as exc_info:
        config.load()
    msg = str(exc_info.value)
    assert "OBSIDIAN_EMBED_API_KEY" in msg
    assert "OBSIDIAN_EMBED_API_URL" in msg
    assert "OBSIDIAN_EMBED_MODEL" in msg


def test_api_requires_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "m")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_API_KEY"):
        config.load()


def test_api_requires_url(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "m")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_API_URL"):
        config.load()


def test_api_requires_model(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.com/v1")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_MODEL"):
        config.load()


def test_api_loads_fully(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    _set_api_env(monkeypatch)
    cfg = config.load()
    assert cfg.embed_provider == "openai"
    assert cfg.embed_api_key == "sk-test"
    assert cfg.embed_api_url == "https://example.com/v1"
    assert cfg.embed_model == "Qwen/Qwen3-Embedding-0.6B"


def test_custom_index_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_INDEX_DIR", str(tmp_path / "idx"))
    _set_api_env(monkeypatch)
    cfg = config.load()
    assert cfg.index_dir == tmp_path / "idx"


def test_dimensions_parsed_as_positive_int(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    _set_api_env(monkeypatch)
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "512")
    cfg = config.load()
    assert cfg.embed_dimensions == 512


def test_dimensions_rejects_non_numeric(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    _set_api_env(monkeypatch)
    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "abc")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()


def test_dimensions_rejects_zero_and_negative(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    _set_api_env(monkeypatch)

    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "0")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()

    monkeypatch.setenv("OBSIDIAN_EMBED_DIMENSIONS", "-5")
    with pytest.raises(RuntimeError, match="OBSIDIAN_EMBED_DIMENSIONS"):
        config.load()


def test_allow_unauth_host_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    _set_api_env(monkeypatch)

    # Default: off.
    cfg = config.load()
    assert cfg.allow_unauth_host is False

    # Explicit "1" → on.
    monkeypatch.setenv("OBSIDIAN_ALLOW_UNAUTH_HOST", "1")
    cfg = config.load()
    assert cfg.allow_unauth_host is True

    # Any other value → off. This keeps "true"/"yes" from being a
    # half-working bypass — there's one magic string, not five.
    for val in ["0", "true", "yes", ""]:
        monkeypatch.setenv("OBSIDIAN_ALLOW_UNAUTH_HOST", val)
        cfg = config.load()
        assert cfg.allow_unauth_host is False, val
