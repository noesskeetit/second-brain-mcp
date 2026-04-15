"""server.py — Stdio MCP server exposing an Obsidian vault as semantic memory.

Four tools:
    obsidian_overview   — vault stats + fresh _index.md + MEMORY PROTOCOL.
                          The first tool a new session should call.
    obsidian_search     — semantic search, optional type filter.
    obsidian_read       — fetch a note whole from disk (frontmatter,
                          body, outlinks, backlinks). Always fresh.
    obsidian_backlinks  — find notes that reference a target by wikilink.

Every tool call runs a cheap mtime-based incremental reindex first, so the
agent never has to think about index freshness after external edits.

Writes to the vault are intentionally NOT exposed. A dedicated `to_obsidian`
MCP prompt surfaces a curated write workflow with human-in-the-loop approval.
"""

from __future__ import annotations

import asyncio
import functools
import json
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import indexer as idx
from . import prompts
from .config import Config
from .config import load as load_config

MEMORY_PROTOCOL = """OBSIDIAN MEMORY PROTOCOL

This MCP exposes a curated Obsidian vault as the source of truth for past
decisions, facts, preferences, people, and project context. Every note in
the vault was explicitly approved by the user before it was written.

1. AT SESSION START: you have already received the vault overview and the
   fresh _index.md above. Skim both before asking clarifying questions about
   things that might already be in memory.

2. BEFORE ANSWERING about past decisions, projects, people, facts, tools, or
   anything that sounds like prior context: call obsidian_search FIRST.
   Prefer semantic search over guessing. INTERPRETING scores: ChromaDB
   returns similarity in [-1, 1]; 0.3+ = strong hit, 0.1-0.3 = weak but
   possibly relevant, below 0 = clean miss (do NOT cite as found).

3. WHEN A HIT LOOKS PROMISING: call obsidian_read on its path to get the
   full note (frontmatter, outlinks, backlinks). Snippets alone are often
   not enough to quote or reason from.

4. WHEN A NOTE REFERENCES OTHERS via [[wikilinks]] or when you need to map
   relationships: call obsidian_backlinks with the note title to see which
   notes cite it.

5. DO NOT WRITE TO THE VAULT during the session via this server's tools.
   A dedicated `to_obsidian` MCP prompt handles curated writes at the end
   of a session, with human-in-the-loop approval.

6. IF A SEARCH RETURNS NOTHING RELEVANT: say so plainly. A clean miss is
   more useful than fabricated context.
"""


app = Server("second-brain")


@functools.lru_cache(maxsize=1)
def _get_cfg() -> Config:
    return load_config()


def _read_index_md() -> str:
    """Return the freshest _index.md content, or a helpful placeholder."""
    cfg = _get_cfg()
    candidates = [
        cfg.vault / "_index.md",
        cfg.vault / "_index 1.md",  # sync conflict artifact; still readable
    ]
    for c in candidates:
        if c.exists():
            try:
                return c.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return "_index.md not found in vault."


def _refresh_index() -> dict:
    """Cheap mtime-based incremental reindex. Called at the top of every tool."""
    try:
        return idx.index_incremental()
    except Exception as e:
        return {"error": f"reindex failed: {e}"}


def _note_stats() -> dict:
    """Counts used in the overview response."""
    col = idx.get_collection()
    got = col.get(include=["metadatas"])
    metas = got.get("metadatas") or []

    by_type: dict[str, int] = {}
    by_top_dir: dict[str, int] = {}
    seen_rels: set[str] = set()

    for m in metas:
        rel = m.get("rel")
        if not rel or rel in seen_rels:
            continue
        seen_rels.add(rel)
        t = m.get("fm_type") or "untyped"
        by_type[t] = by_type.get(t, 0) + 1
        top = rel.split("/", 1)[0] if "/" in rel else "(root)"
        by_top_dir[top] = by_top_dir.get(top, 0) + 1

    return {
        "notes": len(seen_rels),
        "chunks": len(metas),
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_top_dir": dict(sorted(by_top_dir.items(), key=lambda x: -x[1])),
    }


def _load_backlinks() -> dict[str, list[str]]:
    cfg = _get_cfg()
    path = cfg.index_dir / "backlinks.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _backlinks_for(title_or_stem: str, vault_rel_hint: str | None = None) -> list[str]:
    """Return the list of rel-paths that reference `title_or_stem` via [[...]]."""
    back = _load_backlinks()
    keys = [title_or_stem]
    if vault_rel_hint:
        stem = Path(vault_rel_hint).stem
        if stem not in keys:
            keys.append(stem)
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        for rel in back.get(k, []):
            if rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="obsidian_overview",
            description=(
                "Return vault stats, the fresh _index.md, and the OBSIDIAN "
                "MEMORY PROTOCOL. Call this first in any new session to "
                "understand what knowledge is available and how to use it."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_search",
            description=(
                "Semantic search across the curated Obsidian vault. Use this "
                "BEFORE answering about anything that sounds like prior "
                "context — past decisions, projects, people, tools, facts. "
                "Multilingual queries supported when configured with bge-m3."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query.",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "How many hits to return (default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "type_filter": {
                        "type": "string",
                        "description": (
                            "Optional frontmatter 'type' to restrict to "
                            "(e.g. 'knowledge', 'project', 'insight')."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_read",
            description=(
                "Read a single note whole, straight from disk. Use this "
                "after obsidian_search when a hit looks promising and you "
                "need the full text, frontmatter, outlinks, or backlinks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": ("Vault-relative path, e.g. 'knowledge/topic/Some note.md'"),
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="obsidian_backlinks",
            description=(
                "Find notes that reference the given note via [[wikilink]]. "
                "Useful for mapping relationships between ideas and for "
                "discovering context built around a concept."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note_title": {
                        "type": "string",
                        "description": (
                            "The wikilink target to look up. Usually the "
                            "note's title or filename stem."
                        ),
                    }
                },
                "required": ["note_title"],
                "additionalProperties": False,
            },
        ),
    ]


def _text(content: dict | str) -> list[types.TextContent]:
    if isinstance(content, str):
        body = content
    else:
        # `default=str` handles datetime.date/datetime objects that PyYAML
        # auto-parses out of frontmatter.
        body = json.dumps(content, ensure_ascii=False, indent=2, default=str)
    return [types.TextContent(type="text", text=body)]


async def _call_overview(_: dict) -> list[types.TextContent]:
    cfg = _get_cfg()
    refresh = _refresh_index()
    stats = _note_stats()
    index_md = _read_index_md()
    payload = {
        "protocol": MEMORY_PROTOCOL,
        "vault_path": str(cfg.vault),
        "stats": stats,
        "reindex": refresh,
        "index_md": index_md,
    }
    return _text(payload)


async def _call_search(args: dict) -> list[types.TextContent]:
    _refresh_index()
    query = args.get("query")
    if not query:
        return _text({"error": "query is required"})
    n = int(args.get("n_results", 5))
    type_filter = args.get("type_filter") or None
    hits = idx.search(query=query, n_results=n, type_filter=type_filter)
    return _text({"query": query, "type_filter": type_filter, "hits": hits})


async def _call_read(args: dict) -> list[types.TextContent]:
    _refresh_index()
    rel = args.get("path")
    if not rel:
        return _text({"error": "path is required"})
    cfg = _get_cfg()
    # Keep a non-resolved path for parse_note so its relative_to(vault) works
    # when vault sits behind a symlink (e.g. /tmp on macOS → /private/tmp).
    abs_path_raw = cfg.vault / rel
    abs_path_resolved = abs_path_raw.resolve()
    try:
        abs_path_resolved.relative_to(cfg.vault.resolve())
    except ValueError:
        return _text({"error": "path escapes the vault"})
    if not abs_path_raw.is_file():
        return _text({"error": f"note not found: {rel}"})
    try:
        note = idx.parse_note(abs_path_raw)
    except Exception as e:
        return _text({"error": f"failed to parse note: {e}"})

    backs = _backlinks_for(note.title, vault_rel_hint=note.rel)
    return _text(
        {
            "rel": note.rel,
            "title": note.title,
            "frontmatter": note.frontmatter,
            "body": note.body,
            "outlinks": note.wikilinks,
            "backlinks": backs,
            "mtime": note.mtime,
        }
    )


async def _call_backlinks(args: dict) -> list[types.TextContent]:
    _refresh_index()
    title = args.get("note_title")
    if not title:
        return _text({"error": "note_title is required"})
    rels = _backlinks_for(title)
    return _text({"note_title": title, "backlinks": rels})


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    args = arguments or {}
    if name == "obsidian_overview":
        return await _call_overview(args)
    if name == "obsidian_search":
        return await _call_search(args)
    if name == "obsidian_read":
        return await _call_read(args)
    if name == "obsidian_backlinks":
        return await _call_backlinks(args)
    return _text({"error": f"unknown tool: {name}"})


@app.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [prompts.TO_OBSIDIAN_PROMPT]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    if name == "to_obsidian":
        return prompts.get_to_obsidian()
    raise ValueError(f"Unknown prompt: {name}")


async def _serve() -> None:
    async with stdio_server() as (read, write):
        await app.run(
            read,
            write,
            InitializationOptions(
                server_name="second-brain",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
