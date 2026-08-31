# evennia-ai-memory

Embedding-backed memory and lore retrieval for LLM-driven NPCs in the [Evennia](https://www.evennia.com/) ecosystem.

The library stores what an NPC knows and what it remembers, and retrieves both semantically. It is a Django app: it owns the tables, the embeddings and the search, and nothing else. It returns structured data, never prompt text.

## Status

**Scaffold.** The repository structure is in place per the FCM library standards; no library code has landed yet. Lore and interaction memory are being extracted from FullCircleMUD's `src/game/ai_memory/` Django app, where they were built and proven. See [docs/progress.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/progress.md) for the running milestone log.

## What it will provide

| System | Question it answers | Scope |
|---|---|---|
| Lore memory | *"What do I know about the world?"* | Shared, filtered per NPC by scope tags |
| Interaction memory | *"What do I know about you?"* | Per NPC, per speaker |

Both share one storage layer with two backends: pgvector with an HNSW index on PostgreSQL, numpy cosine similarity on SQLite for local development. The tables live on their own database alias behind a router, so rebuilding your game database does not erase what NPCs have learned.

## Is this for me?

You'd install this library if you're building a game with LLM-driven NPCs and want the retrieval layer solved: semantic search over authored world knowledge, per-NPC conversation history, and structured records of past encounters.

You would still own:

- **The prompts.** The library ships none. Templates and how retrieved data reaches them are yours.
- **Your spend.** The library does no rate limiting and no cost tracking. Cap it where your provider already offers it — an API key with a budget — and read usage from their dashboard.
- **The game concepts.** NPC identity and scope tags: you pass them in as identifiers and strings. The library never interprets them.
- **A UUID per entity.** Rows are keyed by a UUID you supply, stable across instances and world rebuilds. The library matches it exactly and never guesses that two identifiers mean the same thing.

If your NPCs read from a dialogue tree, or you only need to look up a handful of facts by key, you do not need this library — a table and an index will do.

## Install

Not yet published. For now, install from a checkout:

```
git clone https://github.com/FullCircleMUD/evennia-ai-memory.git
cd evennia-ai-memory
python -m venv venv
# Activate the venv (platform-specific)
pip install -e .
python runtests.py
```

### Configure

Add the app, its router and its database alias to your settings:

```python
INSTALLED_APPS += ["evennia_ai_memory"]
DATABASE_ROUTERS += ["evennia_ai_memory.db_router.AiMemoryRouter"]
DATABASES["ai_memory"] = {...}          # its own database, so it survives a game rebuild
```

Then point it at an embeddings endpoint. **All three are required** — the library ships no provider
defaults, because a default endpoint or model name would be choosing a provider for you. Keep the key
out of version control: secret settings, or the environment.

```python
AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ["AI_MEMORY_EMBEDDING_API_KEY"]
```

Any OpenAI-compatible embeddings endpoint works; the base URL is the whole provider switch. Miss any of
the three and the app refuses to start, naming the one that's absent.

Finally, create the tables:

```
evennia migrate --database ai_memory
```

## Learn more

- **[CLAUDE.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/CLAUDE.md)** — load-bearing principles and orientation for working in the repository.
- **[docs/INDEX.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/INDEX.md)** — index of design documents.
- **[docs/interoperability.md](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/docs/interoperability.md)** — how this library sits alongside its siblings.

## License

BSD 3-Clause. See [LICENSE](https://github.com/FullCircleMUD/evennia-ai-memory/blob/main/LICENSE).
