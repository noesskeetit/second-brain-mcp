# src/second_brain_mcp/prompts.py
"""MCP prompt exposing the `/to_obsidian` write workflow.

Surfaced via `prompts/list` + `prompts/get` so any MCP client (Claude Code,
Cursor, Zed, generic agents) can invoke the workflow without per-client
CLAUDE.md / AGENTS.md boilerplate.
"""

from __future__ import annotations

import mcp.types as types

TO_OBSIDIAN_TEXT = """You are being asked to commit session knowledge into an Obsidian vault.
Follow these steps precisely; do not skip the approval gate.

1. Walk the session. Identify candidate new knowledge and classify into:
   - knowledge/<domain>/  — a fact about an external system, API, tool
   - insights/            — a distilled conclusion or cross-domain observation
   - me/                  — a personal preference or role detail
   - projects/<name>/     — a new or updated project fact/milestone
   - ref/                 — a pointer to an external resource

2. For each candidate, call `obsidian_search` semantically (not literally) to
   check for duplicates. Often something close already exists; update or link
   to it rather than creating a new note.

3. Frame each insight as an atomic statement. One statement = one note. The
   filename IS the statement, around 60 characters, reading as a full sentence.

4. Show the user a list of candidates for approval BEFORE writing anything.
   Format each line as:
       category/Filename.md — short reason
   Honor the user's decisions: "write them all", "skip this one", "merge
   these two" — obey literally.

5. After approval, write each approved note using YOUR CLIENT'S write tool
   (Claude Code Write, Cursor edit, etc.) directly into:
       $OBSIDIAN_VAULT/<category>/<Filename>.md
   DO NOT use `obsidian-cli create` — it forces the Obsidian app to the
   foreground. Obsidian's file watcher will pick up plain writes automatically.

   Each note must contain:
     - YAML frontmatter with:
         type: <knowledge|project|insight|research|me|reference>
         verified: <today's ISO date>
         confidence: high        # default; use medium/low when genuinely uncertain
         superseded_by: ""       # fill in only when replacing an earlier note
     - A body starting with "# <Title>" matching the filename (sans .md)
     - [[wikilinks]] to related existing notes found in step 2

6. Update `_index.md` — add one line per new note to the appropriate section,
   preserving existing ordering and style.

7. Handle contradictions. If a new note replaces an older one:
   - DO NOT delete the old note.
   - Mark its frontmatter: confidence: deprecated, superseded_by: "[[new note title]]".
   - In the new note's body add a line: "Replaces [[old note title]]."

RULES FOR WRITE OPERATIONS
- Never write to the vault automatically; always triggered by the user's
  `/to_obsidian` command (or equivalent explicit intent).
- Never do bulk operations (delete / rename / re-categorize) without a
  separate explicit approval round from the user.
"""


TO_OBSIDIAN_PROMPT = types.Prompt(
    name="to_obsidian",
    description=(
        "Curate session knowledge into the Obsidian vault with an approval "
        "gate. Use at the end of a session or whenever the user says "
        "/to_obsidian."
    ),
    arguments=[],
)


def get_to_obsidian() -> types.GetPromptResult:
    return types.GetPromptResult(
        description="Curated vault write workflow with human-in-the-loop approval",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=TO_OBSIDIAN_TEXT),
            )
        ],
    )
