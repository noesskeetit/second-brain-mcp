# Write workflow — `to_obsidian`

`second-brain-mcp` exposes exactly one prompt: `to_obsidian`. It is the
only path by which new notes enter the vault. This document explains what
it does, why each step exists, and which conventions make the resulting
notes useful for future sessions.

---

## What `to_obsidian` is

`to_obsidian` is an MCP **prompt** — not a tool. The server returns a
text template via `prompt/get`; the agent reads the template, follows the
seven-step workflow, and uses its own client's write tool (Claude Code's
`Write`, Cursor's edit, Zed's equivalent) to put new `.md` files directly
into `$OBSIDIAN_VAULT`. The server itself never touches the vault.

How to invoke:

| Client       | Invocation                                    |
|--------------|-----------------------------------------------|
| Claude Code  | `/mcp__second-brain__to_obsidian`             |
| Cursor       | prompt picker → `second-brain / to_obsidian`  |
| Zed          | prompt picker → `second-brain / to_obsidian`  |
| Generic MCP  | `prompts/get name="to_obsidian"`              |

You invoke the prompt at the end of a working session, when you want the
agent to consolidate what was learned into durable notes.

---

## The seven steps

The prompt text instructs the agent to walk the following sequence. The
rationale below explains why each step exists — useful for the agent when
edge cases come up, and useful for you when reviewing candidates.

### 1. Walk the session and classify candidates

The agent reviews the current conversation for new, persistent knowledge:
facts about external systems, decisions with rationale, preferences, new
or updated projects, external resources. Each candidate is classified
into a category (see below).

**Why.** Without classification, notes pile into a single bucket and the
vault becomes a flat log. Categories scope search (`type_filter`) and
keep `_index.md` navigable.

### 2. Check for duplicates via `obsidian_search`

For each candidate, the agent runs a **semantic** search against the
existing vault. The intent is to find near-duplicates, not exact string
matches.

**Why.** The most common mistake in curated memory is restating something
that already exists in slightly different wording. Semantic dedup catches
this; keyword grep does not. When a duplicate is found, the agent
proposes an update or a wikilink rather than a new note.

### 3. Frame each insight as an atomic statement

One statement = one note. The filename is the statement itself, written
as a complete phrase, around 60 characters long.

**Why.** An atomic statement as a filename is searchable, skimmable, and
unambiguous. It forces the agent to commit to a single claim per note,
which in turn makes supersedes straightforward — you replace a claim
with a better claim, not a document with a document.

### 4. Show the user the candidate list for approval

The agent presents the candidates as `category/Name.md — why it matters`
and waits for your response. You can accept all, reject some, ask for
two to be merged, or ask for a rewrite.

**Why.** Human-in-the-loop at this step is the difference between
curated memory and an autonomously-expanding pile. It is also the
defence against memory poisoning (see below).

### 5. Write the notes via the client's own write tool

After approval, the agent creates files under
`$OBSIDIAN_VAULT/<category>/<Name>.md` using its own write tool —
Claude Code's `Write`, Cursor's edit, Zed's equivalent. Obsidian picks
the files up through its file watcher without user action.

**Never use `obsidian-cli create`** to create notes. Obsidian's URI
scheme forces the Obsidian app to the foreground on every call, which
interrupts whatever the user is doing. Writing `.md` files directly
through the agent's normal write tool is both faster and silent — the
file watcher handles the rest.

Each file contains:

- Frontmatter per the template (see below).
- A body beginning with `# Heading` matching the filename.
- `[[wikilinks]]` to relevant existing notes surfaced in step 2.

### 6. Update `_index.md`

The agent adds a line for each new note under the correct section of
`_index.md`, preserving the existing ordering and formatting style.

**Why.** `_index.md` is the human-curated navigation layer that
`obsidian_overview` returns whole at the start of every session. Keeping
it current means future sessions know what exists in the vault without
having to search blindly.

### 7. Handle supersedes

If a new note contradicts an existing one, the existing note is **not
deleted**. Instead:

- The old note's frontmatter is updated:
  `confidence: deprecated`, `superseded_by: "[[new note]]"`.
- The new note's body includes a short note: *replaces
  [[old note]]*.

**Why.** Deletion loses provenance. A deprecated note still answers the
question "did I ever believe X?" which is useful when you are debugging
why a decision looked right at the time.

---

## Why the file is written by the client's write tool, not by the server

`second-brain-mcp` deliberately exposes **no write tools over MCP**. All
writes go through the agent's own write tool. This design choice has
three reasons.

**Memory-poisoning defence.** Any write tool over MCP is a
memory-poisoning vector (OWASP ASI06). An attacker crafting a prompt that
triggers the write tool can add arbitrary content to the agent's memory.
With no write tool in the server and a hard approval gate in the prompt
workflow, the only way a note enters the vault is with a human saying
"yes" to a specific candidate list.

**No app-focus hijack.** `obsidian-cli create` uses Obsidian's URI
scheme, which forces the Obsidian desktop app to the foreground on every
invocation. Writing `.md` files directly through the agent's write tool
is silent — Obsidian's file watcher picks them up without stealing focus.

**Client-agnostic behaviour.** Clients already have battle-tested write
tools with diffs, undo, and permission prompts. Wrapping that in MCP
would duplicate functionality and lose the per-client UX refinements.

---

## Why human-in-the-loop

Every autonomy step the industry has tried for memory — LLM-driven
extraction, reflection, compaction — has run into the same three failure
modes:

- **Memory poisoning (OWASP ASI06).** An attacker injects prompts that
  cause the agent to commit attacker-chosen "facts" to memory.
- **Cascading errors in reflection.** A bad summary gets stored, which
  biases the next reflection, which stores a worse summary, and so on.
- **Over-accommodation.** The agent, eager to please, stores things the
  user only half-meant.

The `to_obsidian` approval gate short-circuits all three. You read the
list, you say yes or no. It takes under a minute at the end of a
session. There is currently no reliable automated substitute for that
minute.

---

## Frontmatter conventions

| Field            | Values                                               | Meaning                                                                         |
|------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `type`           | `knowledge` \| `project` \| `insight` \| `me` \| `reference` | Purpose of the note; used by `obsidian_search` as `type_filter`.          |
| `verified`       | ISO date (`YYYY-MM-DD`)                              | When the statement was last confirmed true. Used by future age-aware ranking.   |
| `confidence`     | `high` \| `medium` \| `low` \| `deprecated`          | Trust level. `deprecated` marks superseded notes; others used by future ranking. |
| `superseded_by`  | `"[[new note]]"` (wikilink in a string)              | Present only on deprecated notes. Points to the replacement.                    |

Example frontmatter for a new note:

```yaml
---
type: knowledge
verified: 2026-04-15
confidence: high
superseded_by:
---
```

Example frontmatter for a deprecated note:

```yaml
---
type: knowledge
verified: 2025-09-01
confidence: deprecated
superseded_by: "[[API endpoint moved to v2]]"
---
```

---

## Categories

Categories are suggestions, not a schema. The agent adapts to whatever
structure your vault already has.

| Category      | Contents                                                                 |
|---------------|--------------------------------------------------------------------------|
| `me/`         | Preferences, working style, personal context the agent should remember.  |
| `projects/`   | Per-project state, decisions, open threads, done criteria.               |
| `knowledge/`  | Facts about external systems (APIs, tools, libraries, behaviours).       |
| `insights/`   | Reasoning, analyses, conclusions, "why we decided X".                    |
| `ref/`        | External resources — links, quotes, pointers to papers or docs.          |

If your vault uses different top-level folders, the agent should follow
your convention. The prompt text tells it so explicitly.
