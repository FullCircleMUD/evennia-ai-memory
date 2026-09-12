# evennia-ai-memory

Embedding-backed memory and lore retrieval for LLM-driven NPCs in the [Evennia](https://www.evennia.com/) ecosystem.

The library stores what an NPC knows and what it remembers, and retrieves both semantically. It is a Django app: it owns the tables, the embeddings and the search, and nothing else. It returns structured data, never prompt text.

## Status

Working. Both memory systems, the embeddings client and the lore commands are implemented, with a test suite covering them on SQLite. The PostgreSQL cases are agreed but not yet run. See [docs/progress.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/progress.md) for the milestone log.

## What it gives you

| System | Question it answers | Scope |
|---|---|---|
| Lore memory | *"What do I know about the world?"* | Shared, filtered per NPC by scope tags |
| Interaction memory | *"What do I know about you?"* | Per NPC, per character |

Interaction memory records **events, not conversations** — what was said, but also that this character bought from the NPC, stole from it, taunted it, fled from it. You write the summary of what happened; the library embeds it, so a later question like *"has this one ever crossed me"* pulls the theft and the taunt alongside the argument.

Both share one storage layer with two backends: pgvector with an HNSW index on PostgreSQL, numpy cosine similarity on SQLite for local development. The tables live on a database alias of their own, placed by [evennia-database-cascade](https://github.com/FullCircleMUD/evennia-database-cascade), so rebuilding your game database does not erase what NPCs have learned — and a single-instance game that would rather keep one database can point the alias at the game's instead.

## Is this for me?

You'd install this library if you're building a game with LLM-driven NPCs and want the retrieval layer solved: semantic search over authored world knowledge, and per-NPC conversation history.

You would still own:

- **The prompts.** The library ships none. Templates and how retrieved data reaches them are yours.
- **Your spend.** The library does no rate limiting and no cost tracking. Cap it where your provider already offers it — an API key with a budget — and read usage from their dashboard.
- **The game concepts.** NPC identity and scope tags: you pass them in as identifiers and strings. The library never interprets them.
- **A UUID per entity.** Rows are keyed by a UUID you supply, stable across instances and world rebuilds. The library matches it exactly and never guesses that two identifiers mean the same thing.

If your NPCs read from a dialogue tree, or you only need to look up a handful of facts by key, you do not need this library — a table and an index will do.

---

# Setup

Eight steps, and they are all in **[docs/installing.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/installing.md)** — install the package and its three unpublished siblings, add the two apps, let `evennia-database-cascade` place the database, point the library at an embeddings endpoint and at your lore repository, migrate, author the manifest, import.

That document also collects the required settings, the optional ones with their defaults, what is not checked for you, and what to do when something goes wrong.

The short version, for orientation only:

```python
# server/conf/settings.py, below `from evennia.settings_default import *`
INSTALLED_APPS += ["evennia_ai_memory", "evennia_database_cascade"]

AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")
```

Plus the cascade's own settings call, which belongs to [evennia-database-cascade](https://github.com/FullCircleMUD/evennia-database-cascade) and is documented there — this library writes no database entry and no router of its own. Then:

```
evennia cascade_migrate     # then, in game as a superuser:  lore import
```

---

## Using it from your game code

Six functions, all synchronous. Wrap them in `deferToThread` or Evennia's `run_async` yourself — the library never dispatches off your thread, so you can put a memory lookup, a prompt render and a completion in one hop rather than three.

```python
from evennia_ai_memory import (
    store_memory, search_memories, get_recent_memories,
    get_last_interaction_time, search_lore,
)

# What does this NPC know about what the player just asked?
lore = search_lore(player_message, scope_tags=["millholm", "mages_guild"], top_k=3)

# What does it remember of this player?
memories = search_memories(npc_uuid, pc_uuid, player_message, top_k=5)

# Record what happened afterwards. You write the summary; the library embeds it.
store_memory(npc_uuid, pc_uuid, "Bob", f'Bob asked about a sword, and you said: "{npc_reply}"')
```

**A memory is an event, not a conversation.** The row holds a summary you wrote, so it records anything the two of them did — not only what was said:

```python
store_memory(npc_uuid, pc_uuid, "Bob", "Bob picked your pocket and got away with it.",
             interaction_type="pickpocket")
store_memory(npc_uuid, pc_uuid, "Bob", "You warned Bob off the north road; he ignored you.",
             interaction_type="warned", initiator="npc")
```

The library phrases nothing, because only your game knows how its own interactions read. `interaction_type` is any word you like and is never validated — it's your vocabulary and it will grow. `initiator` is `"pc"` or `"npc"`, defaults to `"pc"`, and is refused otherwise: two possible values, so an unrecognised one is a typo that would quietly mis-order however you render it.

Both come back on every result, so a caller can tell a theft from a greeting.

A search returns a list of dicts, `[]` when nothing matched, and **`None` when it could not search at all** — an embedding outage, say. Those are different answers and worth telling apart: `[]` means this NPC has nothing relevant, `None` means you never found out.

`scope_tags` is a plain list of strings you assemble. The library never resolves them from rooms or typeclasses; where they come from is yours.

## Learn more

- **[docs/installing.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/installing.md)** — the eight setup steps, every setting, and what to do when something goes wrong.
- **[docs/INDEX.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/INDEX.md)** — index of design documents.
- **[docs/test-plan.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/test-plan.md)** — every behaviour the library commits to, and the test covering it.
- **[docs/interoperability.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/interoperability.md)** — how this library sits alongside its siblings.
- **[CLAUDE.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## License

BSD 3-Clause. See [LICENSE](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/LICENSE).
