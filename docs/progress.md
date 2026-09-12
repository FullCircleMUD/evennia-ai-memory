# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-12 — the constants gather in config.py, and three divergences get decided (latest)

- **Seven constants moved to `config.py`**, names and reasoning intact: `MANIFEST`, `CONSENT`,
  `INITIATOR_PC`, `INITIATOR_NPC`, `INITIATORS`, `WRITE_ATTEMPTS`, `WRITE_RETRY_DELAY`. Each module
  imports what it uses from there, so `lore_import.MANIFEST` and `services.WRITE_RETRY_DELAY` still
  resolve and the suite needed no change — a module-scope import binds the name as a module
  attribute, which is what every test reference goes through.

- **`validate_settings()` is `check_settings()`**, the name the standard gives the boot validator so
  it is found under one name in every library. One declaration, one call in `apps.py`, six in the
  suite; no behaviour change.

- **`EMBEDDING_DIMENSIONS` stays in `models.py`, and that is now a decision rather than a gap.** It is
  not a declared value but the result of asking Django for one, and a cold call raises
  `ImproperlyConfigured` — tested, not assumed. `config.py` is imported via `db_spec.py` from inside
  the consumer's settings module, where settings are still unconfigured, so a module-scope read there
  would stop the game from starting. The declared constant it derives from, `DEFAULT_DIMENSIONS`, is
  in `config.py` as the rule requires. Reasoning is at the declaration; the divergence is recorded
  under *Out of scope*.

- **Two more findings recorded as decisions.** Every Evennia import having a why-comment: answered at
  the library level by principle 8 and `XC-01`'s retirement rather than per site. An accessor for
  `_is_postgres()`'s `DATABASES` read: not needed, because `DATABASES` is Django's own and always
  defined, so the `AttributeError` the rule guards against cannot happen — and `EM-12` pins the line
  the library actually holds.

  All three remaining linter warns are therefore adjudicated. A future session should read them as
  settled and not "fix" them back.

## 2026-09-12 — the docs catch up with the two migrations

- **`docs/installing.md` exists**, which is the document the standards require and this library never
  had. The eight setup steps moved out of `README.md` into it, updated for the cascade, and it now
  also carries what README never collected: the required settings with what happens without each, the
  optional ones with why each default is what it is, what is not checked for you, and the
  troubleshooting table. README keeps a short orientation snippet and links to it, so there is one
  copy of the steps rather than two that drift.

- **What the migrations invalidated is gone.** README told a consumer to write a `DATABASES` entry and
  append `AiMemoryRouter` — a function and a module that no longer exist — and warned about a
  `DATABASE_ROUTERS` `NameError` that can no longer happen. `CLAUDE.md`'s principle 6 and its layout
  tree described the router. `interoperability.md` opened by saying no library code existed yet, and
  its `evennia-archive` section documented a two-hand-rolled-router constraint that both libraries
  have since handed to the cascade.

- **`interoperability.md` covers every sibling.** Nine sections were missing and one was a bare
  `[TBD]`. Each now names a relationship and gives its considerations or an explicit clearance in
  terms of what this library actually does.

- **Two principles the standards ask for.** `CLAUDE.md` gained *Test-first* as a numbered principle,
  and `docs/test-plan.md` is now second in the reading order, marked as where a behavioural change
  starts. A ruling under *Out of scope* says resolution and routing are the cascade's and must not be
  written back.

## 2026-09-12 — resolution and routing move to evennia-database-cascade

- **`db_spec.py` declares the alias and the cascade does the rest.** It derives the `DATABASES` entry,
  the router and the migration list from that one declaration, so routing and migration cannot
  disagree. `db_router.py` is gone, along with `config.py`'s `ai_memory_database()` and
  `describe_ai_memory_database()` and the `dj-database-url` dependency. The alias constant moved to
  `config.py` as `AI_MEMORY_ALIAS`, where the constants rule wants it, and the eight call sites read
  it from there.

- **The shared rung stays available, and that is a decision.** Nothing here shares a table name with
  the framework, so a single-instance game can point the alias at its own database and get a second
  set of tables rather than Evennia's. It loses the memories on a rebuild, which is its call to make.
  `vector` is declared required, so the cascade refuses a migrate against a database without it and
  names the `CREATE EXTENSION` to run.

- **`RT` and `DB` retire, whole blocks.** The router is the cascade's and tested there; DS-01 pins the
  app label and alias on the spec and DS-06 pins that no router class is declared here. DB-05 to
  DB-09 went with the startup line naming the resolved database, because the cascade logs
  `configured aliases: …` itself.

- **Verified live on the demo gamedir.** `cascade_migrate` migrated the game database and then the
  alias; in game, `LoreMemory.objects.db` and `NpcMemory.objects.db` both returned `ai_memory` with no
  `.using()`; and counted straight out of the files, `server/ai_memory.db3` held 73 lore rows and 2
  memory rows while `evennia.db3` held no `ai_memory` tables at all. A full lore import from
  `FullCircleMUD/lore@main` created 73 entries, and `search_lore` ranked *The Town Watch's Position on
  Bobbin Goode* (0.612) above *Millholm Economy* (0.592) for "who rules the town of Millholm?".

## 2026-09-12 — logging moves to evennia-logging-extension

- **`log.py` is the standard three-line binding.** `ai_memory_log = make_logger("ai_memory.log")`, and
  the mechanism — level coercion, `trace`, never raising into the caller — is the extension's. The
  bound name does not change, so all fifteen call sites keep the text, level and `trace` flag they
  had. No new logging.

  Lines the old shim could not land now do. It was a silent no-op wherever Evennia was not
  bootstrapped; the extension writes synchronously where no reactor is running, so `ready()`, a
  management command and a consumer's settings module all reach disk. Verified by reading
  `ai_memory.log` back, not by mocking the shim.

  Both paths are proven on the demo gamedir. Without a reactor, a line written during
  `django.setup()`. With one, `ai_memory_log` called in game with `reactor.running` true, landing as
  `[WARN] LIVE reactor-path check` in `ai_memory.log`.

  LG-01 becomes the binding case. LG-04 and LG-05 retire — level coercion and the off-engine no-op
  were the mechanism's behaviour, and LG-05's premise no longer holds. 200 tests pass.

  `config.py` imports the shim lazily, inside `_required()`, as the standard requires unconditionally.

## 2026-08-31 — a memory becomes an event

- **`NpcMemory` redesigned.** The substrate stored a conversation: a player's line, an NPC's reply, and
  a summary the library built from them. That shape only fits speech, and an NPC should also remember
  that this character bought from it, stole from it, taunted it, fled from it.

  A row is now an event. `store_memory(npc_uuid, pc_uuid, pc_name, summary, interaction_type, initiator)`
  — the consumer writes the summary, the library embeds it. The message columns go, since a supplied
  summary already holds whatever wording matters and an attack never had two messages to put in them.
  `initiator` is `"pc"` or `"npc"` and is refused otherwise; `interaction_type` is any non-empty string,
  because that vocabulary is the game's and grows.

  The library phrases nothing, for the same reason it validates no interaction vocabulary: only the
  consuming game knows that `taunt` reads as "Bob taunted you". Recorded as D6, which supersedes D5.

  This is the first change that is a redesign rather than an extraction, and it is what extraction
  bought — the shape was hard to question while it was one mixin among forty.

  The migration was regenerated rather than added to. The library has exactly one install, a demo
  gamedir with a disposable database, so carrying a second migration to correct a schema nobody ran
  would be recording history for its own sake.

## 2026-08-31 — stage 2 implemented

- **The lore commands work and the suite is green.** `store_lore`, the import pipeline, both commands
  and the standalone validator all pass their cases on SQLite; the PostgreSQL cases still wait on a
  Postgres test database.

- **Three test bugs surfaced while implementing, and two were the kind that hide real problems.**

  `XC-13` matched the text `from evennia` and so read `evennia_yaml_reader` as Evennia. A sibling
  library is not the framework, and the check now reads module names from the AST rather than matching
  substrings — as `XC-14` already had to, after its own false positive on a docstring that named
  `deferToThread` while explaining the rule against it.

  `LG-09` forbade writing to stdout anywhere. That is right inside the engine and wrong for `cli.py`,
  which is a command-line tool whose report to the operator *is* stdout. Exempted, with the reason.

  `IM-27` looked for the dispatch inside the command class, but both phases share a module-level helper
  that closes the worker's database connections in a `finally`. It now asserts the module reaches
  `run_async` and that the command uses the helper twice — once per phase.

## 2026-08-31

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

  `[TBD — once the commands exist: an `examples/` gamedir becomes worth having. The scaffold went
  without one because there was no Evennia surface to exercise; a command is exactly the thing a demo
  gamedir is for.]`

- **XC-01 retired.** It asserted that the library imports no Evennia, which was never the boundary that
  mattered. Evennia is the platform — using a `Command`, a cmdset or the logger costs nothing and
  defends nothing. What the library must not own is what the *consumer* defines: rooms, mobs,
  typeclasses, one game's vocabulary. That is principle 1, it is a judgement made case by case, and no
  import check substitutes for it. XC-13 stays for a different and purely functional reason — the
  standalone validator has to start without an engine.

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
