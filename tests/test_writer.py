# tests/test_writer.py
"""Unit tests for writer.py — the per-op mutation functions.

These bypass the MCP layer: they call writer functions directly, so they're
fast and don't need a server subprocess.
"""
import pytest

from second_brain_mcp import writer
from second_brain_mcp.config import load as load_config


@pytest.fixture
def cfg(tmp_vault, reset_indexer_caches):
    return load_config()


def test_create_new_note(cfg, tmp_vault):
    result = writer.op_create(
        cfg,
        path="knowledge/new-fact.md",
        body="This is new.",
        frontmatter={"type": "knowledge", "confidence": "high"},
    )
    assert result["ok"] and result["changed"]
    written = (tmp_vault / "knowledge/new-fact.md").read_text()
    assert written.startswith("---\n")
    assert "type: knowledge" in written
    assert "This is new." in written


def test_create_existing_without_overwrite_fails(cfg, tmp_vault):
    (tmp_vault / "knowledge").mkdir(exist_ok=True)
    (tmp_vault / "knowledge/x.md").write_text("original")
    with pytest.raises(writer.WriteError):
        writer.op_create(cfg, path="knowledge/x.md", body="new")


def test_create_overwrite_replaces(cfg, tmp_vault):
    (tmp_vault / "knowledge").mkdir(exist_ok=True)
    (tmp_vault / "knowledge/x.md").write_text("original")
    result = writer.op_create(
        cfg, path="knowledge/x.md", body="new body", overwrite=True
    )
    assert result["overwrote"] is True
    assert "new body" in (tmp_vault / "knowledge/x.md").read_text()


def test_append_preserves_frontmatter(cfg, tmp_vault):
    result = writer.op_append(cfg, path="note-alpha.md", text="AMENDED.")
    assert result["ok"] and result["changed"]
    text = (tmp_vault / "note-alpha.md").read_text()
    assert text.startswith("---\n")
    assert "type: knowledge" in text
    assert text.rstrip().endswith("AMENDED.")


def test_prepend_inserts_after_frontmatter(cfg, tmp_vault):
    writer.op_prepend(cfg, path="note-alpha.md", text="LEAD.")
    text = (tmp_vault / "note-alpha.md").read_text()
    body_start = text.index("---\n", 4) + len("---\n")
    body = text[body_start:].lstrip("\n")
    assert body.startswith("LEAD.")


def test_replace_body_keeps_frontmatter(cfg, tmp_vault):
    writer.op_replace_body(cfg, path="note-alpha.md", body="totally new body")
    text = (tmp_vault / "note-alpha.md").read_text()
    assert "type: knowledge" in text
    assert "totally new body" in text
    assert "elephants" not in text


def test_replace_text_literal(cfg, tmp_vault):
    result = writer.op_replace_text(
        cfg, path="note-alpha.md", find="elephants", replace="whales"
    )
    assert result["replacements"] == 1
    assert "whales" in (tmp_vault / "note-alpha.md").read_text()


def test_replace_text_regex(cfg, tmp_vault):
    result = writer.op_replace_text(
        cfg, path="note-alpha.md", find=r"\belephants\b", replace="whales", regex=True
    )
    assert result["replacements"] == 1


def test_replace_text_invalid_regex_errors(cfg):
    with pytest.raises(writer.WriteError):
        writer.op_replace_text(
            cfg, path="note-alpha.md", find="[unclosed", replace="x", regex=True
        )


def test_set_frontmatter_merge_and_remove(cfg, tmp_vault):
    writer.op_set_frontmatter(
        cfg,
        path="note-alpha.md",
        updates={"verified": "2026-04-16", "confidence": "medium"},
        remove_keys=["type"],
    )
    text = (tmp_vault / "note-alpha.md").read_text()
    assert "verified: '2026-04-16'" in text or "verified: 2026-04-16" in text
    assert "confidence: medium" in text
    assert "type: knowledge" not in text


def test_delete_removes_file(cfg, tmp_vault):
    path = tmp_vault / "note-beta.md"
    assert path.exists()
    writer.op_delete(cfg, path="note-beta.md")
    assert not path.exists()


def test_rename_moves_file(cfg, tmp_vault):
    writer.op_rename(cfg, path="note-beta.md", new_path="renamed/note-beta.md")
    assert not (tmp_vault / "note-beta.md").exists()
    assert (tmp_vault / "renamed/note-beta.md").exists()


def test_rename_refuses_update_wikilinks(cfg):
    with pytest.raises(writer.WriteError):
        writer.op_rename(
            cfg, path="note-beta.md", new_path="x.md", update_wikilinks=True
        )


def test_rename_refuses_overwrite_destination(cfg, tmp_vault):
    (tmp_vault / "note-beta.md").exists()
    with pytest.raises(writer.WriteError):
        writer.op_rename(cfg, path="note-alpha.md", new_path="note-beta.md")


def test_dry_run_does_not_write(cfg, tmp_vault):
    before = (tmp_vault / "note-alpha.md").read_text()
    result = writer.op_append(cfg, path="note-alpha.md", text="X", dry_run=True)
    assert result["before"] == before
    assert "X" in result["after"]
    assert (tmp_vault / "note-alpha.md").read_text() == before


def test_path_traversal_rejected(cfg):
    for bad in ["../../etc/passwd", "/etc/passwd", "../outside.md"]:
        with pytest.raises(writer.WriteError):
            writer.op_create(cfg, path=bad, body="x")


def test_atomic_write_leaves_no_tmp_on_success(cfg, tmp_vault):
    writer.op_append(cfg, path="note-alpha.md", text="x")
    # No leftover tmp files next to the note.
    leftovers = [p.name for p in tmp_vault.iterdir() if ".tmp-" in p.name]
    assert leftovers == []


def test_dispatcher_unknown_op(cfg):
    with pytest.raises(writer.WriteError):
        writer.apply(cfg, "nonsense", {"path": "note-alpha.md"})


def test_dispatcher_dispatches_create(cfg, tmp_vault):
    result = writer.apply(cfg, "create", {"path": "a/b.md", "body": "hi"})
    assert result["ok"]
    assert (tmp_vault / "a/b.md").exists()
