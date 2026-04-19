# Security

This document describes the security properties of `second-brain-mcp`:
what the server does and does not do, which attack surfaces it closes
by construction, which attack surfaces exist and how to reduce them,
and how to report vulnerabilities.

---

## Tool surface

The MCP server exposes five tools:

| Tool                 | Mutates vault? |
|----------------------|----------------|
| `obsidian_overview`  | No             |
| `obsidian_search`    | No             |
| `obsidian_read`      | No             |
| `obsidian_backlinks` | No             |
| `obsidian_write`     | **Yes**        |

Until v1.1, the package exposed zero write tools; the `to_obsidian`
prompt drove writes through the client's own write tool under a
per-note approval gate. v1.1 replaced that indirection with one
dispatcher tool, `obsidian_write`, with eight ops. The trade-off:
fewer moving parts, tool self-describing, but the approval gate is no
longer implicit — see **Memory poisoning** below.

---

## Path traversal

`obsidian_read` and `obsidian_write` both take vault-relative paths.
Without care, a crafted path like `../../etc/passwd` could read or
overwrite files outside the vault.

Both tools defend against this with a two-step check:

1. Resolve the absolute target: `(vault / rel).resolve()`.
2. Call `.relative_to(vault.resolve())`. If the resolved target does
   not live under the resolved vault, the call returns an error
   without opening or touching the file.

Absolute paths (`/etc/passwd`) are also rejected — Python's
`Path(vault) / "/etc/passwd"` evaluates to `/etc/passwd`, which fails
the resolved-relative-to-vault check.

### The macOS symlink trap

On macOS, a naive single-resolve approach can be subverted by a
symlink inside the vault that points outside it. The path-traversal
guard therefore resolves both sides before comparing, and the
regression test at
[`tests/test_path_traversal.py`](../tests/test_path_traversal.py)
covers both the plain `../` case and the symlink case.

If you modify `obsidian_read` or `obsidian_write`, that test and
[`tests/test_writer.py::test_path_traversal_rejected`](../tests/test_writer.py)
must continue to pass.

---

## Atomic writes

Every mutation in `obsidian_write` writes to
`.<name>.tmp-<random-hex>` first and then atomically replaces the
target with `os.replace()`. Properties this buys:

- A crash or SIGKILL mid-write never leaves a half-written note.
- A reader (`obsidian_read`, `obsidian_search` reindex) that happens
  to run concurrently sees either the old version or the new
  version, never a partial write.
- On exception, the tmp file is cleaned up.

`rename` uses the same `os.replace` primitive on the source path.
`delete` uses `Path.unlink()` — not atomic in the same sense, but the
operation is inherently irreversible and there is no intermediate
state worth protecting.

---

## Memory poisoning (OWASP ASI06)

A write tool exposed via MCP is, by construction, a memory-poisoning
vector. Any prompt the agent reads — including content retrieved from
the vault itself, from a web page, from a tool response, from
indirect instructions embedded in a note — can in principle steer the
agent into calling `obsidian_write` with adversarial content. This is
not a bug in any specific component; it is a property of putting a
write tool into an LLM agent loop.

What the package does to reduce the risk:

- **Tool description as guidance.** The `obsidian_write` description
  itself tells the agent to be deliberate, to check for duplicates,
  to prefer small ops, and to use `dry_run` when uncertain. This
  nudges the model away from reflexive writes, but it is nudge, not
  enforcement.
- **No bulk ops.** One op per call. No `apply_many`, no batch
  rewrites. Each mutation is a separate tool invocation the client
  can log and, if you like, require approval on.
- **`dry_run`.** Letting the model preview before committing catches
  both honest mistakes and obviously-hostile payloads.
- **Frontmatter provenance (convention, not enforced).** `verified`
  and `confidence` fields let future sessions rank notes by trust.
  If a suspicious note gets through, subsequent human review can
  mark it `confidence: deprecated` rather than delete it — preserves
  forensics.

What the package deliberately does **not** do:

- It does not implement its own approval gate. That would require
  either an out-of-band UI (complex) or a blocking prompt to the
  user (clunky across clients). Approval, if you want it, is the
  client's job: Claude Code shows tool calls and their arguments
  before execution, Cursor likewise. Configure the client to require
  confirmation for `obsidian_write` if your threat model warrants it.
- It does not lock down specific ops behind a separate privilege
  level. All ops are equally available; rate-limiting or op-gating
  should happen at the client or reverse-proxy layer.

### Practical mitigations

- **Review tool calls in your client.** Claude Code's default
  behaviour shows tool arguments before execution. Do not disable
  that for this server.
- **Treat your vault as one trust domain.** If you are about to
  index somebody else's vault, don't. Prompt-injection payloads in
  notes are indistinguishable from legitimate content until the
  agent tries to act on them.
- **Keep backups.** `git init` in your vault costs nothing. An
  adversarial write to a tracked vault is a one-command revert.

---

## HTTP transport

The streamable-HTTP transport (`serve --transport http`) opens a
network endpoint on the host it runs on. Two defences ship by
default:

- **Bearer-token auth.** Set `OBSIDIAN_HTTP_TOKEN` to enable
  `Authorization: Bearer <token>` checks on every request. Missing
  or wrong token → 401 before the MCP layer is invoked.
- **Non-loopback refusal.** If the configured host is anything other
  than `127.0.0.1`, `localhost`, or `::1`, the server refuses to
  start without `OBSIDIAN_HTTP_TOKEN` set. The error is loud and
  points at the missing variable. No quietly-open network port.

What the package does **not** provide:

- **TLS.** Uvicorn can serve TLS directly (`--ssl-keyfile`,
  `--ssl-certfile`) but the integration is not wired into the CLI.
  For public-facing deployments, terminate TLS in nginx / caddy /
  Cloudflare in front of the uvicorn process.
- **Mutual TLS / OIDC / fancier auth.** If a Bearer token is not
  enough for your environment, put the server behind a reverse
  proxy that enforces whatever auth you need. The Bearer check stays
  on as defense in depth.
- **Rate limiting.** Ditto — reverse-proxy concern.

### Recommended loopback-only setup

For a single-user remote deployment where you just want your laptop
to talk to the MCP on a VM:

```bash
# On the VM
export OBSIDIAN_VAULT=$HOME/obsidian/vault
uvx second-brain-mcp serve --transport http --host 127.0.0.1 --port 8765

# On your laptop
ssh -L 8765:127.0.0.1:8765 user@vm
claude mcp add --transport http second-brain http://127.0.0.1:8765/mcp
```

No public port, no TLS headaches, no token required for the loopback
bind. The SSH tunnel is the auth.

---

## No network access during serving (apart from HTTP transport itself)

After the embedder is downloaded once (on first tool call), the
server's indexing and search paths run fully offline:

- The local embedder loads from the HuggingFace cache
  (`~/.cache/huggingface/`). No network request per call.
- The API embedder (`OBSIDIAN_EMBED_PROVIDER=openai`) does talk to
  its configured `/v1/embeddings` endpoint — that is the whole
  point of it. See [CUSTOMIZE.md](./CUSTOMIZE.md).
- ChromaDB persists to a local directory
  (`$OBSIDIAN_INDEX_DIR/index/`). No remote database.
- No telemetry. The server does not phone home.

The first-run bge-m3 download is the only implicit network event,
and it is performed by `sentence-transformers` against HuggingFace
directly — the server does not proxy or re-publish it.

---

## No secrets in vault

The indexer embeds whatever text is in your `.md` files. If you paste
an API key, database password, or any other credential into a note,
that text ends up in the ChromaDB index — and any agent with access
to the MCP server can surface it through semantic search.

**Recommendation:** keep secrets out of the vault entirely. Put them
in a password manager, `.env` files outside the vault, or a secrets
backend. If you need to write a note *about* a secret (where it
lives, how it rotates), describe the location without including the
value.

If you discover a secret has been indexed:

1. Remove the text from the note and save (or use
   `obsidian_write` op=`replace_text`).
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
- The version of `second-brain-mcp` you tested against
  (`uvx second-brain-mcp --version` or the `version` field of
  `pyproject.toml`).

Reports are acknowledged within a few days. Fixes land through a
normal patch release with the reporter credited in the release notes
unless anonymity is requested.
