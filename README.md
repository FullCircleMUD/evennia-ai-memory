# evennia-ai-memory

Embedding-backed memory and lore retrieval for LLM-driven NPCs in the [Evennia](https://www.evennia.com/) ecosystem.

The library stores what an NPC knows and what it remembers, and retrieves both semantically. It is a Django app: it owns the tables, the embeddings and the search, and nothing else. It returns structured data, never prompt text.

## Status

Working. Both memory systems, the embeddings client and the lore commands are implemented, with a test suite covering them on SQLite. The PostgreSQL cases are agreed but not yet run. See [docs/progress.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/progress.md) for the milestone log.

## What it gives you

| System | Question it answers | Scope |
|---|---|---|
| Lore memory | *"What do I know about the world?"* | Shared, filtered per NPC by scope tags |
| Interaction memory | *"What do I know about you?"* | Per NPC, per speaker |

Both share one storage layer with two backends: pgvector with an HNSW index on PostgreSQL, numpy cosine similarity on SQLite for local development. The tables live on their own database alias behind a router, so rebuilding your game database does not erase what NPCs have learned.

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

Eight steps, in order. Each one is needed; the game will not start, or lore will not load, if any is skipped.

## 1. Install

Not yet published to PyPI. Install from a checkout, into the same environment your game runs in:

```
git clone https://github.com/FullCircleMUD/evennia-ai-memory.git
cd evennia-ai-memory
pip install -e .
```

That brings `evennia`, `evennia-yaml-reader`, `django`, `numpy`, `openai`, `pgvector`, `psycopg` and `dj-database-url` with it. Nothing else to install.

## 2. Register the app, the router and the database

In your gamedir's `server/conf/settings.py`:

```python
import os
from evennia_ai_memory.config import ai_memory_database

INSTALLED_APPS += ["evennia_ai_memory"]

DATABASES["ai_memory"] = ai_memory_database(os.path.join(GAME_DIR, "ai_memory.db3"))

# Append, never assign — and do not assume the list exists.
_AI_MEMORY_ROUTER = "evennia_ai_memory.db_router.AiMemoryRouter"
DATABASE_ROUTERS = list(globals().get("DATABASE_ROUTERS", []))
if _AI_MEMORY_ROUTER not in DATABASE_ROUTERS:
    DATABASE_ROUTERS.append(_AI_MEMORY_ROUTER)
```

All three are required. Without the router, the library's queries go to your game database and its tables are created there — which defeats the point of a separate alias.

**Don't write `DATABASE_ROUTERS += [...]`.** Evennia's defaults do not define that setting, so `+=` works only if some other library already created the list. If this is the first router in your gamedir it raises `NameError: name 'DATABASE_ROUTERS' is not defined` before the server starts; if it's your third, it happens to work — which is why the shortcut looks fine until it doesn't.

The form above is correct either way. It builds the list whether or not one exists, appends rather than replacing so it cannot drop a router another library added, and the membership check makes re-running it harmless. `evennia-message-bus` documents the same form, so a consumer running both ends up with one list holding both routers.

`ai_memory_database()` resolves in three steps: `DATABASE_URL_AI_MEMORY` if set, otherwise `DATABASE_URL`, otherwise the SQLite path you passed. It does not warn about which one it took — the library cannot know which is right for your deployment — so it writes the answer to its log at startup instead.

Worth knowing before relying on the second step: memories in the game's own database are destroyed when that database is rebuilt, which is the outcome a separate alias otherwise prevents.

## 3. Point it at an embeddings endpoint

```python
AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")
```

**All three are required.** The library ships no provider defaults, because a default endpoint or model name would be choosing a provider for you. Miss any and the app refuses to start, naming the one that is absent. Any OpenAI-compatible embeddings endpoint works; the base URL is the whole provider switch.

**Read the key with `.get()` and a fallback, never `os.environ["..."]`.** A bare lookup raises `KeyError` while settings are still being imported — *before* Evennia reaches the `secret_settings.py` import at the bottom of the file. The crash pre-empts the very mechanism meant to supply the value, and you get an unhelpful traceback instead of the library's own startup error. An empty string is fine here: the library treats empty as missing and says so by name.

Optionally, if your model is not 1536 dimensions:

```python
AI_MEMORY_EMBEDDING_DIMENSIONS = 768
```

Set this **before the first migration**. It decides the width of the vector column, and changing it once rows exist means re-embedding all of them — vectors of two widths are not comparable, and the old ones are silently skipped.

## 4. Point it at your lore repository

Lore lives in its own repository of YAML, read either from a local checkout or from GitHub. Pick one:

```python
# A local checkout — the fast loop while you are authoring.
AI_MEMORY_READER = "evennia_yaml_reader.local.LocalReader"
AI_MEMORY_READER_KWARGS = {"root": "/path/to/your/lore"}
```

```python
# A GitHub repository — what a deployment uses.
AI_MEMORY_READER = "evennia_yaml_reader.github.GitHubReader"
AI_MEMORY_READER_KWARGS = {
    "repo": "your-org/lore",
    "ref": "main",
    "pat": "ghp_...",
}
```

Copy those dotted paths exactly. `GitHubReader` lives in `evennia_yaml_reader.github`, with a capital H — `evennia_yaml_reader.local.GitHubReader` is a common slip and fails at startup.

**On secret settings and ordering.** If the PAT comes from `secret_settings.py`, either put the whole `AI_MEMORY_READER_KWARGS` block in that file — it is imported last, so it overrides — or place the block *below* the `from server.conf.secret_settings import *` line. A name defined in secret settings does not exist earlier in the file, and referencing it above that import is a `NameError` at server start.

## 5. Create the tables

Two migrations, not one:

```
evennia migrate
evennia migrate --database ai_memory
```

The second creates the library's tables on its own alias. Skip it and every call fails with `no such table: evennia_ai_memory_lorememory`.

**On PostgreSQL, the `vector` extension must already exist** in the target database. The migration does not create it, because doing so needs superuser and an application role should not have it:

```
psql -d <your database> -c "CREATE EXTENSION vector"    # as a superuser, once per database
```

Extensions are per-database and go with a drop, so this belongs to provisioning rather than deployment. On SQLite there is nothing to install.

## 6. Prepare your lore repository

A lore repository is YAML and a manifest, and nothing else. At its root:

```yaml
# index.yaml
sources:
  - continental.yaml
  - factions/mages_guild.yaml
  - millholm/regional.yaml
```

**The manifest is what the repository consists of.** The importer reads the paths it names; it does not go looking. A file not listed is never imported, so add a new lore file to the manifest in the same commit that adds the file. A file listed but missing stops the import rather than passing quietly — deliberately, because that catches a deletion which forgot the list.

Each content file carries a `source` and a list of entries:

```yaml
source: "millholm/regional.yaml"
entries:
  - title: "Founding of Millholm"
    scope_level: regional
    scope_tags: ["millholm"]
    content: |
      Millholm was founded roughly four hundred years ago by four
      families from the eastern coast.
```

Every entry needs all four fields:

- `title` — with `source`, this identifies the entry. That pair is how a re-import tells an edit from a new entry.
- `scope_level` — any non-empty string. The library does not check it against a vocabulary; `continental` / `regional` / `local` / `faction` is a convention, not a rule.
- `scope_tags` — a list deciding who can reach it. **An entry is returned only when every tag it carries is one the asking NPC holds.** So `["millholm", "mages_guild"]` reaches a guild member in Millholm and nobody else. An empty list reaches everyone.
- `content` — the text, and the text that gets embedded. One topic, a paragraph or so: too short embeds weakly, too long buries the relevant sentence.

## 7. Load the lore

Start the game and log in as a superuser. Then, in game:

```
lore import dry
```

That reads the repository, validates every entry, and reports what it *would* change. It writes nothing and calls no embedding API, so it is the cheap way to prove the reader, the manifest and the YAML are all good. On a fresh install you should see everything counted as *created*.

Then, for real:

```
lore import
```

It embeds and stores. Expect it to take a moment — one embedding call per new or changed entry — and to report created, updated, unchanged and removed counts, naming anything removed.

Re-running is safe and cheap: unchanged entries are skipped without embedding. **The repository is the source of truth**, so an entry deleted from the YAML is deleted from the database on the next import.

To empty the table deliberately:

```
lore wipe
```

It asks for confirmation and does nothing unless you type `yes` in full. Safe, because an import restores everything from the repository.

## 8. Check it worked

- The game's log directory now holds `ai_memory.log`, and its first line names the database the memories resolved to.
- `lore import dry` reports the number of entries you expect.
- In game, `lore import` reports the same number as *created* the first time and as *unchanged* the second.

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

## When it goes wrong

| What you see | What it means |
|---|---|
| `AI_MEMORY_EMBEDDING_… is not set` | That setting is missing or empty. If you used `os.environ[...]`, see step 3 — the crash may be pre-empting your secret settings. |
| `KeyError` during settings import | Same cause, one step earlier. Use `.get()`. |
| `no such table: evennia_ai_memory_…` | The second migration in step 5 was not run. |
| `type "vector" does not exist` | PostgreSQL without the extension. See step 5. |
| `AI_MEMORY_READER names … which could not be imported` | Check the dotted path against step 4, especially `github` versus `local` and the capital H. |
| `index.yaml was not found` | Either the reader root or repo is wrong, or the manifest is missing. Step 6. |
| `auth failed reading … the token was rejected` | The PAT is wrong or lacks scope. A private repo needs `repo` scope; without it GitHub answers 404, which reports as *not found* rather than as an auth failure. |
| `… was not found (named by the manifest)` | The manifest lists a file that is not there. |
| `NameError: name 'DATABASE_ROUTERS' is not defined` | `+=` on a setting Evennia does not define. Use the append form in step 2. |
| `NameError` naming your PAT variable | The reader block sits above the `secret_settings` import. Step 4. |
| Import refused, problems listed | One or more entries are malformed. Nothing was written; fix them and re-run. |

## Learn more

- **[docs/INDEX.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/INDEX.md)** — index of design documents.
- **[docs/test-plan.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/test-plan.md)** — every behaviour the library commits to, and the test covering it.
- **[docs/interoperability.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/interoperability.md)** — how this library sits alongside its siblings.
- **[CLAUDE.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## License

BSD 3-Clause. See [LICENSE](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/LICENSE).
