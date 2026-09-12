# Interoperability

This library against every sibling library in `libraries/`.

**No library code exists yet, and these sections have not been reviewed with the project owner.** They
state what the current design implies, not what the code does. Each is provisional: re-confirm against
an implementation rather than inheriting it.

What this library will do that can constrain a sibling: register a **Django app with its own models and
migrations**, route those models to a **second database alias** via its own router, and issue ORM reads
and writes against that alias. It calls an embeddings endpoint over the network, configured from
settings it owns. It touches no `ObjectDB` row and dispatches nothing off the calling thread — every
function is synchronous and the consumer owns the dispatch.

## evennia-ai-memory

This library.

## evennia-archive

**No coupling, with one shared consideration.** Neither library imports the other. Both, however,
install a database router and write to an alias of their own, so both routers sit in the consumer's
`DATABASE_ROUTERS` list at once.

Django consults routers in order and takes the first non-`None` answer, so each router must return
`None` for every app it does not own. A router that answers for foreign models — by returning its own
alias as a catch-all, or by answering `allow_relation` unconditionally — silently captures the other
library's queries and sends them to the wrong database. The requirement is symmetric and belongs to
whichever router is written to breach it; this library's router will answer only for
`evennia_ai_memory` models.

`[TBD — confirm once both routers exist: whether the two impose any ordering requirement on
DATABASE_ROUTERS, or whether "answer only for your own app" is sufficient on its own.]`

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

`[TBD — needs section: this entry has not been written. See
libraries/evennia-message-bus/docs/interoperability.md for what that library expects.]`

## evennia-mob-spawner

**No coupling.** Neither library imports the other, and nothing this library stores refers to a spawned
object. It resolves no identifier back to a game object, so it holds no reference a despawn could
invalidate.

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

## evennia-targeting

**No coupling.** Neither library imports the other. Targeting filters candidate lists already in hand
and issues no query against this library's alias; this library resolves no game objects.

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
