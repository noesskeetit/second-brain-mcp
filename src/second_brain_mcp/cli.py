# src/second_brain_mcp/cli.py
"""`second-brain-mcp` command line interface.

Subcommands:
    serve      — run the stdio MCP server (used in `claude mcp add`)
    index      — incremental reindex (mtime-based)
    rebuild    — full wipe + reindex
    search     — sanity-check search (bypasses MCP)
    stats      — collection stats
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="second-brain-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="Run the stdio MCP server")
    sub.add_parser("index", help="Incremental reindex")
    sub.add_parser("rebuild", help="Full wipe + reindex")
    sub.add_parser("stats", help="Print collection stats")

    p_search = sub.add_parser("search", help="CLI semantic search")
    p_search.add_argument("query")
    p_search.add_argument("--n", type=int, default=5)
    p_search.add_argument("--type", dest="type_filter", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from .server import main as serve_main

        serve_main()
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
