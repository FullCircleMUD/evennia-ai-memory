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

The extraction baseline is in: both memory systems, the embeddings client and the lore commands work,
and the suite covers them on SQLite. The PostgreSQL cases are agreed and not yet run. FCM's
`src/game/ai_memory/` Django app is the substrate this replicates — see *The starting point* for what
that constrains.

## Where to read first

For any non-trivial task, start by reading in this order:

1. [README.md](README.md) — what the project is, status, quick start.
2. [docs/test-plan.md](docs/test-plan.md) — **where a behavioural change starts.** A case lands here
   before the test, and the test before the code.
3. [docs/INDEX.md](docs/INDEX.md) — map of all design docs.
4. [docs/progress.md](docs/progress.md) — what actually exists right now.

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
4. **The functions never dispatch off the calling thread.** Every public function is synchronous and
   returns; wrapping the call is the consumer's. That is what lets a consumer put a memory lookup, a
   prompt render and a completion in *one* `deferToThread` — a library that deferred internally would
   force a hop inside a hop and make the siblings awkward to compose.

   The lore commands are the exception, and only because they cannot be anything else: a superuser
   types a command, it runs on the reactor, and there is no caller above it to hand the dispatch to. So
   the command dispatches its own work and closes its worker's database connections itself. Nothing in
   the data layer does. XC-04 and XC-14 assert both halves.

5. **The library never chooses words, in either direction.** A consumer writes the summary of an
   interaction and the library embeds it; a search hands back structured results and the consumer
   phrases them. Only the consuming game knows how its own events read, which is why
   `interaction_type` is unvalidated and why no template lives here.

   Searches return structured results. Formatting them
   into a prompt, choosing a template, and deciding what an NPC says are all the consumer's. The
   library ships no prompt and no phrasing.
6. **Memory lives on an alias of its own, and the cascade places it.** The library declares its
   alias in [db_spec.py](src/evennia_ai_memory/db_spec.py) and `evennia-database-cascade` derives the
   `DATABASES` entry, the router and the migration list from that one declaration. The point is that
   rebuilding the consumer's game database does not erase what NPCs have learned.

   **The shared rung stays open, deliberately.** A single-instance game can reasonably keep these
   tables in its own database, and nothing here shares a table name with the framework, so the alias
   gets a second set of tables rather than Evennia's. What such a consumer gives up is the memories
   when they rebuild — their call to make, which is why `allow_sharing_common_db` is left at its
   default rather than refused.

7. **Test-first.** A case lands in [docs/test-plan.md](docs/test-plan.md), then the test, then the
   code. The plan is a commitment rather than a wishlist, and its `Test function` column is the
   coverage trail, checked both ways. See
   [test-first-process.md](../../design/test-first-process.md).
8. **Use Evennia freely; own nothing the consumer defines.** The library runs inside Evennia and only
   inside it, so its core infrastructure — a `Command`, a cmdset — is the platform, not a
   compromise. `log.py` binds `ai_memory_log` through `evennia-logging-extension`, which owns the
   mechanism and puts every line in the library's own `ai_memory.log` under the running instance's
   `LOG_DIR`, so an operator debugging a dropped memory reads one file instead of the whole server log.

   The line to hold is principle 1's, not an import list: rooms, mobs, typeclasses, factions and one
   game's vocabulary belong to the consumer. That is a judgement made case by case, and no static check
   substitutes for it.

   One functional exception, and it is not about boundaries: the standalone validator must start
   without an engine, because a pre-commit hook or a CI job has no gamedir. XC-13 covers it.

## Out of scope

Scope boundaries are decided as concrete questions arise, by applying the principles above. These
rulings are settled:

- **A why-comment on every Evennia import** — this library answers that question once, at the library
  level, rather than per import site. See principle 8: Evennia is the platform, the line to hold is
  principle 1's, and `XC-01` was retired for asserting a boundary that was never the boundary. The
  `library-standards-linter`'s `evennia_import_unexplained` findings are that decision; the four sites
  are `Command` and `AccountCmdSet`.
- **An accessor for the `DATABASES` read in `services.py`** — not needed, and the linter's
  `settings_read_outside_config` finding is this decision. `_is_postgres()` reads
  `settings.DATABASES[AI_MEMORY_ALIAS]["ENGINE"]` to pick the pgvector or numpy path. `DATABASES` is
  Django's own and always defined, so the rule's stated failure — `AttributeError` for a consumer who
  declared nothing — cannot happen. `EM-12` pins the line the library actually holds: no
  `settings.AI_MEMORY*` read outside `config.py`.
- **Moving `EMBEDDING_DIMENSIONS` into `config.py`** — it cannot go there, and the
  `library-standards-linter`'s one `constant_outside_config` finding is this decision rather than a
  gap. It is not a declared value but the result of asking Django for one, and `config.py` is imported
  via `db_spec.py` from inside the consumer's settings module, where settings are still unconfigured —
  a module-scope read there raises `ImproperlyConfigured` and the game never starts. The declared
  constant it derives from, `DEFAULT_DIMENSIONS`, is in `config.py` as the rule requires. Full
  reasoning is at the declaration in [models.py](src/evennia_ai_memory/models.py).
- **Database resolution and routing** — `evennia-database-cascade`'s. This library declares its alias
  in [db_spec.py](src/evennia_ai_memory/db_spec.py) and ships no router, no `DATABASES` snippet and no
  resolution code. Do not write any of them back; see
  [docs/interoperability.md](docs/interoperability.md) § evennia-database-cascade.
- **Rate limiting and cost tracking** — the consumer's, handled at the API provider. See principle 3.
- **Combat memory** — out of scope. The substrate carries a `CombatMemory` model and migrations, but
  nothing calls them and no store or search service was ever written. The schema will change once there
  is a strategy bot to serve, so extracting it now would be extracting a guess. It is a body of work in
  its own right, to be started deliberately rather than carried as a question.
- **Chat completions** — `evennia-llm-service`'s.
- **Phrasing an interaction** — the consumer writes the summary and the library embeds it. Only the
  consuming game knows how its own interactions read, which is why `interaction_type` is unvalidated
  too. See principle 5 and D6 in the test plan.
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

- `[TBD — needs discussion: whether the embedding dimension stays fixed at 1536 or becomes a
  library-level setting. Configurable dimensions mean the migration reads the setting, the numpy path
  needs a length guard, and changing it on a live install requires re-embedding everything, since
  vectors from two models are not comparable.]`
- `[TBD — needs discussion: whether an Evennia integration mixin ships as `contrib/`. The lore commands
  are core, because administering the library's own table is infrastructure. A mixin that gives a
  consumer's NPC typeclass its memory hooks is the other kind of thing — the common case many but not
  all consumers would want — which is what `contrib/` is for. No `contrib/` exists today, per the
  standards' rule against scaffolding one empty.]`

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
├── runtests.py                # standalone test runner; no gamedir required
├── .gitignore
├── docs/                      # technical wiki (humans + LLMs)
│   ├── INDEX.md
│   ├── installing.md          # the consumer's eight steps, and every setting
│   ├── progress.md
│   ├── test-plan.md           # where a behavioural change starts
│   ├── interoperability.md
│   └── archive/               # historical context (currently empty)
├── src/
│   └── evennia_ai_memory/     # library code (src layout)
│       ├── __init__.py
│       ├── apps.py            # AppConfig; ready() validates the settings
│       ├── config.py          # settings accessors, check_settings(), and every
│       │                      # constant but EMBEDDING_DIMENSIONS — see below
│       ├── db_spec.py         # the AliasSpec declared to evennia-database-cascade
│       ├── log.py             # binds ai_memory_log → ai_memory.log
│       ├── models.py          # NpcMemory, LoreMemory
│       ├── services.py        # the public functions
│       ├── lore_import.py     # the import pipeline: discover, validate, plan, apply
│       ├── commands.py        # CmdLoreImport, CmdLoreWipe
│       ├── cli.py             # standalone validator, for pre-commit and CI
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
- Runtime dependencies: `django`, `evennia` (the lore commands), `evennia-database-cascade` (places
  the alias and derives the router from `db_spec`), `evennia-logging-extension` (owns the logging
  mechanism `log.py` binds to), `evennia-targeting` (reads a confirmation answer), `evennia-yaml-reader` (reads the lore repository), `numpy`, `openai`
  (the embeddings client; the SDK speaks to any OpenAI-compatible endpoint, so the provider is a
  config value), `pgvector`, `psycopg`.
- The sibling libraries are unpublished, so a dev venv installs them from their checkouts:
  `pip install -e ../evennia-database-cascade -e ../evennia-logging-extension -e ../evennia-targeting`
  `-e ../evennia-yaml-reader`.
- **Tests use Django's test runner** via `runtests.py`, which bootstraps Django then calls
  `evennia._init()`, as the siblings do. No gamedir required.
- Dedicated venv at `evennia-ai-memory/venv/` (gitignored). Development install via `pip install -e .`.

## Sibling libraries to reference

When in doubt about a convention not covered here, look at how a sibling library does it:

- **[../evennia-shards/](../evennia-shards/)** — full Evennia-bootstrapped library with Django test
  settings and its own migrations. Reference for the Django app shape and the test-runner pattern.
- **[../evennia-yaml-reader/](../evennia-yaml-reader/)** — how to document a deliberate divergence from
  the library standards in `CLAUDE.md`.
- **[../evennia-archive/](../evennia-archive/)** — the other library that owns tables on an alias of
  its own. Reference for the `db_spec.py` shape and for wiring `configure()` into test settings.
- **[../evennia-llm-service/](../evennia-llm-service/)** — imports this library; owns chat completions
  and the prompt-template mechanism.
