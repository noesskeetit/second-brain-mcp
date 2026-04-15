# Security

This document describes the security properties of `second-brain-mcp`:
what the server does and does not do, which attack surfaces it closes by
construction, and how to report vulnerabilities.

---

## Read-only guarantees

The MCP server exposes **zero write tools**. The entire tool surface —
`obsidian_overview`, `obsidian_search`, `obsidian_read`,
`obsidian_backlinks` — is read-only. There is no `obsidian_create`,
`obsidian_update`, `obsidian_delete`, or equivalent by any other name.

The only write path is the `to_obsidian` **prompt**, which instructs the
agent to use its own client's write tool under explicit user approval for
every note. The server never touches the vault.

The attack-surface reasoning is straightforward: a remote or injected
prompt cannot coerce the agent into writing a note through an MCP tool
that does not exist, and the approval step in `to_obsidian` requires a
human to confirm each candidate. The only way adversarial content
enters the vault is if the user personally accepts it.

---

## Path traversal

`obsidian_read` takes a `rel` argument — a path relative to the vault
root. Without care, a crafted `rel` like `../../etc/passwd` could read
files outside the vault.

The server defends against this with a two-step check:

1. Resolve the absolute target: `(vault / rel).resolve()`.
2. Call `.relative_to(vault.resolve())`. If the resolved target does not
   live under the resolved vault, the server returns
   `{"error": "path escapes the vault"}` without opening the file.

### The macOS symlink trap

On macOS, the naive resolve-once approach can be subverted by a symlink
that already lives inside the vault. `Path.resolve()` follows symlinks.
A symlink placed under the vault pointing outside the vault will resolve
to an absolute path, and that path must also be verified as being under
the resolved vault — not merely starting with the vault prefix, which
can pass spuriously under case-insensitive filesystems.

The regression test for both the plain `../` case and the symlink case
lives in [`tests/test_path_traversal.py`](../tests/test_path_traversal.py).
If you are modifying `obsidian_read`, that test must continue to pass.

---

## No network access during serving

After the embedder is downloaded once (on first tool call), the server
runs fully offline:

- The embedder loads from the local HuggingFace cache
  (`~/.cache/huggingface/`). No network request per call.
- ChromaDB persists to a local directory (`$OBSIDIAN_INDEX_DIR/index/`).
  No remote database.
- No telemetry. The server does not phone home, does not report usage,
  and does not open any outbound socket during normal operation.

The first-run bge-m3 download is the only network event, and it is
performed by `sentence-transformers` against HuggingFace directly — the
server does not proxy or re-publish it.

---

## No secrets in vault

The indexer embeds whatever text is in your `.md` files. If you paste an
API key, database password, or any other credential into a note, that
text ends up in the ChromaDB index — and any agent with access to the
MCP server can surface it through semantic search.

**Recommendation:** keep secrets out of the vault entirely. Put them in
a password manager, `.env` files outside the vault, or a secrets
backend. If you need to write a note *about* a secret (where it lives,
how it rotates), describe the location without including the value.

If you discover a secret has been indexed:

1. Remove the text from the note and save.
2. Run `uvx second-brain-mcp rebuild` to drop the old embeddings.
3. Rotate the credential — assume indexing is compromise-equivalent.

---

## Reporting vulnerabilities

Please report suspected vulnerabilities privately by email to
**shura.gabbasov@mail.ru**. Do not file public GitHub issues for
security-sensitive reports.

Include:

- A description of the vulnerability and the affected tool / code path.
- Reproduction steps or a proof-of-concept if possible.
- The version of `second-brain-mcp` you tested against (`uvx second-brain-mcp --version`).

Reports are acknowledged within a few days. Fixes land through a normal
patch release with the reporter credited in the release notes unless
anonymity is requested.
