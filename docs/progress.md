# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-08-31 (latest)

- **Stage 2 agreed: the lore commands.** Two superuser commands, cases written and no code yet — see
  the `IM` and `WP` blocks in [test-plan.md](test-plan.md).

  `lore import` reads the content repo through a settings-resolved reader (the
  `evennia-world-builder` convention — GitHub in production, a local checkout in development), validates
  all of it, and brings the table into line. **The YAML is the source of truth**, so an entry deleted
  from the YAML is deleted from the database. It runs in two phases with the report between them, which
  also gives a dry run for nothing.

  `lore wipe` is separate so that emptying the table has to be named rather than arrived at. An import
  that resolves zero entries refuses and points at it.

  Two things this settles. The library ships commands, so it gains real Evennia coupling —
  `Command`, and a cmdset patch at `ready()`. That was blocked only by a line in this file ruling
  Evennia surface out of scope, which was never discussed; the standards say a library may ship
  game-shaped things, and administering its own table is infrastructure rather than a game concept. And
  `evennia-yaml-reader` becomes a hard dependency once the importer lands, which
  [interoperability.md](interoperability.md) already anticipates.

  The standalone importer and its Railway service retire — the game no longer deploys on Railway. That
  makes the library the sole writer to the lore table, and removes the raw SQL that had to be kept in
  step with the model by hand.

- **Stage 1 is implemented and the suite is green on SQLite.** The five functions, the embeddings
  client, the retry split and the lore filter all pass their cases. The PostgreSQL cases remain
  uncovered, as agreed — SQLite first, PostgreSQL once it is proven.

- **Retry classification.** `_embed_once` raises `PermanentEmbeddingError` for the provider errors a
  retry cannot clear — rejected key, forbidden, malformed request, unknown model — and `_embed` retries
  everything else. An unclassified fault is more often a transport hiccup than a permanent one, and the
  cost of being wrong is a couple of seconds, so the default is to retry.

- **The lore filter could not be one expression.** `contained_by` is the subset rule exactly, but Django
  does not support it on SQLite. So the filter is exact on PostgreSQL and permissive on SQLite, with
  `_can_access_lore` applied in Python there — before scoring, so an inadmissible row can never displace
  an admissible one. D1 holds on both: filtering precedes ranking either way.

  SC-12 changed with it. It asserted the SQL filter and the Python rule agree, which cannot hold where
  the filter is deliberately permissive. It now asserts the property that actually matters and is true
  on both backends: the filter may admit rows the rule rejects, and may never exclude one it would
  admit.

## 2026-08-30

- **The baseline is the existing system.** The library is the game's `src/game/ai_memory/` service
  module lifted out — the same tables, the same function signatures, the same behaviour. Success is a
  consumer deleting the coupled game code, installing the library, renaming a few call sites, and
  everything running as before. Whether more moves into the library afterwards is a separate question,
  taken case by case. Recorded as *The starting point* in [../CLAUDE.md](../CLAUDE.md).

  The departures agreed are listed, each with its cases, under *Departures* in
  [test-plan.md](test-plan.md): lore filtering happens before ranking on both backends; a read that
  cannot embed returns `None` and does not retry, rather than silently substituting a recency query;
  rows are keyed by UUID rather than a dbref-then-name fallback, with both UUIDs required on every
  memory read; a write retries a transient failure then logs and drops it, and never writes a row with
  no vector; and the summary is written in the second person, which leaves the NPC's name with no reader
  so it goes from the signature and the model.

  Retries belong to writes, which are dispatched off the reactor with nothing waiting on them. A read
  has a player waiting, so it fails fast and the consumer decides what the NPC does about it.

  `get_last_interaction_time` keeps returning its relative-time phrase alongside the timestamp. It
  exists so an NPC can greet a returning player differently from a stranger, or from someone who was
  standing there a minute ago; the phrasing is tuned for that rather than for display, and the caller
  uses only the phrase and whether there was any history at all.

  No case in the plan is blocked on a decision.

- **The database resolves through a helper the consumer calls in settings**, following
  `evennia-message-bus`: `DATABASE_URL_AI_MEMORY`, then `DATABASE_URL`, then a SQLite file, with
  `describe_ai_memory_database()` naming the result in the startup log rather than the library guessing
  or warning. Consistency with the sibling was chosen over dropping the middle rung, which puts
  memories in the game's database where a rebuild destroys them. Covered by the `DB` cases.

  Backend selection still reads the resolved `ENGINE` rather than the environment variables: a
  `DATABASE_URL` naming MySQL would otherwise select the pgvector path.

- **The library owns the embeddings client.** It calls the endpoint itself rather than taking an
  injected callable. Configuration comes from Django settings through accessors in a `config` module,
  never by reading `settings` directly — the pattern `evennia-shards` uses. Endpoint, key and model are
  all required and the library ships no defaults for any of them: a default base URL or model name
  would choose a provider on the consumer's behalf and bury that choice in library code. Absent any of
  the three the app refuses to start, naming the setting and where to put it. Installation instructions
  in [../README.md](../README.md) cover it.

  This adds `openai` as a runtime dependency. The SDK speaks to any OpenAI-compatible embeddings
  endpoint, so the provider is a configuration value rather than a code change.

- **Backends: SQLite first, PostgreSQL once it is proven**, following the substrate's `_is_postgres()`
  branching. The pgvector cases stay in the plan with empty cells until then.

- **Stage 1's surface** is `store_memory`, `search_memories`, `get_recent_memories`,
  `get_last_interaction_time` and `search_lore` — listed with their signatures under *Stage 1 surface*
  in [test-plan.md](test-plan.md).

  `store_lore` is out of scope — nothing in the game calls it, and lore is written only by the
  standalone importer in the lore content repo, which talks to the table directly and stays where it is.
  The `LoreMemory` model and its migrations still ship, because something has to create the table the
  importer writes to. Moving the importer in, with the validator that gates an import and the
  `evennia-yaml-reader` dependency that follows, is stage 2.

  `get_recent_lore` is dropped. Its only job was being the fallback that D2 removes, and "most recently
  updated lore" does not answer "what does this NPC know about the great war" — lore is not time-ordered
  the way an interaction history is.

- **Scope set: lore and interaction memory.** The library takes the two memory systems in FCM's
  `src/game/ai_memory/` that have working services — lore and interaction memory — together with their
  dual storage backend (pgvector on PostgreSQL, numpy on SQLite), their models, migrations and database
  router.

  **Combat memory is out of scope.** A `CombatMemory` model and its migrations exist in the substrate,
  but nothing calls them and no store or search service was ever written. The schema will change once
  there is a strategy bot to serve, so extracting it now would be extracting a guess. Whether it later
  lands here or in a library of its own is open.

- **No rate limiting and no cost tracking.** A consumer caps spend where the provider already offers
  it — an API key carrying a budget — and reads usage from the provider's own dashboard. Rebuilding
  either here duplicates a control the consumer already has, less well, and it is not a thing a MUD
  needs to own.

- **Retrieval returns data, never prompt text.** Prompts must be consumer-definable, so prompt
  assembly, template selection and formatting stay outside the library. The substrate already works
  this way — `search_lore()` returns dicts, and all formatting happens in the consumer's Evennia mixin.

- **Direction: `evennia-llm-service` imports this library as a hard dependency.** The retrieve → build
  → call → store flow is one unit of work, and splitting it across a library boundary means the
  consuming game reassembles it at every call site. A hard dependency lets that orchestration, and the
  threading and transaction handling around it, live in one place.

  Two consequences were raised and are not yet resolved:

  `[TBD — needs discussion: the install burden. Depending on this library means depending on its
  models, migrations, router and second database alias, so a consumer wanting stateless LLM NPCs must
  still configure an `ai_memory` alias and migrate it.]`

  `[TBD — needs discussion: whether `evennia-llm-service` owns the `deferToThread` dispatch. If it
  does, it becomes the dispatch site where `evennia-shards` requires `preserve_tenant_context`, and it
  must close Django connections on the worker thread. This library's own contract — every function
  synchronous, the consumer dispatches — is unaffected either way.]`

- **Repository bootstrapped.** Library-standards scaffold in place: `pyproject.toml`, `runtests.py`,
  `src/evennia_ai_memory/__init__.py` (version 0.0.1), smoke tests, `tests/` infrastructure with plain
  Django settings, `CLAUDE.md`, `README.md`, `docs/INDEX.md`, `docs/progress.md`,
  `docs/interoperability.md`, `docs/test-plan.md`, `docs/archive/`. No library code yet.

  Two deliberate divergences from the library standards, both captured in CLAUDE.md principle 6: the
  library depends on **Django but not Evennia**, so `runtests.py` bootstraps Django alone and
  `tests/test_settings.py` is plain Django rather than an `evennia.settings_default` import; and there
  is no `examples/` directory, because a library with no Evennia surface has nothing to exercise in a
  demo gamedir.

- **Test plan written ahead of any code**, covering the substrate's behaviour case by case. Seven
  behavioural questions are unresolved and blocking, collected under *Open decisions* in
  [test-plan.md](test-plan.md).
