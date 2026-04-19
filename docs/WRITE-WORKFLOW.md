# Write workflow — `obsidian_write`

`second-brain-mcp` exposes one write tool: `obsidian_write`. It is a
single dispatcher with eight operations (`op` field), covering every
mutation an agent should reasonably make to the vault. This document
explains what the tool does, when to prefer each op, and the
conventions that make resulting notes useful for future sessions.

---

## The one tool

`obsidian_write` is an MCP **tool**, not a prompt. The agent calls it
directly — no `prompts/get` indirection, no client-side scaffolding.
The tool's own description tells the model the rules of engagement;
there is no separate template to load.

| Client       | Invocation                                    |
|--------------|-----------------------------------------------|
| Claude Code  | Tool appears alongside other MCP tools; ask the agent to "add a note" or "update the frontmatter of X" and it picks `obsidian_write`. |
| Cursor       | Same — tool picker → `second-brain / obsidian_write`. |
| Zed          | Same. |
| Generic MCP  | `tools/call name="obsidian_write" arguments={...}` |

You do not need a slash command to trigger it. If you want a
session-end "commit what we learned" ritual, wire it into your
client's CLAUDE.md / system prompt — that is where it belongs,
not inside the MCP server.

---

## Operations

All ops take a vault-relative `path` and support `dry_run=true`,
which returns `{before, after}` without touching disk.

| `op`              | Required args                          | What it does                                                                   |
|-------------------|----------------------------------------|--------------------------------------------------------------------------------|
| `create`          | `path`, `body`, `frontmatter?`         | New note. Fails if the file exists unless `overwrite=true`.                    |
| `append`          | `path`, `text`, `separator?="\n\n"`    | Append text to the end of the body. Frontmatter untouched.                     |
| `prepend`         | `path`, `text`, `separator?="\n\n"`    | Insert text right after the frontmatter block.                                 |
| `replace_body`    | `path`, `body`                         | Swap the whole body. Frontmatter preserved.                                    |
| `replace_text`    | `path`, `find`, `replace`, `regex?`, `count?` | Find/replace inside the body. Literal by default; `regex=true` = Python re with MULTILINE+DOTALL. |
| `set_frontmatter` | `path`, `updates?`, `remove_keys?`     | Merge keys into frontmatter and/or remove keys. Body untouched.                |
| `delete`          | `path`                                 | Delete the note.                                                               |
| `rename`          | `path`, `new_path`                     | Move / rename. Does NOT rewrite `[[wikilinks]]` in other notes.                |

### Rules of engagement

The tool description embeds short guidance the agent should follow:

1. **Deliberate, not reflexive.** Don't write whenever a conversation
   turn produces a fact. Write when the user says so, or when the
   session has clearly established something durable the user wants
   remembered.

2. **Check for duplicates with `obsidian_search` before `create`.**
   Semantic search catches near-duplicates that keyword grep misses.
   When a duplicate is found, prefer `append` / `set_frontmatter` /
   `replace_text` on the existing note over forking a near-identical
   new one.

3. **One atomic statement per note.** The filename IS the statement,
   around 60 characters, a full sentence. Two facts = two notes.

4. **Prefer small ops.** `set_frontmatter` to bump `verified`,
   `replace_text` for a typo, `append` for an addendum — all beat a
   whole-note rewrite. Small ops are easier to review, easier to
   revert, and preserve the note's history in the backing filesystem.

5. **Use `dry_run=true` when uncertain.** Especially for
   `replace_text` with a regex and for `delete`. The tool returns
   `{before, after}` so the agent (and you, reading the transcript)
   can inspect the change before committing.

---

## Safety invariants

Every op runs these checks, no exceptions:

- **Path traversal guard.** `path` is joined onto the vault root, the
  result is `.resolve()`d, and the resolved path must still live under
  `vault.resolve()`. Absolute paths (`/etc/passwd`) and parent escapes
  (`../../outside.md`) both fail closed with `{"ok": false, "error":
  "path escapes the vault: ..."}`.
- **Atomic writes.** Every mutation writes to `.<name>.tmp-<random>`
  first, then `os.replace`s into place. A crashed server or SIGKILL
  mid-write never leaves a half-written note. The tmp file is cleaned
  up on exception.
- **Reindex on success.** Any op that actually touched disk
  (`changed: true`, not `dry_run`) triggers an incremental reindex
  before returning. The next `obsidian_search` call reflects the edit
  immediately.

See [SECURITY.md](./SECURITY.md) for the full threat model, including
memory poisoning considerations now that a write tool exists.

---

## Frontmatter conventions

The tool does not enforce a schema — you can set any keys you like.
Conventions below are what the stock protocol text and the indexer
understand for filtering and ranking.

| Field            | Values                                               | Meaning                                                                         |
|------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `type`           | `knowledge` \| `project` \| `insight` \| `me` \| `reference` | Purpose of the note; used by `obsidian_search` as `type_filter`.          |
| `verified`       | ISO date (`YYYY-MM-DD`)                              | When the statement was last confirmed true.                                     |
| `confidence`     | `high` \| `medium` \| `low` \| `deprecated`          | Trust level. `deprecated` marks superseded notes.                               |
| `superseded_by`  | `"[[new note]]"` (wikilink in a string)              | Present only on deprecated notes. Points to the replacement.                    |

Example call — create a new knowledge note:

```json
{
  "op": "create",
  "path": "knowledge/api/Rate limit is 300 req/min per token.md",
  "frontmatter": {
    "type": "knowledge",
    "verified": "2026-04-16",
    "confidence": "high",
    "superseded_by": ""
  },
  "body": "# Rate limit is 300 req/min per token\n\nObserved against prod 2026-04-14. See [[Token rotation happens at midnight UTC]]."
}
```

Example call — bump a verification date without touching body:

```json
{
  "op": "set_frontmatter",
  "path": "knowledge/api/Rate limit is 300 req/min per token.md",
  "updates": {"verified": "2026-05-01"}
}
```

Example call — deprecate an old note and link forward:

```json
{
  "op": "set_frontmatter",
  "path": "knowledge/api/Old endpoint is v1.md",
  "updates": {"confidence": "deprecated", "superseded_by": "[[Endpoint is v2 as of 2026-03]]"}
}
```

---

## Categories

Categories are suggestions, not a schema. If your vault uses different
top-level folders, use them — the write tool does not require any
particular layout.

| Category      | Contents                                                                 |
|---------------|--------------------------------------------------------------------------|
| `me/`         | Preferences, working style, personal context the agent should remember.  |
| `projects/`   | Per-project state, decisions, open threads, done criteria.               |
| `knowledge/`  | Facts about external systems (APIs, tools, libraries, behaviours).       |
| `insights/`   | Reasoning, analyses, conclusions, "why we decided X".                    |
| `ref/`        | External resources — links, quotes, pointers to papers or docs.          |

---

## Handling supersedes

When a new fact contradicts an older note, do **not** `delete` the
old one:

1. `set_frontmatter` on the old note: `confidence: deprecated`,
   `superseded_by: "[[new note title]]"`.
2. `append` or `create` the new note; include `replaces
   [[old note title]]` in the body.

Deletion loses provenance. A deprecated note still answers "did I
ever believe X?" which is useful when debugging why a past decision
looked right at the time.

---

## `_index.md`

`obsidian_overview` returns `_index.md` whole at session start, so it
is the navigation layer the agent reads first. After creating a new
note, update `_index.md` with `obsidian_write` op=`append` or
op=`replace_text` so the new note is discoverable without a full
search pass. Keep the ordering and formatting style the file already
uses.
