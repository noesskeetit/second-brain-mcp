"""server.py — MCP server exposing an Obsidian vault as semantic memory.

Tools:
    obsidian_overview   — vault stats + fresh _index.md + MEMORY PROTOCOL.
                          The first tool a new session should call.
    obsidian_search     — semantic search, optional type filter.
    obsidian_read       — fetch a note whole from disk (frontmatter,
                          body, outlinks, backlinks). Always fresh.
    obsidian_backlinks  — find notes that reference a target by wikilink.
    obsidian_write      — mutate the vault: create / append / prepend /
                          replace_body / replace_text / set_frontmatter /
                          delete / rename. One tool, many ops.

Every tool call runs a cheap mtime-based incremental reindex first, so the
agent never has to think about index freshness after external edits. Writes
trigger an incremental reindex on success so search reflects the change
immediately.

Transports:
    stdio — the default; used by `claude mcp add` and similar subprocess
            launchers.
    http  — streamable HTTP on a user-chosen host/port with an optional
            Bearer token. Required when the server binds to a non-loopback
            interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import sys
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import indexer as idx
from . import writer
from .config import LOOPBACK_HOSTS, Config
from .config import load as load_config

MEMORY_PROTOCOL = """OBSIDIAN MEMORY PROTOCOL

This MCP exposes a curated Obsidian vault as the source of truth for past
decisions, facts, preferences, people, and project context. Every note in
the vault should be an atomic, human-reviewed statement — dense signal, not
archival noise.

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

5. WRITES via obsidian_write are allowed and expected — this is how the
   vault grows. Rules of engagement:
     * Deliberate, not reflexive. Do NOT write whenever a conversation turn
       produces a fact; write when the user says so, or when you've just
       established something durable the user clearly wants remembered.
     * Check for duplicates with obsidian_search before `create`. Updating
       an existing note (append / set_frontmatter / replace_text) is almost
       always better than forking a near-duplicate.
     * One atomic statement per note. The filename IS the statement, around
       60 characters, reading as a full sentence.
     * Prefer small ops. `set_frontmatter` to bump `verified`,
       `replace_text` for a typo, `append` for an addendum — over rewriting
       the whole note.
     * Use `dry_run=true` when you are not certain the edit is right.

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


WRITE_TOOL_DESCRIPTION = (
    "Mutate the vault. One tool, many ops — pick with `op`:\n"
    "  create           — make a new note (fails if exists unless overwrite=true).\n"
    "  append           — add text to the end of a note's body.\n"
    "  prepend          — insert text right after the frontmatter block.\n"
    "  replace_body     — replace the whole body, frontmatter preserved.\n"
    "  replace_text     — find/replace within the body (literal or regex).\n"
    "  set_frontmatter  — merge keys into frontmatter, optionally remove some.\n"
    "  delete           — delete a note.\n"
    "  rename           — move/rename a note (wikilinks in OTHER notes are\n"
    "                     NOT rewritten — do that with a follow-up replace_text).\n"
    "\n"
    "All ops take a vault-relative `path` and support `dry_run=true` which\n"
    "returns {before, after} without touching disk.\n"
    "\n"
    "Use deliberately: prefer small ops (set_frontmatter, replace_text, append)\n"
    "over rewriting whole notes, and run obsidian_search before `create` to\n"
    "avoid duplicates."
)

WRITE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": [
                "create",
                "append",
                "prepend",
                "replace_body",
                "replace_text",
                "set_frontmatter",
                "delete",
                "rename",
            ],
            "description": "Which mutation to perform.",
        },
        "path": {
            "type": "string",
            "description": "Vault-relative path, e.g. 'knowledge/topic/Some note.md'.",
        },
        "new_path": {
            "type": "string",
            "description": "Only for op=rename. Vault-relative destination path.",
        },
        "body": {
            "type": "string",
            "description": "For op=create or op=replace_body — the note body (no frontmatter).",
        },
        "frontmatter": {
            "type": "object",
            "description": "For op=create — initial frontmatter dict.",
            "additionalProperties": True,
        },
        "overwrite": {
            "type": "boolean",
            "description": "For op=create — allow replacing an existing file.",
            "default": False,
        },
        "text": {
            "type": "string",
            "description": "For op=append or op=prepend — the text to insert.",
        },
        "separator": {
            "type": "string",
            "description": "For op=append/prepend — joiner between existing body and new text.",
            "default": "\n\n",
        },
        "find": {
            "type": "string",
            "description": "For op=replace_text — the needle. Treated as regex when regex=true.",
        },
        "replace": {
            "type": "string",
            "description": "For op=replace_text — the replacement string.",
        },
        "regex": {
            "type": "boolean",
            "description": "For op=replace_text — interpret `find` as regex (MULTILINE+DOTALL).",
            "default": False,
        },
        "count": {
            "type": "integer",
            "description": "For op=replace_text — max replacements. -1 means all.",
            "default": -1,
        },
        "updates": {
            "type": "object",
            "description": "For op=set_frontmatter — keys to set/merge into frontmatter.",
            "additionalProperties": True,
        },
        "remove_keys": {
            "type": "array",
            "items": {"type": "string"},
            "description": "For op=set_frontmatter — keys to remove from frontmatter.",
        },
        "update_wikilinks": {
            "type": "boolean",
            "description": (
                "For op=rename — when true, also rewrite [[wikilinks]] in other "
                "notes. NOT IMPLEMENTED yet; passing true raises an error."
            ),
            "default": False,
        },
        "dry_run": {
            "type": "boolean",
            "description": "Return {before, after} without writing to disk.",
            "default": False,
        },
    },
    "required": ["op", "path"],
    "additionalProperties": False,
}


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
        types.Tool(
            name="obsidian_write",
            description=WRITE_TOOL_DESCRIPTION,
            inputSchema=WRITE_TOOL_SCHEMA,
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


async def _call_write(args: dict) -> list[types.TextContent]:
    op = args.get("op")
    if not op:
        return _text({"error": "op is required"})
    cfg = _get_cfg()
    op_args = {k: v for k, v in args.items() if k != "op"}
    try:
        result = writer.apply(cfg, op, op_args)
    except writer.WriteError as e:
        return _text({"ok": False, "op": op, "error": str(e)})
    except TypeError as e:
        # Unexpected kwargs from a malformed client call. Surface cleanly.
        return _text({"ok": False, "op": op, "error": f"bad arguments: {e}"})

    # Only reindex when the op actually touched disk — dry_run returns
    # changed=True for create/delete/rename but did not write.
    if not args.get("dry_run") and result.get("changed"):
        reindex = _refresh_index()
        result["reindex"] = reindex
    return _text(result)


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
    if name == "obsidian_write":
        return await _call_write(args)
    return _text({"error": f"unknown tool: {name}"})


def _init_options() -> InitializationOptions:
    return InitializationOptions(
        server_name="second-brain",
        server_version="1.2.0",
        capabilities=app.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def _serve_stdio() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, _init_options())


def _build_http_asgi(token: str | None, path: str):
    """Return a Starlette ASGI app wiring StreamableHTTPSessionManager +
    Bearer middleware at `path`."""
    # Imports kept local so stdio mode doesn't pay the starlette/uvicorn cost.
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    session_manager = StreamableHTTPSessionManager(app=app, json_response=False, stateless=False)

    async def handle_mcp(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    # OAuth discovery stubs. Claude Code's MCP SDK probes these BEFORE the
    # first /mcp/ call. Two behaviours, by spec:
    #
    # * /.well-known/oauth-protected-resource (RFC 9728) → 200 JSON metadata
    #   advertising "Bearer via header, no OAuth flow". This is what lets the
    #   SDK skip OAuth and use the static Bearer from its config.
    # * /.well-known/oauth-authorization-server, /register → 404 JSON. No
    #   OAuth server, no dynamic client registration. JSON (not plain text)
    #   so SDK's body parser doesn't crash.
    async def _oauth_not_supported(_request):
        return JSONResponse(
            {
                "error": "not_supported",
                "error_description": (
                    "This server does not support OAuth. "
                    "Use a static Bearer token via the Authorization header."
                ),
            },
            status_code=404,
        )

    async def _protected_resource_metadata(request):
        resource_url = f"{request.url.scheme}://{request.url.netloc}{path}"
        return JSONResponse(
            {
                "resource": resource_url,
                "bearer_methods_supported": ["header"],
                "resource_documentation": (
                    "Use static Bearer token via Authorization header."
                ),
            },
            status_code=200,
        )

    class BearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Only guard the MCP mount. Anything else (OAuth discovery paths
            # like /.well-known/oauth-protected-resource, /register, root /,
            # etc.) falls through to Starlette which 404s cleanly. Without
            # this carve-out, MCP clients that probe for OAuth support see a
            # 401 on discovery paths, misread it as "OAuth required", and
            # fall into a registration flow we don't implement — breaking
            # static-Bearer clients that already have a valid token.
            if not request.url.path.startswith(path):
                return await call_next(request)
            if token is None:
                return await call_next(request)
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer ") or header[len("Bearer "):] != token:
                return JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="second-brain"'},
                )
            return await call_next(request)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route(
                "/.well-known/oauth-authorization-server",
                _oauth_not_supported,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource",
                _protected_resource_metadata,
                methods=["GET"],
            ),
            Route("/register", _oauth_not_supported, methods=["POST"]),
            Mount(path, app=handle_mcp),
        ],
        middleware=[Middleware(BearerMiddleware)],
    )


def _serve_http(
    host: str, port: int, path: str, token: str | None, allow_unauth_host: bool = False
) -> None:
    import uvicorn

    if host not in LOOPBACK_HOSTS and not token:
        if allow_unauth_host:
            # Escape hatch for container deployments: the process inside a
            # Docker container MUST listen on 0.0.0.0 to be reachable across
            # the network namespace boundary, but real exposure is decided by
            # the host-side port publish (e.g. `127.0.0.1:8765:8765`). When
            # the operator sets OBSIDIAN_ALLOW_UNAUTH_HOST=1 they have
            # assumed responsibility for that external boundary.
            print(
                "[second-brain-mcp] WARNING: binding to non-loopback host "
                f"{host!r} with NO auth token (OBSIDIAN_ALLOW_UNAUTH_HOST=1). "
                "Only safe when external exposure is controlled elsewhere "
                "(e.g. Docker loopback port-publish, SSH tunnel).",
                file=sys.stderr,
            )
        else:
            raise RuntimeError(
                f"refusing to bind to non-loopback host {host!r} without an auth "
                "token. Set OBSIDIAN_HTTP_TOKEN, use --host 127.0.0.1, or set "
                "OBSIDIAN_ALLOW_UNAUTH_HOST=1 if the external boundary is "
                "enforced elsewhere (Docker host-side publish, reverse proxy)."
            )
    if token:
        print("[second-brain-mcp] HTTP auth: Bearer token required", file=sys.stderr)
    else:
        print("[second-brain-mcp] HTTP auth: DISABLED", file=sys.stderr)
    print(f"[second-brain-mcp] serving on http://{host}:{port}{path}", file=sys.stderr)

    asgi = _build_http_asgi(token=token, path=path)
    uvicorn.run(asgi, host=host, port=port, log_level="info")


def main(transport: str = "stdio") -> None:
    cfg = _get_cfg()
    if transport == "http":
        _serve_http(
            cfg.http_host,
            cfg.http_port,
            cfg.http_path,
            cfg.http_token,
            allow_unauth_host=cfg.allow_unauth_host,
        )
    elif transport == "stdio":
        asyncio.run(_serve_stdio())
    else:
        raise RuntimeError(f"unknown transport: {transport!r}")


if __name__ == "__main__":
    main()
