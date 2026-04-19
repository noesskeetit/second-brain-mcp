# tests/test_indexer_smoke.py
import time

from second_brain_mcp import indexer


def test_rebuild_indexes_two_notes(tmp_vault):
    stats = indexer.rebuild()
    assert stats["notes"] == 2  # _index.md excluded
    assert stats["chunks"] >= 2


def test_search_finds_alpha(tmp_vault):
    indexer.rebuild()
    hits = indexer.search("elephants", n_results=3)
    titles = [h["title"] for h in hits]
    assert any("Alpha" in t for t in titles)


def test_type_filter(tmp_vault):
    indexer.rebuild()
    hits = indexer.search("anything", n_results=5, type_filter="insight")
    assert all(h["fm_type"] == "insight" for h in hits)


def test_incremental_picks_up_new_note(tmp_vault):
    indexer.rebuild()
    (tmp_vault / "note-gamma.md").write_text(
        "---\ntype: knowledge\n---\n# Note Gamma\n\nGamma discusses submarines.\n"
    )
    # Ensure mtime differs enough for the filesystem
    time.sleep(0.1)
    res = indexer.index_incremental()
    assert res["added_or_updated"] >= 1
    hits = indexer.search("submarine", n_results=3)
    assert any("Gamma" in h["title"] for h in hits)


def test_incremental_detects_deletion(tmp_vault):
    indexer.rebuild()
    (tmp_vault / "note-beta.md").unlink()
    res = indexer.index_incremental()
    assert res["deleted"] >= 1


def test_index_md_excluded_from_vector(tmp_vault):
    indexer.rebuild()
    hits = indexer.search("Index", n_results=10)
    assert not any(h["rel"] == "_index.md" for h in hits)


def test_stats_reports_provider(tmp_vault):
    indexer.rebuild()
    s = indexer.stats()
    assert s["embed_provider"] == "openai"
    assert s["embed_model"] == "fake-test-model"
    # embed_device was removed when the on-device embedder was dropped.
    assert "embed_device" not in s
