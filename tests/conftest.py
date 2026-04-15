# tests/conftest.py
import pytest


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    """Minimal vault with 2 notes + _index.md for smoke tests."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_index.md").write_text("# Index\n\n- [[note-alpha]]\n")
    (vault / "note-alpha.md").write_text(
        "---\ntype: knowledge\nconfidence: high\n---\n\n"
        "# Note Alpha\n\nAlpha talks about elephants and [[note-beta]].\n"
    )
    (vault / "note-beta.md").write_text(
        "---\ntype: insight\n---\n\n# Note Beta\n\nBeta talks about trains.\n"
    )
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    monkeypatch.setenv("OBSIDIAN_INDEX_DIR", str(tmp_path / "idx"))
    # Keep tests CPU-only and cheap — use the tiny English model.
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("OBSIDIAN_EMBED_DEVICE", "cpu")
    # Clear cached config and embedder so env changes take effect in a fresh fixture.
    from second_brain_mcp import indexer

    indexer._get_cfg.cache_clear()
    indexer._EMBED_FN = None
    return vault
