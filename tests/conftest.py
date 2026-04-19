# tests/conftest.py
"""Shared test fixtures.

The embedder is API-only in production (no torch, no local models). Tests
intercept every embedding call through a deterministic bag-of-words fake
so that:
  * rebuild/incremental mechanics run end-to-end against a real ChromaDB,
  * semantic-search tests stay valid without hitting a network,
  * no model is downloaded or shipped alongside the test suite.

The interception point is `OpenAIEmbeddingFunction.__call__` — the class
and its constructor stay real (so code paths that inspect the embedder
still see "openai"), but the actual HTTP call is replaced with the fake.
Tests that explicitly replace the whole class (test_indexer_embed_fn.py)
bypass this automatically.
"""
from __future__ import annotations

import math

import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

# Covers every token that smoke tests ask about.
_TEST_VOCAB = [
    "elephants",
    "trains",
    "submarines",
    "note",
    "alpha",
    "beta",
    "gamma",
    "index",
    "anything",
    "knowledge",
    "insight",
]


class _FakeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic bag-of-words embedder. Test-only."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors: list[list[float]] = []
        for text in input:
            lower = text.lower()
            vec = [1.0 if word in lower else 0.0 for word in _TEST_VOCAB]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    @staticmethod
    def name() -> str:
        return "fake-bag-of-words"


_FAKE = _FakeEmbeddingFunction()


@pytest.fixture(autouse=True)
def _stub_openai_ef(monkeypatch):
    """Route every OpenAI embedding call to the fake. Autouse so no test can
    accidentally make a network request. Tests that replace the whole class
    (via monkeypatch.setattr on the module attribute) aren't affected — their
    replacement wins because it's a different object."""
    from chromadb.utils import embedding_functions

    def fake_call(self, input):
        return _FAKE(input)

    monkeypatch.setattr(
        embedding_functions.OpenAIEmbeddingFunction,
        "__call__",
        fake_call,
    )


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
    # Dummy creds — the autouse fixture intercepts before any HTTP happens.
    monkeypatch.setenv("OBSIDIAN_EMBED_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("OBSIDIAN_EMBED_API_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OBSIDIAN_EMBED_MODEL", "fake-test-model")

    from second_brain_mcp import indexer

    indexer._get_cfg.cache_clear()
    indexer._EMBED_FN = None
    return vault


@pytest.fixture
def reset_indexer_caches():
    """Clear indexer's cached config and embed-fn so env-var changes take effect."""
    from second_brain_mcp import indexer

    def _reset():
        indexer._get_cfg.cache_clear()
        indexer._EMBED_FN = None

    _reset()
    yield _reset
    _reset()
