# Roadmap

v1.0 ships the read + write loop on top of a plain ChromaDB + bge-m3
baseline. The items below are planned follow-ups. Each one is contained
enough to be a good first-contribution PR.

---

## v1.1 — Trust-aware ranking

Multiply `similarity` by a booster read from `fm_confidence`:

| `fm_confidence` | Boost |
|-----------------|-------|
| `high`          | 1.15  |
| `medium`        | 1.00  |
| `low`           | 0.85  |
| `deprecated`    | 0.40  |

Re-sort after boosting. Roughly 5 lines in `indexer.search()`.

Effect: deprecated notes fall to the bottom of results; high-confidence
notes surface first when similarity ties. Makes the `superseded_by`
mechanism actually change what the agent sees, rather than just leaving
the old note around unweighted.

---

## v1.2 — Age-aware decay

For notes with `type ∈ {knowledge, reference}` and a `verified` date
older than 90 days, apply `exp(-age_days / 180)` to the similarity
score. Does not hide anything — just biases ranking toward fresher
facts.

Effect: solves the stale-API-endpoint problem. A reference note written
two years ago about an external service still surfaces if nothing newer
covers the same ground, but any newer note outranks it when both match
the query. Roughly 10 lines in `indexer.search()`.

---

## v1.3 — Inline `#tag` filter

Parse hashtags (`#example-tag`) from note bodies during indexing, store
as a comma-separated string in chunk metadata (ChromaDB `where` filters
do not accept lists), and expose a `tag_filter` parameter on
`obsidian_search` parallel to the existing `type_filter`.

Effect: users who already tag notes inline get filter granularity below
`type`. No change for users who don't use hashtags — the field is
simply empty.

---

## v1.4 — Hierarchical `_index.md` for large vaults

When a vault grows past ~500 notes, `_index.md` bloats the response of
`obsidian_overview` enough to eat meaningful token budget. Switch to
returning top-level sections plus only the sections that contain
query-relevant notes (with the query inferred from recent search
history or the first message of the session).

Effect: overview stays compact at any vault size. Not urgent until
that scale threshold is hit in practice.

---

## Non-goals

Explicitly off the roadmap. These will not ship in this package; if
they happen at all, they belong in separate projects.

- **Auto-LLM-extraction, auto-reflection, compaction loops.** Memory
  poisoning risk, cascading-error risk, and over-accommodation are all
  real failure modes with no good automated defence today.
  Human-in-the-loop through `to_obsidian` is the whole point.
- **Write tools exposed via MCP.** See
  [docs/SECURITY.md](docs/SECURITY.md). Any MCP write tool is a
  memory-poisoning vector.
- **Multi-user / shared memory.** Single-vault by design. Multi-user
  memory has its own set of problems (inconsistency across agents,
  trust propagation, access control) that this package intentionally
  sidesteps.
- **Graph database backend.** Wikilinks plus the backlinks sidecar give
  enough graph structure for the two navigation tools that exist. A
  real graph DB buys nothing until there is a feature that needs
  multi-hop queries, and none is planned.
