"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEX_DIR = Path.home() / ".second-brain-mcp"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Config:
    vault: Path
    index_dir: Path
    embed_model: str
    embed_api_key: str
    embed_api_url: str
    embed_dimensions: int | None
    http_host: str
    http_port: int
    http_path: str
    http_token: str | None
    allow_unauth_host: bool

    @property
    def embed_provider(self) -> str:
        # Kept as a property (not a stored field) so the collection stamp logic
        # and stats output continue to have a single source of truth for
        # "what embedder built this index". The server is API-only; if a user
        # ever re-adds a local provider, this becomes a real field again.
        return "openai"


def _parse_dimensions(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "OBSIDIAN_EMBED_DIMENSIONS must be a positive integer, "
            f"got {raw!r}. See docs/CUSTOMIZE.md."
        ) from exc
    if value <= 0:
        raise RuntimeError(
            "OBSIDIAN_EMBED_DIMENSIONS must be a positive integer, "
            f"got {value}. See docs/CUSTOMIZE.md."
        )
    return value


def load() -> Config:
    vault_raw = os.environ.get("OBSIDIAN_VAULT")
    if not vault_raw:
        raise RuntimeError(
            "OBSIDIAN_VAULT is required. Set it to the absolute path of your vault, "
            "e.g. OBSIDIAN_VAULT=$HOME/obsidian/vault"
        )
    vault = Path(vault_raw).expanduser().resolve()
    index_dir = Path(os.environ.get("OBSIDIAN_INDEX_DIR", str(DEFAULT_INDEX_DIR))).expanduser()

    api_key = os.environ.get("OBSIDIAN_EMBED_API_KEY") or None
    api_url = os.environ.get("OBSIDIAN_EMBED_API_URL") or None
    embed_model = os.environ.get("OBSIDIAN_EMBED_MODEL") or None

    missing = []
    if not api_key:
        missing.append("OBSIDIAN_EMBED_API_KEY")
    if not api_url:
        missing.append("OBSIDIAN_EMBED_API_URL")
    if not embed_model:
        missing.append("OBSIDIAN_EMBED_MODEL")
    if missing:
        raise RuntimeError(
            "Embedder is API-only (OpenAI-compatible HTTP endpoint). "
            f"Missing: {', '.join(missing)}. See docs/CUSTOMIZE.md."
        )

    dimensions = _parse_dimensions(os.environ.get("OBSIDIAN_EMBED_DIMENSIONS"))

    http_host = os.environ.get("OBSIDIAN_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    http_port_raw = os.environ.get("OBSIDIAN_MCP_PORT", "8765").strip() or "8765"
    try:
        http_port = int(http_port_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"OBSIDIAN_MCP_PORT must be an integer, got {http_port_raw!r}."
        ) from exc
    http_path = os.environ.get("OBSIDIAN_MCP_PATH", "/mcp").strip() or "/mcp"
    if not http_path.startswith("/"):
        http_path = "/" + http_path
    http_token = os.environ.get("OBSIDIAN_HTTP_TOKEN") or None
    allow_unauth_host = os.environ.get("OBSIDIAN_ALLOW_UNAUTH_HOST", "").strip() == "1"

    return Config(
        vault=vault,
        index_dir=index_dir,
        embed_model=embed_model,
        embed_api_key=api_key,
        embed_api_url=api_url,
        embed_dimensions=dimensions,
        http_host=http_host,
        http_port=http_port,
        http_path=http_path,
        http_token=http_token,
        allow_unauth_host=allow_unauth_host,
    )
