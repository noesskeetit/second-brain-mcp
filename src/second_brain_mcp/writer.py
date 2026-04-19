"""writer.py — mutating operations on the Obsidian vault.

Pure functions, one per operation. The MCP server's `obsidian_write` tool is
a thin dispatcher over this module; tests and any internal caller can use it
directly without the MCP wrapper.

Safety invariants held by every op:
    * paths are normalised and verified to stay inside the vault (no `..` escape,
      no symlink-into-etc tricks),
    * writes are atomic (temp file + os.replace) so an interrupted run never
      leaves half-written notes,
    * the caller is responsible for triggering a reindex after mutation — the
      MCP server layer does that.
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import Config

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class WriteError(Exception):
    """Surface as a clean JSON error to the MCP client, not a stack trace."""


@dataclass
class NoteText:
    frontmatter: dict
    body: str  # no leading newline, no trailing newline (normalised)


def _safe_path(cfg: Config, rel: str) -> Path:
    if not rel or not isinstance(rel, str):
        raise WriteError("path is required and must be a string")
    # `vault / "/etc/passwd"` resolves to "/etc/passwd" — Path drops the left
    # side when the right is absolute. Don't strip the leading slash; let that
    # absoluteness escape the vault and fail the relative_to check below.
    abs_raw = cfg.vault / rel
    try:
        abs_raw.resolve().relative_to(cfg.vault.resolve())
    except ValueError as exc:
        raise WriteError(f"path escapes the vault: {rel}") from exc
    return abs_raw


def _parse(text: str) -> NoteText:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return NoteText(frontmatter={}, body=text.strip("\n"))
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end():].strip("\n")
    return NoteText(frontmatter=fm, body=body)


def _render(note: NoteText) -> str:
    if note.frontmatter:
        fm_text = yaml.safe_dump(
            note.frontmatter,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip("\n")
        return f"---\n{fm_text}\n---\n\n{note.body}\n" if note.body else f"---\n{fm_text}\n---\n"
    return f"{note.body}\n" if note.body else ""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _require_exists(path: Path, rel: str) -> None:
    if not path.is_file():
        raise WriteError(f"note not found: {rel}")


def _diff_payload(before: str | None, after: str | None, dry_run: bool) -> dict:
    if not dry_run:
        return {}
    return {"before": before, "after": after}


# ---------- operations ----------


def op_create(
    cfg: Config,
    path: str,
    body: str = "",
    frontmatter: dict | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    exists = abs_path.exists()
    if exists and not overwrite:
        raise WriteError(f"note already exists: {path} (pass overwrite=true to replace)")

    note = NoteText(frontmatter=dict(frontmatter or {}), body=(body or "").strip("\n"))
    new_text = _render(note)

    before = abs_path.read_text(encoding="utf-8", errors="replace") if exists else None
    if not dry_run:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "create",
        "path": path,
        "changed": True,
        "overwrote": exists,
        **_diff_payload(before, new_text, dry_run),
    }


def op_append(
    cfg: Config,
    path: str,
    text: str,
    separator: str = "\n\n",
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)

    before = abs_path.read_text(encoding="utf-8", errors="replace")
    note = _parse(before)
    joined = note.body + (separator if note.body else "") + text
    note.body = joined.strip("\n")
    new_text = _render(note)

    if not dry_run and new_text != before:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "append",
        "path": path,
        "changed": new_text != before,
        **_diff_payload(before, new_text, dry_run),
    }


def op_prepend(
    cfg: Config,
    path: str,
    text: str,
    separator: str = "\n\n",
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)

    before = abs_path.read_text(encoding="utf-8", errors="replace")
    note = _parse(before)
    joined = text + (separator if note.body else "") + note.body
    note.body = joined.strip("\n")
    new_text = _render(note)

    if not dry_run and new_text != before:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "prepend",
        "path": path,
        "changed": new_text != before,
        **_diff_payload(before, new_text, dry_run),
    }


def op_replace_body(
    cfg: Config,
    path: str,
    body: str,
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)

    before = abs_path.read_text(encoding="utf-8", errors="replace")
    note = _parse(before)
    note.body = (body or "").strip("\n")
    new_text = _render(note)

    if not dry_run and new_text != before:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "replace_body",
        "path": path,
        "changed": new_text != before,
        **_diff_payload(before, new_text, dry_run),
    }


def op_replace_text(
    cfg: Config,
    path: str,
    find: str,
    replace: str,
    regex: bool = False,
    count: int = -1,
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)

    if not find:
        raise WriteError("find must be a non-empty string")

    before = abs_path.read_text(encoding="utf-8", errors="replace")
    note = _parse(before)

    if regex:
        try:
            pattern = re.compile(find, flags=re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise WriteError(f"invalid regex: {exc}") from exc
        new_body, n_subs = pattern.subn(replace, note.body, count=0 if count < 0 else count)
    else:
        if count < 0:
            new_body = note.body.replace(find, replace)
            n_subs = note.body.count(find)
        else:
            new_body = note.body.replace(find, replace, count)
            n_subs = min(note.body.count(find), count)

    note.body = new_body.strip("\n")
    new_text = _render(note)

    if not dry_run and new_text != before:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "replace_text",
        "path": path,
        "changed": new_text != before,
        "replacements": n_subs,
        **_diff_payload(before, new_text, dry_run),
    }


def op_set_frontmatter(
    cfg: Config,
    path: str,
    updates: dict | None = None,
    remove_keys: list | None = None,
    dry_run: bool = False,
) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)

    before = abs_path.read_text(encoding="utf-8", errors="replace")
    note = _parse(before)

    for k, v in (updates or {}).items():
        note.frontmatter[k] = v
    for k in remove_keys or []:
        note.frontmatter.pop(k, None)
    new_text = _render(note)

    if not dry_run and new_text != before:
        _atomic_write(abs_path, new_text)
    return {
        "ok": True,
        "op": "set_frontmatter",
        "path": path,
        "changed": new_text != before,
        "frontmatter": note.frontmatter,
        **_diff_payload(before, new_text, dry_run),
    }


def op_delete(cfg: Config, path: str, dry_run: bool = False) -> dict:
    abs_path = _safe_path(cfg, path)
    _require_exists(abs_path, path)
    before = abs_path.read_text(encoding="utf-8", errors="replace")
    if not dry_run:
        abs_path.unlink()
    return {
        "ok": True,
        "op": "delete",
        "path": path,
        "changed": True,
        **_diff_payload(before, None, dry_run),
    }


def op_rename(
    cfg: Config,
    path: str,
    new_path: str,
    update_wikilinks: bool = False,
    dry_run: bool = False,
) -> dict:
    if update_wikilinks:
        # Deliberately not implemented: rewriting [[wikilinks]] across the vault
        # risks corrupting notes with context-sensitive links. Caller can do a
        # targeted replace_text sweep instead.
        raise WriteError("update_wikilinks=true is not supported; rewrite references manually")

    src = _safe_path(cfg, path)
    dst = _safe_path(cfg, new_path)
    _require_exists(src, path)
    if dst.exists():
        raise WriteError(f"destination already exists: {new_path}")

    before = src.read_text(encoding="utf-8", errors="replace")
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    return {
        "ok": True,
        "op": "rename",
        "path": path,
        "new_path": new_path,
        "changed": True,
        **_diff_payload(before, before, dry_run),
    }


# ---------- dispatcher ----------


_OPS: dict[str, Any] = {
    "create": op_create,
    "append": op_append,
    "prepend": op_prepend,
    "replace_body": op_replace_body,
    "replace_text": op_replace_text,
    "set_frontmatter": op_set_frontmatter,
    "delete": op_delete,
    "rename": op_rename,
}


def apply(cfg: Config, op: str, args: dict) -> dict:
    fn = _OPS.get(op)
    if fn is None:
        raise WriteError(f"unknown op: {op!r}. Allowed: {sorted(_OPS)}")
    return fn(cfg, **args)
