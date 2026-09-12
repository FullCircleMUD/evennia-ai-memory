# DESIGN Index

Map of all design documents in this directory, organised by category. Add new documents here when they land — un-indexed documents are invisible.

## For a consumer

- **[installing.md](installing.md)** — everything a consumer does to get the library running: the eight numbered steps, the required and optional settings, what is not checked for you, and what to do when something goes wrong.

## Process and discipline

- **[progress.md](progress.md)** — running log of milestones with links to evidence.
- **[test-plan.md](test-plan.md)** — every test case the library commits to covering, with stable IDs and the test function that covers each. Written before the tests; the empty `Test function` cells are the outstanding work. Also carries the open behavioural decisions the cases depend on.

## Architecture and design

- **[interoperability.md](interoperability.md)** — this library against every sibling library in `libraries/`: the relationship and the considerations or explicit clearance for each.

*(No architecture documents yet. What the library does is covered by the test plan's per-surface prose and by `installing.md`; a design document lands when a decision needs more room than either gives it.)*

## Archive

Historical context, not authoritative. Material in `archive/` is preserved per the "don't delete; supersede" principle.

*(The archive is currently empty. If substrate material later emerges — design notes carried over from the `src/game/ai_memory/` extraction, or brainstorming captured before a decision crystallised — it lands here.)*
