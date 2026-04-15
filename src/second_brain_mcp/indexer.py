"""Semantic index over an Obsidian vault.

Walks the vault, parses YAML frontmatter, extracts [[wikilinks]], chunks notes
(small notes kept whole, bigger ones split by H2/H3 headers), embeds via
sentence-transformers, and stores the result in a ChromaDB collection next to
a backlinks sidecar JSON. Designed for incremental reindex via mtime diffing.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import chromadb
import yaml
from chromadb.utils import embedding_functions

from .config import Config
from .config import load as load_config

COLLECTION = "obsidian_notes"

CHUNK_SMALL_THRESHOLD = 1500
CHUNK_TARGET_CHARS = 1400
CHUNK_OVERLAP = 180

WIKILINK_RE = re.compile(r"\[\[([^\]\|#^]+)(?:[#^][^\]\|]*)?(?:\|[^\]]*)?\]\]")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@functools.lru_cache(maxsize=1)
def _get_cfg() -> Config:
    return load_config()


# _index.md is intentionally excluded — it is served whole via the MCP overview
# tool, and its long keyword-heavy content would otherwise dominate rankings.
# Obsidian sync sometimes leaves conflict artifacts like "_index 1.md".
def _is_excluded(name: str) -> bool:
    return name.startswith("_index") and name.endswith(".md")


_EMBED_FN = None


def embed_fn():
    global _EMBED_FN
    if _EMBED_FN is None:
        cfg = _get_cfg()
        _EMBED_FN = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=cfg.embed_model,
            device=cfg.embed_device,
        )
    return _EMBED_FN


def get_collection():
    cfg = _get_cfg()
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(cfg.index_dir / "index"))
    try:
        return client.get_collection(COLLECTION, embedding_function=embed_fn())
    except Exception:
        return client.create_collection(COLLECTION, embedding_function=embed_fn())


def reset_collection():
    cfg = _get_cfg()
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(cfg.index_dir / "index"))
    with contextlib.suppress(Exception):
        client.delete_collection(COLLECTION)
    return client.create_collection(COLLECTION, embedding_function=embed_fn())


@dataclass
class Note:
    path: Path  # absolute
    rel: str  # relative to vault root (POSIX)
    title: str
    mtime: float
    frontmatter: dict
    body: str
    wikilinks: list[str]


def parse_note(path: Path) -> Note:
    cfg = _get_cfg()
    text = path.read_text(encoding="utf-8", errors="replace")
    fm: dict = {}
    body = text
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
            if not isinstance(fm, dict):
                fm = {}
        except yaml.YAMLError:
            fm = {}
        body = text[m.end() :]

    # Title: first H1 if present, otherwise filename stem
    title = path.stem
    for line in body.splitlines()[:10]:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    wikilinks = sorted(set(WIKILINK_RE.findall(body)))

    return Note(
        path=path,
        rel=str(path.relative_to(cfg.vault)).replace(os.sep, "/"),
        title=title,
        mtime=path.stat().st_mtime,
        frontmatter=fm,
        body=body.strip(),
        wikilinks=wikilinks,
    )


def chunk_note(note: Note) -> list[dict]:
    body = note.body
    header = f"# {note.title}\n\n" if not body.lstrip().startswith("# ") else ""
    prepared = header + body

    if len(prepared) <= CHUNK_SMALL_THRESHOLD:
        return [{"chunk_index": 0, "text": prepared}]

    # Split by H2/H3 headers while keeping the header attached to its section
    sections: list[str] = []
    current: list[str] = []
    for line in prepared.splitlines():
        if re.match(r"^#{2,3}\s", line) and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())

    chunks: list[dict] = []
    buf = ""
    for section in sections:
        if not section:
            continue
        if not buf:
            buf = section
        elif len(buf) + 2 + len(section) <= CHUNK_TARGET_CHARS:
            buf = buf + "\n\n" + section
        else:
            chunks.append({"chunk_index": len(chunks), "text": buf})
            buf = section

    if buf:
        chunks.append({"chunk_index": len(chunks), "text": buf})

    # If a single section was still too big, slice it with overlap
    final: list[dict] = []
    for ch in chunks:
        txt = ch["text"]
        if len(txt) <= CHUNK_TARGET_CHARS * 1.5:
            final.append({"chunk_index": len(final), "text": txt})
            continue
        start = 0
        while start < len(txt):
            end = min(len(txt), start + CHUNK_TARGET_CHARS)
            final.append({"chunk_index": len(final), "text": txt[start:end]})
            if end == len(txt):
                break
            start = end - CHUNK_OVERLAP

    return final


def chunk_id(rel: str, chunk_index: int) -> str:
    h = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]
    return f"{h}_{chunk_index}"


def collect_vault_notes() -> list[Note]:
    cfg = _get_cfg()
    notes: list[Note] = []
    if not cfg.vault.exists():
        return notes
    for md in cfg.vault.rglob("*.md"):
        if _is_excluded(md.name):
            continue
        try:
            notes.append(parse_note(md))
        except Exception as e:
            print(f"  skip {md}: {e}", file=sys.stderr)
    return notes


def _index_map_from_collection(col) -> dict[str, float]:
    """Return {rel_path: max(mtime) across its chunks} from the collection."""
    out: dict[str, float] = {}
    got = col.get(include=["metadatas"])
    for meta in got.get("metadatas") or []:
        rel = meta.get("rel")
        mt = float(meta.get("mtime", 0))
        if rel is None:
            continue
        if rel not in out or mt > out[rel]:
            out[rel] = mt
    return out


def _delete_by_rel(col, rel: str):
    with contextlib.suppress(Exception):
        col.delete(where={"rel": rel})


def _add_note(col, note: Note):
    chunks = chunk_note(note)
    if not chunks:
        return 0

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []

    fm = note.frontmatter or {}
    for ch in chunks:
        ids.append(chunk_id(note.rel, ch["chunk_index"]))
        docs.append(ch["text"])
        metas.append(
            {
                "rel": note.rel,
                "title": note.title,
                "chunk_index": ch["chunk_index"],
                "mtime": note.mtime,
                "fm_type": str(fm.get("type", "")),
                "fm_verified": str(fm.get("verified", "")),
                "fm_confidence": str(fm.get("confidence", "")),
                "outlinks": ",".join(note.wikilinks),
            }
        )

    col.add(ids=ids, documents=docs, metadatas=metas)
    return len(chunks)


def build_backlinks(notes: Iterable[Note]) -> dict[str, list[str]]:
    """For every wikilink target, list the rel-paths of notes that reference it.

    Targets are the raw [[name]] strings. Matching can use either the referenced
    note's title or its filename stem.
    """
    back: dict[str, set[str]] = {}
    for n in notes:
        for link in n.wikilinks:
            back.setdefault(link.strip(), set()).add(n.rel)
    return {k: sorted(v) for k, v in back.items()}


def save_backlinks(notes: Iterable[Note]):
    cfg = _get_cfg()
    back = build_backlinks(notes)
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    (cfg.index_dir / "backlinks.json").write_text(
        json.dumps(back, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rebuild() -> dict:
    col = reset_collection()
    notes = collect_vault_notes()
    total_chunks = 0
    for n in notes:
        total_chunks += _add_note(col, n)
    save_backlinks(notes)
    return {"mode": "rebuild", "notes": len(notes), "chunks": total_chunks}


def index_incremental() -> dict:
    col = get_collection()
    notes = collect_vault_notes()
    current = {n.rel: n for n in notes}
    indexed = _index_map_from_collection(col)

    to_add: list[Note] = []
    to_delete: list[str] = []
    for rel, mt in indexed.items():
        if rel not in current:
            to_delete.append(rel)
        elif current[rel].mtime > mt + 0.0001:
            to_delete.append(rel)
            to_add.append(current[rel])
    for rel, n in current.items():
        if rel not in indexed:
            to_add.append(n)

    for rel in to_delete:
        _delete_by_rel(col, rel)

    added_chunks = 0
    for n in to_add:
        added_chunks += _add_note(col, n)

    # Sidecar backlinks always reflects the current vault
    save_backlinks(notes)

    return {
        "mode": "incremental",
        "notes_total": len(notes),
        "added_or_updated": len(to_add),
        "deleted": len(to_delete),
        "chunks_added": added_chunks,
    }


def search(query: str, n_results: int = 5, type_filter: str | None = None) -> list[dict]:
    col = get_collection()
    kwargs: dict = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if type_filter:
        kwargs["where"] = {"fm_type": type_filter}
    res = col.query(**kwargs)

    hits = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0], strict=False
    ):
        hits.append(
            {
                "rel": meta.get("rel"),
                "title": meta.get("title"),
                "fm_type": meta.get("fm_type") or None,
                "fm_confidence": meta.get("fm_confidence") or None,
                "similarity": round(1 - dist, 3),
                "snippet": doc.strip()[:350],
            }
        )
    return hits


def stats() -> dict:
    cfg = _get_cfg()
    col = get_collection()
    got = col.get(include=["metadatas"])
    metas = got.get("metadatas") or []
    by_rel: dict[str, float] = {}
    for m in metas:
        rel = m.get("rel")
        if rel:
            by_rel[rel] = max(by_rel.get(rel, 0), float(m.get("mtime", 0)))
    return {
        "notes": len(by_rel),
        "chunks": len(metas),
        "vault": str(cfg.vault),
        "index_dir": str(cfg.index_dir),
        "embed_model": cfg.embed_model,
        "embed_device": cfg.embed_device,
    }
