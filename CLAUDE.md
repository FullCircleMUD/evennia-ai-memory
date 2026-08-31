# CLAUDE.md

> **Project-wide working rules and cross-repo context live in the FCM umbrella repo's `CLAUDE.md`**,
> loaded automatically when you work from the umbrella root. If you opened this repo directly instead
> of via the umbrella, relaunch from the umbrella root for the full context. This file holds only this
> repo's specific instructions.

Instructions for Claude (and other LLM agents) working in this repository.

## What this project is

`evennia-ai-memory` stores what an NPC knows and what it remembers, and retrieves both semantically. It
provides two embedding-backed memory systems — **lore** (shared world knowledge, filtered per NPC by
scope tags) and **interaction memory** (per-NPC, per-speaker conversation history) — over a dual storage
backend: pgvector on PostgreSQL, numpy cosine similarity on SQLite. Tagline: **"Embedding-backed memory
and lore for LLM-driven NPCs."**

The library is Evennia-flavoured by intended audience but is **not coupled to Evennia at runtime**: it
is a Django app and nothing more. What an NPC *does* with what it remembers, and how that reaches a
prompt, belong to the consumer.

For the big-picture overview, read [README.md](README.md).
For the design wiki, read [docs/INDEX.md](docs/INDEX.md).

## Project status

For the current state of the project — milestones reached, what's pending — see
[docs/progress.md](docs/progress.md), the running log of milestones with links to evidence.

The library is being extracted from FullCircleMUD's `src/game/ai_memory/` Django app, where lore and
interaction memory were built and proven. That app is the substrate for this library's initial code
drop.

## Where to read first

For any non-trivial task, start by reading in this order:

1. [README.md](README.md) — what the project is, status, quick start.
2. [docs/INDEX.md](docs/INDEX.md) — map of all design docs.

## The starting point

**Replicate the existing system.** The library is FCM's `src/game/ai_memory/` service module lifted into
a package: the same two tables, the same function signatures, the same behaviour on the same rows. The
test of a correct extraction is that a consumer can delete the coupled game code, install the library,
rename a few call sites, and have everything run as before.

Departures need a reason that has actually been discussed and agreed. Every sanctioned one is listed,
with the cases that encode it, under *Departures* in [docs/test-plan.md](docs/test-plan.md). A change
that is not there is not sanctioned, however sensible it looks — including one that fixes something.
Whether more of the game later moves into the library is a separate question, taken case by case once
the baseline is in.

## Load-bearing architectural principles

These are the principles every implementation decision must respect. Getting them wrong is expensive to
undo.

1. **The library does not own game concepts.** NPCs, mobs, rooms, zones, factions, quests — none of
   these belong here. The library stores rows keyed by identifiers and tags the consumer supplies, and
   ranks them by similarity. What an identifier *means*, and where a scope tag comes from, is the
   consumer's concern.
2. **No FCM-specific assumptions.** This library is extracted from infrastructure that originated in
   service of FullCircleMUD (FCM). Anything FCM-specific creeping in is a code smell — zone names,
   faction vocabularies, tier taxonomies, prompt-variable names all belong to the consumer. Default to
   "consumer concern" when uncertain.
3. **The library owns the embeddings client and ships no provider defaults.** It calls the embeddings
   endpoint itself, configured from Django settings through accessors in `config` rather than by
   reading `settings` directly — the pattern `evennia-shards` uses. Endpoint, key and model are all
   required: a default base URL or model name would choose a provider on the consumer's behalf and bury
   that choice in library code. Absent any of them, the app refuses to start with an error naming the
   setting and where to put it.

   **No rate limiting and no cost tracking.** A consumer caps spend where the provider already offers
   it — an API key carrying a budget — and reads usage from the provider's own dashboard. Rebuilding
   either here duplicates a control the consumer already has, less well, and it is not a thing a MUD
   needs to own.
4. **Retrieval returns data, never prompt text.** Searches return structured results. Formatting them
   into a prompt, choosing a template, and deciding what an NPC says are all the consumer's. The
   library ships no prompt and no phrasing.
5. **Memory lives in its own database.** The tables sit behind a dedicated router on a separate
   database alias, so rebuilding the consumer's game database does not erase what NPCs have learned.
6. **Only the log shim touches Evennia.** `log.py` writes every line to the library's own
   `ai_memory.log` under the running instance's `LOG_DIR`, through Evennia's `logger.log_file` — the
   same shim `evennia-shards` and `evennia-message-bus` use, and the reason an operator debugging a
   dropped memory reads one file instead of the whole server log. Outside an Evennia engine it is a
   silent no-op. Every other module stays framework-neutral: the library's logic needs Django's ORM
   and nothing else, and XC-01 asserts it.

## Out of scope

Scope boundaries are decided as concrete questions arise, by applying the principles above. These
rulings are settled:

- **Rate limiting and cost tracking** — the consumer's, handled at the API provider. See principle 3.
- **Combat memory** — future work, outside this library's current scope. The substrate carries a
  `CombatMemory` model and migrations, but nothing calls them and no store or search service was ever
  written. The schema will change once there is a strategy bot to serve, so extracting it now would be
  extracting a guess. `[TBD — needs discussion: whether it later lands here or in a library of its
  own.]`
- **Chat completions** — `evennia-llm-service`'s.
- **Retrieval only, in stage 1.** `store_lore` and the import command are stage 2; until then the lore
  table is populated from outside the library.
- **`get_recent_lore`** — dropped. Its only job was being a fallback the library no longer performs, and
  "most recently updated" is not a useful answer to a lore question.
- **Prompt templates and prompt assembly** — the consumer's. Template loading is mechanism that belongs
  to the LLM-service layer; the templates themselves belong to the game.
- **Evennia typeclasses and mixins** — the consumer's integration layer. Commands are not: administering
  the library's own table is infrastructure, not a game concept, which is why the lore commands ship in
  core rather than `contrib/`, the same as `evennia-world-builder`'s `wb_build`.
- **Resolving scope tags** from room tags, faction tags or anything else — the consumer passes a plain
  `list[str]`.

Open questions, to be picked up deliberately:

- `[TBD — naming only: the settings are proposed as `AI_MEMORY_EMBEDDING_API_KEY`,
  `AI_MEMORY_EMBEDDING_BASE_URL` and `AI_MEMORY_EMBEDDING_MODEL`, following the sibling convention of
  prefixing by library.]`
- `[TBD — needs discussion: whether the embedding dimension stays fixed at 1536 or becomes a
  library-level setting. Configurable dimensions mean the migration reads the setting, the numpy path
  needs a length guard, and changing it on a live install requires re-embedding everything, since
  vectors from two models are not comparable.]`
- `[TBD — needs discussion: whether the substrate's migrations are carried across or squashed to a
  single initial migration.]`
- `[TBD — later stage: whether the lore YAML importer moves into this library, and where the validator
  that gates an import lives. It also decides whether `evennia-yaml-reader` becomes a dependency. Out
  of scope for stage 1 — see *Out of scope* above.]`
- `[TBD — needs discussion: whether `get_last_interaction_time` keeps returning a relative-time phrase
  alongside the timestamp, as it does today.]`
- `[TBD — needs discussion: whether an Evennia integration mixin ships as `contrib/`. No `contrib/`
  exists today, per the standards' rule against scaffolding one empty.]`

## Working conventions

- **Editing design docs.** Update or add design documents whenever an architectural decision is made or
  refined. Capture the *why*, not just the *what*. Index new docs in [docs/INDEX.md](docs/INDEX.md).
- **Don't put implementation detail in this file or README.** Link out to docs/ instead. Keep CLAUDE.md
  and README.md stable; let docs/ churn.
- **License.** BSD 3-Clause. Source files carry an SPDX header on the first line
  (`# SPDX-License-Identifier: BSD-3-Clause`).

## Documentation discipline (load-bearing)

Design documents in `docs/` must reflect decisions **actually discussed and agreed on with the project
owner**. They are not a place to forward-design the system from first principles or extrapolate
"reasonable defaults" from a starting point.

**Rules:**

1. **Only capture what was discussed and agreed.** If the conversation establishes a principle (e.g.
   "the library never calls a provider"), do not extrapolate it into specifics that were not raised
   (e.g. a chosen retry policy, a particular injection API shape).
2. **Flag open questions explicitly.** Where a topic has been raised but not resolved, write
   `[TBD — needs discussion: <what is open>]` in the doc. Future sessions then pick the topic up
   deliberately rather than inheriting unagreed assumptions.
3. **Distinguish archived material from in-conversation decisions.** Material in `docs/archive/` is
   preserved historical context, not authoritative. Restating it in new docs is acceptable when it
   provides necessary context, but mark it as such.
4. **Smaller is better.** A doc that captures three discussed points faithfully is more useful than one
   that captures three discussed points plus seven invented ones. Resist the urge to fill out sections
   "for completeness."

If a session catches itself writing content that goes beyond what was discussed, stop and either remove
the extrapolation or convert it to a `[TBD]` marker.

## Repository layout

```
evennia-ai-memory/
├── CLAUDE.md                  # this file
├── README.md
├── LICENSE                    # BSD 3-Clause
├── pyproject.toml
├── runtests.py                # standalone test runner (Django bootstrap, no Evennia)
├── .gitignore
├── docs/                      # technical wiki (humans + LLMs)
│   ├── INDEX.md
│   ├── progress.md
│   ├── interoperability.md
│   └── archive/               # historical context (currently empty)
├── src/
│   └── evennia_ai_memory/     # library code (src layout)
│       ├── __init__.py
│       ├── apps.py            # AppConfig; ready() validates the settings
│       ├── config.py          # settings accessors, database resolution
│       ├── db_router.py       # routes the models to their own alias
│       ├── log.py             # shim onto Evennia's logger → ai_memory.log
│       ├── models.py          # NpcMemory, LoreMemory
│       ├── services.py        # the public functions
│       ├── migrations/
│       └── tests.py           # unit tests, run via runtests.py
└── tests/                     # standalone test infrastructure
    ├── __init__.py
    ├── test_settings.py       # Evennia defaults, two DB aliases, the router
    └── urls.py
```

Note: no `examples/` yet (no demo gamedir), and no `contrib/` (nothing opt-in exists; the standards
forbid scaffolding one empty).

## Tools and environment

- Python 3.10+ (pinned via `pyproject.toml`).
- Runtime dependencies: `django`, `dj-database-url`, `evennia` (the log shim only — see principle 6),
  `numpy`, `openai` (the embeddings client; the SDK speaks to any OpenAI-compatible endpoint, so the
  provider is a config value), `pgvector`, `psycopg`.
- **Tests use Django's test runner** via `runtests.py`, which bootstraps Django then calls
  `evennia._init()`, as the siblings do. No gamedir required.
- Dedicated venv at `evennia-ai-memory/venv/` (gitignored). Development install via `pip install -e .`.

## Sibling libraries to reference

When in doubt about a convention not covered here, look at how a sibling library does it:

- **[../evennia-shards/](../evennia-shards/)** — full Evennia-bootstrapped library with Django test
  settings and its own migrations. Reference for the Django app shape and the test-runner pattern.
- **[../evennia-yaml-reader/](../evennia-yaml-reader/)** — how to document a deliberate divergence from
  the library standards in `CLAUDE.md`.
- **[../evennia-archive/](../evennia-archive/)** — the other library that writes to a second database
  alias behind its own router.
- **[../evennia-llm-service/](../evennia-llm-service/)** — imports this library; owns chat completions
  and the prompt-template mechanism.
