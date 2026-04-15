"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEX_DIR = Path.home() / ".second-brain-mcp"
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"


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
    embed_device = os.environ.get("OBSIDIAN_EMBED_DEVICE") or _auto_device()
    return Config(
        vault=vault,
        index_dir=index_dir,
        embed_model=embed_model,
        embed_device=embed_device,
    )
