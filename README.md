# evennia-ai-memory

Encounter memory and semantic lore retrieval for LLM-driven NPCs in the [Evennia](https://www.evennia.com/) ecosystem.

The library stores what an NPC knows and what it remembers, and gets both back fast. It is a Django app:
it owns the tables, the lore embeddings and the queries, and nothing else. It returns structured data,
never prompt text.

## Status

Working, with a test suite on SQLite. The PostgreSQL cases are agreed but not yet run. See
[docs/progress.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/progress.md) for the
milestone log.

## What it gives you

| System | Question it answers | Scope |
|---|---|---|
| Lore | *"What do I know about the world?"* | Shared, filtered per NPC by scope tags, searched semantically |
| Encounters | *"What happened before, with these people or people like them?"* | Per owner, any number of participants |

**An encounter is one row per encounter, as one party remembers it** — a summary, a full record, a
transcript of what was said, a structured analysis, a total level, and every participant with a side and
integer traits. You write all of it; nothing in an encounter is embedded. It is read back by who was in
it and how strong they were:

- **`shortlist_encounters`** — the owner's encounters most like one about to begin: those holding the
  same people, then those nearest its total level. Each comes with its participants, in one query.
- **`get_recent_transcripts`** — what was said in the owner's newest encounters with each of a group, in
  one query.
- **`get_recent_encounters`**, **`get_nearest_encounters`** and **`recall_encounters`** — by exact
  participants, and by the participants' traits summed and compared by Euclidean distance.

Lore is embedded and searched by similarity: pgvector with an HNSW index on PostgreSQL, numpy cosine
similarity on SQLite for local development. The tables live on a database alias of their own, placed by
[evennia-database-cascade](https://github.com/FullCircleMUD/evennia-database-cascade), so rebuilding your
game database does not erase what NPCs have learned.

## Is this for me?

You'd install it if you're building LLM-driven NPCs and want the retrieval layer solved: semantic search
over authored world knowledge, and an NPC's past encounters back in one round trip.

You still own:

- **The prompts.** The library ships none.
- **Your spend.** No rate limiting and no cost tracking — cap it on your provider's API key.
- **The game concepts.** NPC identity, sides, trait keys and scope tags are identifiers and strings you
  pass in. The library never interprets them.
- **A UUID per entity**, stable across instances and world rebuilds.

---

# Setup

Eight steps, all in **[docs/installing.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/installing.md)**
— install the package and its unpublished siblings, add the apps, let `evennia-database-cascade` place the
database, point the library at an embeddings endpoint and your lore repository, migrate, author the
manifest, import. The short version:

```python
# server/conf/settings.py, below `from evennia.settings_default import *`
INSTALLED_APPS += ["evennia_ai_memory", "evennia_database_cascade"]

AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")
```

```
evennia cascade_migrate     # then, in game as a superuser:  lore import
```

---

## Using it from your game code

Every function is synchronous. Wrap them in `deferToThread` yourself — the library never dispatches off
your thread, so a lookup, a prompt render and a completion can share one hop.

```python
from evennia_ai_memory import (
    get_recent_transcripts, search_lore, shortlist_encounters, store_encounter,
)

# What does this NPC know about what the player just asked?
lore = search_lore(player_message, scope_tags=["millholm"], top_k=3)

# An encounter is beginning: what is it most like, and what was said with these people before?
shortlist = shortlist_encounters(npc_uuid, [alice_uuid, bob_uuid], total_level=24, limit=100)
said = get_recent_transcripts(npc_uuid, [alice_uuid, bob_uuid], limit=5)

# It has ended: remember it.
store_encounter(
    npc_uuid, summary, record, analysis,
    participants=[{"uuid": alice_uuid, "name": "Alice", "side": "character", "traits": {"warrior": 12}}],
    total_level=12, transcript='Alice says, "Yield."',
)
```

A lore search returns a list of dicts, `[]` when nothing matched, and **`None` when it could not search at
all** — an embedding outage, say. `scope_tags` is a plain list of strings you assemble; where they come
from is yours.

## Learn more

- **[docs/installing.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/installing.md)** — setup, every setting, and what to do when something goes wrong.
- **[docs/INDEX.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/INDEX.md)** — index of design documents.
- **[docs/test-plan.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/test-plan.md)** — every behaviour the library commits to, and the test covering it.
- **[docs/interoperability.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/interoperability.md)** — how this library sits alongside its siblings.
- **[CLAUDE.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## License

BSD 3-Clause. See [LICENSE](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/LICENSE).
