---
type: knowledge
verified: 2026-04-15
confidence: high
superseded_by: ""
---

# EXAMPLE-note

One filename = one atomic statement, around 60 characters. The H1 title
should match the filename (minus `.md`).

Bodies can reference other notes with wikilinks, e.g. [[_index]]. The
indexer extracts these links and builds a backlinks sidecar so
`obsidian_backlinks` can navigate the graph.

## Sections

Notes longer than ~1500 characters are chunked by `##` / `###` headers.
Shorter notes are embedded whole.

## Tags for `type`

Use one of: `knowledge`, `project`, `insight`, `research`, `me`, `reference`.
Other values are stored but not used by the default `type_filter`.

## Supersedes

When a note replaces an older fact, set `superseded_by: "[[new note]]"` on
the old note and add a "Replaces [[old note]]" line to the new note's body.
