# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it.

**The baseline is the existing system.** The library is FCM's `src/game/ai_memory/` service module lifted
out: the same tables, the same function signatures, the same behaviour on the same rows. A consumer
should be able to delete the coupled game code, install the library, rename a few call sites, and have
everything run as before. Every case below therefore describes what the game does today — except the
ones listed under *Departures*, each of which traces to a specific discussion. A case that encodes a
change with no entry there is a defect in this plan.

## Stage 1 surface

Five functions. `store_lore` and `get_recent_lore` are out of scope — see *Retired*.

```
store_memory(npc_uuid, speaker_uuid, speaker_name, user_msg, assistant_msg, interaction_type="say")
search_memories(npc_uuid, speaker_uuid, query_text, top_k=5)
get_recent_memories(npc_uuid, speaker_uuid, limit=10)
get_last_interaction_time(npc_uuid, speaker_uuid)
search_lore(query_text, scope_tags, top_k=3)
```

| Prefix | Covers |
|---|---|
| `EM` | Embedding |
| `SM` | `store_memory` |
| `MS` | `search_memories` |
| `MR` | `get_recent_memories` |
| `LI` | `get_last_interaction_time` |
| `LS` | `search_lore` |
| `SC` | Scope access rules |
| `BE` | Backend dispatch and dual-backend equivalence |
| `RT` | Database router |
| `LG` | Logging |
| `XC` | Cross-cutting |

`CM`, `SL` and `LR` are reserved. They covered combat memory, `store_lore` and `get_recent_lore` — all
out of scope for stage 1, see *Retired*. Do not reuse those prefixes for anything else.

## Fixtures

The suite needs Django and a database, but no Evennia: the library takes identifiers and strings from
the caller and never resolves a game object.

| Fixture | Purpose |
|---|---|
| `StubEmbedder` | Deterministic `text -> list[float]`; same text always gives the same vector |
| `OrthogonalEmbedder` | Maps a small vocabulary to mutually orthogonal unit vectors, so similarity ordering is exactly predictable |
| `RaisingEmbedder` | Raises on call |
| `FlakyEmbedder` | Fails a set number of times then succeeds, for retry cases |
| `ShortEmbedder` | Returns a vector of the wrong dimension |
| `CountingEmbedder` | Records every call, for "was it called / how many times" cases |
| `make_memory(**kwargs)` | Builds an `NpcMemory` row directly, bypassing `store_memory` |
| `make_lore(**kwargs)` | Builds a `LoreMemory` row directly |
| `aged(row, delta)` | Forces `created_at` / `updated_at` to a chosen age past `auto_now_add` |

**Backend coverage.** The `_search_*_numpy` paths run on the suite's SQLite database. The
`_search_*_pgvector` paths cannot: `CosineDistance` compiles to a pgvector operator SQLite has no
answer for. Cases tagged **[pg]** require a PostgreSQL test database.

SQLite is proven first, following the substrate's `_is_postgres()` branching. PostgreSQL comes after,
and until it does the **[pg]** cases sit in the plan with empty cells — agreed, not yet covered.

## EM — embedding

The library owns the embeddings client and calls the provider itself. Configuration comes from Django
settings, read through accessors in the library's `config` module rather than by touching `settings`
directly — the pattern `evennia-shards` uses.

**The library ships no provider defaults.** Endpoint, key and model are all required settings. A
default base URL or model name would choose a provider on the consumer's behalf and bury that choice in
library code; both are provider-specific strings and neither is the library's to pick. Absent any of
the three, the app refuses to start.

`[TBD — naming: proposed `AI_MEMORY_EMBEDDING_API_KEY`, `AI_MEMORY_EMBEDDING_BASE_URL`,
`AI_MEMORY_EMBEDDING_MODEL`, following the sibling convention of prefixing by library. The game's
existing `LLM_EMBEDDING_*` names belong to its LLM layer, not here.]`

| ID | Case | Test function |
|---|---|---|
| EM-01 | The text embedded is exactly the text the library documents as the embedding source | |
| EM-02 | On a write, a transient failure is retried, then logged and dropped (**D4**) | |
| EM-03 | On a write, a permanent failure is dropped without retrying (**D4**) | |
| EM-04 | A missing API key raises `ImproperlyConfigured` at startup, not at the first call | |
| EM-05 | The error names the setting and where to put it, rather than reporting a generic failure | |
| EM-06 | Embedding happens once per stored row, not once per field | |
| EM-07 | A wrong-length vector is refused at the boundary rather than stored | |
| EM-08 | The library holds no rate limiter and no cost tracking — asserted statically over the source tree | |
| EM-09 | On a read, a failure is not retried — one attempt, then report (**D2**) | |
| EM-10 | A missing base URL raises `ImproperlyConfigured` at startup | |
| EM-11 | A missing embedding model raises `ImproperlyConfigured` at startup | |
| EM-12 | Configuration is read only through the `config` accessors — no direct `settings` reads in library code, asserted statically | |
| EM-13 | A required setting present but empty is treated as missing, for all three | |
| EM-14 | The configured base URL is the one the client is built with, so the provider is swappable | |
| EM-15 | The library reads its own settings namespace and never the consumer's `LLM_*` names | |
| EM-16 | No endpoint URL and no model name appear anywhere in library code — asserted statically | |

## SM — `store_memory`

| ID | Case | Test function |
|---|---|---|
| SM-01 | A stored exchange is retrievable by `get_recent_memories` | |
| SM-02 | The row records both UUIDs, the speaker name, both messages and the interaction type | |
| SM-03 | The summary names the speaker but refers to the NPC in the second person, never by name (**D5**) | |
| SM-04 | On SQLite the vector is stored as a float32 byte blob | |
| SM-05 | **[pg]** On PostgreSQL the vector is stored in `embedding_vector`, and `embedding` stays null | |
| SM-06 | The blob round-trips — what comes back out equals what went in, to float32 precision | |
| SM-07 | An embedding failure logs and returns without raising into the caller (**D4**) | |
| SM-08 | A transient write failure is retried, then logged and dropped (**D4**) | |
| SM-09 | A row is never written without a vector (**D4**) | |
| SM-10 | Empty `user_msg` or `assistant_msg` still stores | |
| SM-11 | Two identical exchanges both store — no deduplication | |
| SM-12 | `created_at` is set automatically and is timezone-aware | |
| SM-13 | The row lands on the `ai_memory` alias, not `default` | |
| SM-14 | No NPC name is stored — the model carries the speaker's name only (**D5**) | |

## MS — `search_memories`

| ID | Case | Test function |
|---|---|---|
| MS-01 | Returns the semantically nearest memories first | |
| MS-02 | Returns at most `top_k` | |
| MS-03 | Fewer than `top_k` matches returns all of them, not an error | |
| MS-04 | No memories for the pair returns `[]` | |
| MS-05 | Each result carries summary, both messages, similarity, `created_at` and speaker name | |
| MS-06 | Both UUIDs are required — results are always scoped to the pair (**D3**) | |
| MS-07 | Rows with no embedding are skipped, not ranked as zero | |
| MS-08 | A stored vector of a different dimension is skipped rather than raising | |
| MS-09 | `similarity` is in `[-1.0, 1.0]` and is 1.0 for an exact text match | |
| MS-10 | Another NPC's memories with the same speaker are excluded | |
| MS-11 | A UUID matches exactly — a near-miss returns nothing, and there is no name fallback (**D3**) | |
| MS-12 | Retired — see *Departures* D3 | — |
| MS-13 | Retired — see *Departures* D3 | — |
| MS-14 | A failed embedding returns `None`, distinct from `[]`, with no recency substitution (**D2**) | |
| MS-15 | `top_k=0` returns `[]` | |
| MS-16 | **[pg]** pgvector path returns the same ordering as the numpy path for the same corpus | |
| MS-17 | Ties in similarity produce a deterministic order | |

## MR — `get_recent_memories`

| ID | Case | Test function |
|---|---|---|
| MR-01 | Returns the most recent `limit` memories for the pair | |
| MR-02 | Results are ordered oldest first, having selected the newest `limit` | |
| MR-03 | No memories returns `[]` | |
| MR-04 | Results carry no `similarity` key | |
| MR-05 | Embeds nothing, and so cannot fail the way a search can | |
| MR-06 | Both UUIDs are required and match exactly (**D3**) | |
| MR-07 | Another speaker's exchanges with the same NPC are excluded (**D3**) | |

## LI — `get_last_interaction_time`

| ID | Case | Test function |
|---|---|---|
| LI-01 | Returns the timestamp of the most recent exchange for the pair | |
| LI-02 | No history returns the documented empty result | |
| LI-03 | Another speaker's memories do not satisfy the query | |
| LI-04 | Both UUIDs must match, and there is no name fallback (**D3**) | |
| LI-05 | Returns both the timestamp and a relative-time phrase | |
| LI-06 | The returned datetime is timezone-aware | |
| LI-07 | Each relative-time band is produced at its boundary — under an hour, same day, yesterday, days, weeks, a month name, beyond a year | |
| LI-08 | A delta beyond a year phrases as such rather than falling back to a month name | |

## LS — `search_lore`

| ID | Case | Test function |
|---|---|---|
| LS-01 | Returns the semantically nearest accessible entries first | |
| LS-02 | Returns at most `top_k` | |
| LS-03 | Each result carries title, content, scope level and similarity | |
| LS-04 | An entry the caller's tags do not admit never appears, however similar | |
| LS-05 | Entries with an empty tag list are returned to a caller passing no tags | |
| LS-06 | Entries with no embedding are skipped | |
| LS-07 | A wrong-dimension stored vector is skipped rather than raising | |
| LS-08 | Empty corpus returns `[]` | |
| LS-09 | A failed embedding returns `None`, distinct from `[]`, with no recency substitution (**D2**) | |
| LS-10 | **[pg]** Inadmissible entries occupying the nearest ranks do not starve the result (**D1**) | |
| LS-11 | **[pg]** pgvector and numpy paths return the same entries in the same order for the same corpus | |
| LS-12 | A result set smaller than `top_k` because of tag filtering is returned, not padded | |
| LS-13 | Takes no speaker — lore is scoped by tags, never by who is asking | |

## SC — scope access rules

The rule under test: an entry's tags are an **AND** requirement — a row is returned only when every tag
it carries is in the list the caller passed. A row tagged `["millholm", "mages_guild"]` reaches a caller
holding both and not one holding only the first. Rows say who may know them; callers say what they are
part of; return where the first is contained in the second.

`scope_level` sits alongside the tags: it is stored, indexed, returned in results, and carries the
`continental` term in the SQL pre-filter. The Python access rule reads tags only.

| ID | Case | Test function |
|---|---|---|
| SC-01 | Empty entry tags are accessible to everyone | |
| SC-02 | Empty entry tags are accessible to a caller passing no tags | |
| SC-03 | Single matching tag grants access | |
| SC-04 | Single non-matching tag denies access | |
| SC-05 | Two entry tags with only one held denies access | |
| SC-06 | Two entry tags with both held grants access | |
| SC-07 | A caller holding a superset of the entry's tags is granted access | |
| SC-08 | Tag comparison is exact — case and whitespace are significant | |
| SC-09 | Duplicate tags on either side do not change the answer | |
| SC-10 | Tag order does not change the answer | |
| SC-11 | Tags compare by equality and set membership — the library imposes no type, as the game does not | |
| SC-12 | The Python rule and the SQL filter agree — neither admits an entry the other would reject | |
| SC-13 | **[pg]** The pgvector query expresses the tag rule itself, rather than post-filtering a ranked window (**D1**) | |
| SC-14 | `scope_level` is stored and returned unchanged, and does not decide access | |
| SC-15 | A row with empty tags is returned whatever its `scope_level` | |

## BE — backend dispatch

| ID | Case | Test function |
|---|---|---|
| BE-01 | A SQLite alias selects the numpy path | |
| BE-02 | **[pg]** A PostgreSQL alias selects the pgvector path | |
| BE-03 | Backend detection reads the library's own alias, not `default` | |
| BE-04 | A missing alias configuration fails loudly at call time, not silently as SQLite | |
| BE-05 | Cosine similarity of a vector with itself is 1.0 | |
| BE-06 | Cosine similarity of orthogonal vectors is 0.0 | |
| BE-07 | A zero vector yields 0.0 rather than dividing by zero | |
| BE-08 | Similarity is symmetric | |

## RT — database router

| ID | Case | Test function |
|---|---|---|
| RT-01 | Reads of the library's models route to its own alias | |
| RT-02 | Writes of the library's models route to its own alias | |
| RT-03 | Another app's model returns `None` for read and for write, so a sibling router gets its say | |
| RT-04 | Relations between two of the library's models are allowed | |
| RT-05 | A relation involving a foreign model returns `None` | |
| RT-06 | The library's migrations apply only on its own alias | |
| RT-07 | Another app's migrations are refused on the library's alias | |
| RT-08 | Another app's migrations on another alias return `None` | |
| RT-09 | Co-installed with a second router claiming a different app, neither captures the other's models | |

## LG — logging

The library logs to a logger of its own, so an operator reading its output is not searching the game's
log for it. The substrate already does this. The library installs no handler — the consumer attaches
one, and decides whether anything reaches a screen.

| ID | Case | Test function |
|---|---|---|
| LG-01 | Every log record goes to the library's own named logger, never the root logger | |
| LG-02 | A dropped write logs the cause, not just that something failed | |
| LG-03 | Each retry attempt is logged, and so is the final drop | |
| LG-04 | The library adds no handler and sets no level — the consumer owns both | |
| LG-05 | Nothing is written to stdout or stderr directly | |
| LG-06 | A read that could not embed is logged, so an outage is visible to an operator | |

## XC — cross-cutting

| ID | Case | Test function |
|---|---|---|
| XC-01 | The library imports no Evennia — asserted statically over the source tree | |
| XC-02 | Every public function returns plain data — no model instances, no querysets, no formatted prose | |
| XC-03 | A search result is a new object each call; mutating it does not affect stored rows | |
| XC-04 | Every public function is synchronous and returns rather than dispatching | |
| XC-05 | Interaction and lore searches are independent — a row of one kind never appears in the other's results | |
| XC-06 | Scope tags reach the library as a plain list of strings; the library resolves nothing | |
| XC-07 | A rebuild of the consumer's `default` database leaves the library's rows intact | |
| XC-08 | Timestamps are timezone-aware throughout | |
| XC-09 | The package installs and the runner reaches it | `test_version` |
| XC-10 | The library is registered as a Django app | `test_app_installed` |
| XC-11 | The library's own database alias is configured | `test_ai_memory_alias_configured` |
| XC-12 | Every read returns the same result shape whichever path it took | |

## Departures

Everything else in this plan replicates the game's current behaviour. These five do not, and each
traces to a decision taken in discussion. Nothing may be added here without one.

**D1. Lore filtering happens before ranking, on both backends.** Today the two disagree: SQLite applies
the tag rule to every row and then ranks; PostgreSQL ranks first, takes `top_k * 3` as headroom, and
applies the rule inside that window — so rows the caller's tags don't admit can occupy every slot and
starve a result that qualifying rows would have filled. There is no single existing behaviour to
replicate, so one had to be chosen. The SQLite behaviour wins because it is what the lore design
describes. Covers LS-10, SC-12, SC-13.

**D2. A read that cannot embed reports it, and does not retry.** To search, the query text has to become
a vector, which is a call out to the embedding service. When that call fails there is nothing to search
with. Today the library quietly runs a recency query instead and returns the result as though the search
had worked — different shape, different ordering, and on the memory side the speaker filter is dropped
so another speaker's rows come back. The library instead returns `None`: `None` means "could not
search", `[]` means "searched, found nothing". The caller decides what to do about it — a read has
someone waiting on it, so there is no retry either. Covers MS-14, LS-09, EM-09, LG-06.

**D3. Rows are keyed by UUID.** Every entity that holds or appears in a memory carries a UUID, unique
and stable across instances and rebuilds. The caller supplies it, the library matches it exactly, and
both UUIDs are required on every memory read — a memory is the history between one NPC and one speaker,
so the pair is the scope.

This replaces an id-and-name pair with a conditional between them. Today a row carries an Evennia dbref
and an object key; a search filters on the dbref and falls back to the key only when the dbref query
returns nothing. The dbref is a bare integer with nothing anchoring it — a rebuild reassigns it from a
restarted sequence — and the fallback stops firing as soon as one row exists under the new dbref. A
UUID has neither problem. Covers MS-06, MS-11, MR-06, MR-07, LI-04; retires MS-12 and MS-13.

**D4. A write retries a transient failure, then logs and drops it.** Today an embedding failure is
swallowed and the row is written anyway with no vector — stored, and unreachable by any search. The
library retries what can succeed on a retry, drops a permanent failure immediately, logs either way,
never raises into the caller, and never writes a row it cannot return. Writes are dispatched off the
reactor with nothing waiting on them, which is what makes retrying affordable here and not on a read.
Covers SM-07 to SM-09, EM-02, EM-03.

**D5. The summary is written in the second person, and no NPC name is stored.** Today it reads
`Bob said: "…" | Bron replied: "…"`. It becomes `Bob said: "…" | You replied: "…"`, because the summary
is a prompt input for that NPC and second person is how it will be read. The NPC's name then has no
reader — it was never returned in results, and D3 removes the name fallback that was its other use — so
it goes from the signature and the model. The speaker's name stays: it is in the summary and it comes
back in every result. Covers SM-03, SM-14.

## Open decisions

None. Every case above is agreed and can be written.

The relative-time phrase from `get_last_interaction_time` stays: it exists so an NPC can greet a
returning player differently from a stranger, or from someone who was standing there a minute ago, and
the phrasing is tuned for that rather than for display. The caller discards the timestamp and uses only
the phrase and whether there was any history at all.

Questions that do not block a case — embedding dimensions, migration squashing, the lore importer,
`contrib/` — are listed under *Out of scope* in [../CLAUDE.md](../CLAUDE.md).

## Retired

**Combat memory (`CM`).** Out of scope: the substrate has a `CombatMemory` model and migrations but no
service and no caller, and the schema will change once there is a strategy bot to serve. `[TBD — needs
discussion: whether combat memory later lands in this library or in one of its own.]`

**`store_lore` (`SL`).** Out of scope for stage 1. Nothing in the game calls it — lore is written only
by the standalone importer in the lore content repo, which talks to the table directly. The importer
stays where it is, so `search_lore` is the only function that touches lore in stage 1. The `LoreMemory`
model and its migrations still ship, because something has to create the table the importer writes to.
Bringing the importer in, with the validator that gates an import and the `evennia-yaml-reader`
dependency that follows, is stage 2.

**`get_recent_lore` (`LR`).** Dropped. Its only job was being the fallback D2 removes, and "the most
recently updated lore" is not a useful answer to "what does this NPC know about the great war" — lore is
not time-ordered the way an interaction history is.

Prefixes stay reserved so the IDs are never reused.

## Settled

Properties the library carries over from the game unchanged, each pinned by a case:

- Two tables in one database of their own, behind the library's router (RT block, XC-07).
- Retrieval returns plain data, never prompt text (XC-02).
- Lore is scoped by tags on the row against tags supplied by the caller, and never by who is asking
  (SC block, LS-13).
- Scope tags arrive as a plain list of strings the library never resolves (XC-06).
- Every function is synchronous; the consumer owns the dispatch (XC-04).
- The library logs to its own named logger (LG block).
- No rate limiting and no cost tracking; a consumer caps spend with a budgeted API key and reads usage
  from the provider's dashboard (EM-08).
