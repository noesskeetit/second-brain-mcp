# src/second_brain_mcp/cli.py
"""`second-brain-mcp` command line interface.

Subcommands:
    serve      — run the MCP server (stdio by default, or streamable-http)
    index      — incremental reindex (mtime-based)
    rebuild    — full wipe + reindex
    search     — sanity-check search (bypasses MCP)
    stats      — collection stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="second-brain-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Run the MCP server (stdio or http)")
    p_serve.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("OBSIDIAN_MCP_TRANSPORT", "stdio"),
        help="Transport mode (default: stdio; env: OBSIDIAN_MCP_TRANSPORT).",
    )
    p_serve.add_argument(
        "--host",
        default=None,
        help="HTTP bind host (default 127.0.0.1; env: OBSIDIAN_MCP_HOST).",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (default 8765; env: OBSIDIAN_MCP_PORT).",
    )
    p_serve.add_argument(
        "--path",
        default=None,
        help="HTTP mount path (default /mcp; env: OBSIDIAN_MCP_PATH).",
    )

    sub.add_parser("index", help="Incremental reindex")
    sub.add_parser("rebuild", help="Full wipe + reindex")
    sub.add_parser("stats", help="Print collection stats")

    p_search = sub.add_parser("search", help="CLI semantic search")
    p_search.add_argument("query")
    p_search.add_argument("--n", type=int, default=5)
    p_search.add_argument("--type", dest="type_filter", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        # CLI flags override env for this run.
        if args.host is not None:
            os.environ["OBSIDIAN_MCP_HOST"] = args.host
        if args.port is not None:
            os.environ["OBSIDIAN_MCP_PORT"] = str(args.port)
        if args.path is not None:
            os.environ["OBSIDIAN_MCP_PATH"] = args.path

        from .server import main as serve_main

        serve_main(transport=args.transport)
        return 0

    from . import indexer

    if args.cmd == "index":
        print(json.dumps(indexer.index_incremental(), indent=2))
    elif args.cmd == "rebuild":
        print(json.dumps(indexer.rebuild(), indent=2))
    elif args.cmd == "stats":
        print(json.dumps(indexer.stats(), indent=2))
    elif args.cmd == "search":
        hits = indexer.search(args.query, n_results=args.n, type_filter=args.type_filter)
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
