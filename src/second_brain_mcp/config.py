"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEX_DIR = Path.home() / ".second-brain-mcp"
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"
DEFAULT_PROVIDER = "local"
ALLOWED_PROVIDERS = {"local", "openai"}


def _auto_device() -> str:
    # Lazy-import torch so a missing torch during config inspection doesn't crash.
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


@dataclass(frozen=True)
class Config:
    vault: Path
    index_dir: Path
    embed_model: str
    embed_device: str
    embed_provider: str
    embed_api_key: str | None
    embed_api_url: str | None
    embed_dimensions: int | None


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
    embed_model = os.environ.get("OBSIDIAN_EMBED_MODEL", DEFAULT_EMBED_MODEL)

    provider = os.environ.get("OBSIDIAN_EMBED_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise RuntimeError(
            f"OBSIDIAN_EMBED_PROVIDER={provider!r} is not supported. "
            f"Allowed values: {sorted(ALLOWED_PROVIDERS)}. See docs/CUSTOMIZE.md."
        )

    api_key = os.environ.get("OBSIDIAN_EMBED_API_KEY") or None
    api_url = os.environ.get("OBSIDIAN_EMBED_API_URL") or None
    dimensions = _parse_dimensions(os.environ.get("OBSIDIAN_EMBED_DIMENSIONS"))

    if provider == "openai":
        missing = []
        if not api_key:
            missing.append("OBSIDIAN_EMBED_API_KEY")
        if not api_url:
            missing.append("OBSIDIAN_EMBED_API_URL")
        if missing:
            raise RuntimeError(
                f"OBSIDIAN_EMBED_PROVIDER=openai requires: {', '.join(missing)}. "
                "See docs/CUSTOMIZE.md → API embedder."
            )
        embed_device = ""  # unused in API mode
    else:
        embed_device = os.environ.get("OBSIDIAN_EMBED_DEVICE") or _auto_device()

    return Config(
        vault=vault,
        index_dir=index_dir,
        embed_model=embed_model,
        embed_device=embed_device,
        embed_provider=provider,
        embed_api_key=api_key,
        embed_api_url=api_url,
        embed_dimensions=dimensions,
    )
