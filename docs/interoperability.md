# Interoperability

This library against every sibling library in `libraries/`.

What this library does that can constrain a sibling: register a **Django app with its own models and
migrations**, declare an alias to `evennia-database-cascade` and issue ORM reads and writes against
it, and install two superuser commands into `AccountCmdSet`. It calls an embeddings endpoint over the
network, configured from settings it owns, and writes its own log file. It touches no `ObjectDB` row,
stores no state on Evennia objects, and dispatches nothing off the calling thread except in the two
commands — every public function is synchronous and the consumer owns the dispatch.

## evennia-ai-memory

This library.

## evennia-archive

**No coupling.** Neither library imports the other. Both own tables on an alias of their own, and both
declare that alias to `evennia-database-cascade` rather than shipping a router, so the routers are
derived from the two specs by one mechanism and cannot conflict with each other.

One difference worth knowing if you run both: the archive's tables share Evennia's own table names, so
its spec refuses the shared rung. This library's do not, so its spec allows it. A deployment can
therefore put the memories in the game's database while the archive keeps its own — the cascade
resolves each alias against its own spec.

## evennia-calendar

**No coupling.** Neither library imports the other. Nothing this library stores is time-addressed
beyond its own `created_at` and `updated_at`, which are Django timestamps rather than game time, so a
calendar's notion of dates never reaches a query here.

## evennia-database-cascade

**Hard dependency.** This library declares its alias in `db_spec.py` and the cascade derives the
`DATABASES` entry, the router and the migration list from it. Nothing here writes a router, a
`DATABASES` snippet or any resolution code of its own, and `db_spec` imports nothing from Django
because it sits on the consumer's settings path.

The constraint on a consumer is the cascade's own and documented there: the one `configure()` call, the
`DATABASE_URL_<ALIAS>` convention, and `evennia cascade_migrate`. See the cascade's
[installing.md](../../evennia-database-cascade/docs/installing.md). What travels on this library's
spec is its own concern: `required_extensions=("vector",)`, because the embedding columns are
pgvector's, and both `allow_` flags left at their defaults.

## evennia-equipment

**No coupling.** Neither library imports the other, and nothing this library stores refers to an item.
It resolves no identifier back to a game object, so no equipment change can invalidate a row here.

## evennia-llm-service

**Hard dependency, in the other direction.** `evennia-llm-service` imports this library and is the only
side that knows about the relationship; this library imports nothing of its and does not know it exists.
It owns chat completions, the prompt-template mechanism, and the orchestration around a call —
retrieve, build, call, store.

`[TBD — needs discussion: whether `evennia-llm-service` owns the `deferToThread` dispatch. If it does,
it becomes the dispatch site carrying the `evennia-shards` requirement below, and it must close Django
connections on the worker thread. This library's own contract is unaffected either way — every function
here is synchronous.]`

The two configure their providers independently — this library owns its embeddings endpoint, key and
model; `evennia-llm-service` owns its chat equivalents. A consumer may point both at the same provider
and use the same key, or not; that is its choice and neither library needs to know.

## evennia-logging-extension

**Hard dependency.** `log.py` imports it unconditionally and binds `ai_memory_log` through
`make_logger`, so every line this library emits goes through the extension to `ai_memory.log` under
`settings.LOG_DIR`. Nothing else here touches it, and the library declares no logging settings of its
own — the filename is hardcoded.

The one constraint on a consumer is the extension's own and is documented there: where `LOG_DIR` is
resolved, and what it means for where a library import sits in a settings module. See
[evennia-logging-extension's installing.md](../../evennia-logging-extension/docs/installing.md).

## evennia-message-bus

**No coupling.** Neither library imports the other. The bus carries messages between instances; this
library answers questions about rows it holds and publishes nothing.

Worth knowing where both are installed: the bus exists to serve multi-instance deployments, and a
memory row is reachable from every instance that can see the alias. So two instances sharing one
memories database already see each other's writes without the bus being involved, and nothing here
needs an announcement when a row lands.

## evennia-mob-spawner

**No coupling.** Neither library imports the other, and nothing this library stores refers to a spawned
object. It resolves no identifier back to a game object, so it holds no reference a despawn could
invalidate.

## evennia-portal-multiplex

**No coupling.** Neither library imports the other. Multiplexing happens at the Portal, between
players and instances; every function here runs in the Server against its own alias and has no view of
which instance a session arrived through.

## evennia-scaling

**No coupling.** Neither library imports the other, and nothing here is scoped to an instance. Rows
are keyed by the UUIDs a consumer supplies, which are stable across instances by design, so a
character moving between instances keeps its memories provided both can see the alias — a deployment
question the cascade answers, not this library.

## evennia-shards

**No coupling.** Neither library imports the other, and neither of shards' recurring constraints
reaches this one.

Tenancy is installed on `ObjectDB` and nothing else. This library's models are its own, on a separate
database alias, so there is no `shard_id` column to scope and no auto-stamp to lose — a query here is
unaffected by whether a shard context is set.

The off-thread constraint likewise lands elsewhere. Every function in this library is synchronous by
contract; the consumer wraps the call in `deferToThread` or equivalent. Because
`preserve_tenant_context` must be applied **at the dispatch site**, and the dispatch site is the
consumer's, the requirement belongs to the consumer's integration layer rather than to this library.
That wrap is still needed whenever the same worker also touches `ObjectDB`.

## evennia-survival

**No coupling.** Neither library imports the other. Survival state lives on the consumer's typeclasses
as attributes; this library stores rows keyed by UUID and reads no object state, so a hunger stage is
invisible to it. A consumer that wants an NPC to remember being fed writes that summary itself.

## evennia-targeting

**Hard dependency.** The lore wipe reads its confirmation answer with `parse_yes`, so every library
reads an answer the same way. Targeting imports nothing from this library and issues no query against
its alias; this library resolves no game objects.

## evennia-world-builder

**No coupling.** Neither library imports the other.

Worth knowing: lore entries are filtered by scope tags, and in a consuming game those tags often
correspond to room tags that world-builder sets from YAML. The correspondence is the consumer's to
maintain — this library receives a plain `list[str]` and has no knowledge of where the strings came
from, so a change to world-builder's tagging cannot break it directly. It can, however, silently narrow
what an NPC retrieves, which is a consumer-side integration concern rather than a library constraint.

## evennia-yaml-reader

**Hard dependency.** This library imports yaml-reader unconditionally: the lore import command reads a
content repository through it, and the standalone validator uses `LocalReader` directly. Which reader
is used at runtime is a consumer setting — `AI_MEMORY_READER` and `AI_MEMORY_READER_KWARGS`, the same
dispatch convention `evennia-world-builder` and `evennia-mob-spawner` use.

This library imposes nothing on yaml-reader beyond its API contract. It depends on the typed errors
being distinguishable: an auth failure and a missing path are reported differently to the operator,
because one is a rejected token and the other a wrong repository or ref.

## fcm-telemetry-spawn

**No coupling.** Neither library imports the other. Both are consumers of the same deployment rather
than of each other: telemetry drives what spawns, and nothing about a spawn decision reaches a memory
row. A game wanting an NPC to remember a spawn event writes that summary itself.

## fcm-xrpl

**No coupling.** Neither library imports the other. The ledger holds ownership; this library holds what
an NPC remembers. A consumer whose NPC should recall a trade writes the summary of it — this library
never reads a wallet, a balance or a token, and an `fcm-*` library's FCM concepts are exactly what
principle 2 keeps out of here.
