# Installing

Everything a consumer does to get `evennia-ai-memory` running, in the order they do it. Eight steps;
each one is needed, and the game will not start — or lore will not load — if any is skipped. The
settings are collected at the end, with what happens when each is absent and what the library cannot
check for you.

## 1. Install the package

Not yet published to PyPI. Install from a checkout, into the same environment your game runs in:

```
git clone https://github.com/FullCircleMUD/evennia-ai-memory.git
cd evennia-ai-memory
pip install -e .
```

That brings `evennia`, `django`, `numpy`, `openai`, `pgvector` and `psycopg` with it. The sibling
libraries it depends on are also required and **none is published**, so pip cannot resolve them by name — install
each from its own checkout:

```
pip install -e ../evennia-database-cascade -e ../evennia-logging-extension -e ../evennia-targeting -e ../evennia-yaml-reader
```

## 2. Add the apps

In your gamedir's `server/conf/settings.py`, below `from evennia.settings_default import *`:

```python
INSTALLED_APPS += ["evennia_ai_memory", "evennia_database_cascade"]
```

Both are required. Leave this library out and its `AppConfig.ready()` never runs, so nothing
validates your settings and nothing tells you why the first NPC conversation failed. Leave the
cascade out and the next step has nothing to resolve the alias.

**Below the Evennia import, always.** `LOG_DIR` is set by `from evennia.settings_default import *`,
and this library resolves its log directory when it is first imported. Imported above that line it
is refused at boot, naming the setting.

## 3. Let the cascade place the database

This library ships its declaration — the alias `ai_memory`, its SQLite fallback `ai_memory.db3`, and
the `vector` extension requirement. What remains for you is the cascade's one settings call and, per
deployment, whether to give the memories a database of their own. Follow
[evennia-database-cascade's installing.md](../../evennia-database-cascade/docs/installing.md); write
no `DATABASES` entry and no router yourself, because both are derived from the declaration and a
hand-written one can disagree with it.

Two facts are specific to this library:

**Every rung is available, including the shared one.** `DATABASE_URL_AI_MEMORY` gives the memories a
database of their own; `DATABASE_URL` alone puts them in the game's; neither lands them in
`server/ai_memory.db3`. The shared rung is allowed deliberately — a single-instance game can
reasonably keep everything in one database, and nothing here shares a table name with Evennia, so the
alias gets a second set of tables rather than the game's.

**Know what the shared rung costs.** Memories in the game's database are destroyed when that database
is rebuilt, which is the outcome a separate alias otherwise prevents.

## 4. Point it at an embeddings endpoint

```python
AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")
```

All three are required — see *Required settings* below. Any OpenAI-compatible embeddings endpoint
works; the base URL is the whole provider switch.

**Read the key with `.get()` and a fallback, never `os.environ["..."]`.** A bare lookup raises
`KeyError` while settings are still being imported — *before* Evennia reaches the
`secret_settings.py` import at the bottom of the file. The crash pre-empts the very mechanism meant
to supply the value, and you get an unhelpful traceback instead of the library's own startup error.
An empty string is fine here: the library treats empty as missing and says so by name.

## 5. Point it at your lore repository

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

Copy those dotted paths exactly. `GitHubReader` lives in `evennia_yaml_reader.github`, with a
capital H — `evennia_yaml_reader.local.GitHubReader` is a common slip and fails at startup.

**On secret settings and ordering.** If the PAT comes from `secret_settings.py`, either put the whole
`AI_MEMORY_READER_KWARGS` block in that file — it is imported last, so it overrides — or place the
block *below* the `from server.conf.secret_settings import *` line. A name defined in secret settings
does not exist earlier in the file, and referencing it above that import is a `NameError` at server
start.

## 6. Create the tables

```
evennia cascade_migrate
```

One command, not two: the cascade migrates the game database and then every alias it placed, in the
right order. Skip it and every call fails with `no such table: evennia_ai_memory_lorememory`.

**On PostgreSQL the `vector` extension must already exist** in the target database. The spec declares
it required, so the cascade checks before any migration runs and refuses with the command to run —
creating an extension needs superuser, and an application role deliberately is not one:

```
psql -d <your database> -c "CREATE EXTENSION vector"    # as a superuser, once per database
```

Extensions are per-database and go with a drop, so this belongs to provisioning rather than
deployment. On SQLite there is nothing to install.

## 7. Prepare your lore repository

A lore repository is YAML and a manifest, and nothing else. At its root:

```yaml
# index.yaml
sources:
  - continental.yaml
  - factions/mages_guild.yaml
  - millholm/regional.yaml
```

**The manifest is what the repository consists of.** The importer reads the paths it names; it does
not go looking. A file not listed is never imported, so add a new lore file to the manifest in the
same commit that adds the file. A file listed but missing stops the import rather than passing
quietly — deliberately, because that catches a deletion which forgot the list.

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

- `title` — with `source`, this identifies the entry. That pair is how a re-import tells an edit from
  a new entry.
- `scope_level` — any non-empty string. The library does not check it against a vocabulary;
  `continental` / `regional` / `local` / `faction` is a convention, not a rule.
- `scope_tags` — a list deciding who can reach it. **An entry is returned only when every tag it
  carries is one the asking NPC holds.** So `["millholm", "mages_guild"]` reaches a guild member in
  Millholm and nobody else. An empty list reaches everyone.
- `content` — the text, and the text that gets embedded. One topic, a paragraph or so: too short
  embeds weakly, too long buries the relevant sentence.

## 8. Load the lore

Start the game and log in as a superuser. Then, in game:

```
lore import dry
```

That reads the repository, validates every entry, and reports what it *would* change. It writes
nothing and calls no embedding API, so it is the cheap way to prove the reader, the manifest and the
YAML are all good. On a fresh install you should see everything counted as *created*.

Then, for real:

```
lore import
```

It embeds and stores — one embedding call per new or changed entry — and reports created, updated,
unchanged and removed counts, naming anything removed.

Re-running is safe and cheap: unchanged entries are skipped without embedding. **The repository is
the source of truth**, so an entry deleted from the YAML is deleted from the database on the next
import.

To empty the table deliberately:

```
lore wipe
```

It asks for confirmation and does nothing unless you type `yes` in full. Safe, because an import
restores everything from the repository.

## Checking it worked

- The game's log directory holds `ai_memory.log`. `cascade.log` names the database the alias
  resolved to.
- `lore import dry` reports the number of entries you expect.
- `lore import` reports that number as *created* the first time and as *unchanged* the second.

## Required settings

No defaults, checked at boot, and the instance does not start without them. The library ships no
provider defaults because a default endpoint or model name would be choosing a provider on your
behalf and burying that choice in library code.

| Setting | What it does | Without it |
|---|---|---|
| `AI_MEMORY_EMBEDDING_BASE_URL` | The embeddings endpoint. Any OpenAI-compatible one | Refused at boot, naming the setting |
| `AI_MEMORY_EMBEDDING_API_KEY` | The key for that endpoint | Refused at boot, naming the setting |
| `AI_MEMORY_EMBEDDING_MODEL` | The embedding model to call | Refused at boot, naming the setting |

Absent and empty are the same failure: a blank key is not a key. All three are reported together, so
one restart hands back the whole list rather than one setting per attempt.

## Optional settings

| Setting | Default | Why that default |
|---|---|---|
| `AI_MEMORY_EMBEDDING_DIMENSIONS` | `1536` | A storage width rather than a product name, so choosing it picks no provider on your behalf. Set it **before the first migration** — it decides the vector column's width, and changing it once rows exist means re-embedding all of them, because vectors of two widths are not comparable |
| `AI_MEMORY_READER` | `evennia_yaml_reader.github.GitHubReader` | A deployment reads lore from GitHub; a local checkout is the authoring loop, so the deployment case is the default |
| `AI_MEMORY_READER_KWARGS` | `{}` | The arguments belong to whichever reader you chose, so the library has nothing to supply |

## What is not checked for you

- **`INSTALLED_APPS`.** Leave this library out and `AppConfig.ready()` never runs, so nothing
  validates anything — including the three required settings above. Leave
  `evennia_database_cascade` out and `configure()` resolves no alias.
- **The reader's keyword arguments.** `AI_MEMORY_READER_KWARGS` is handed to whichever class
  `AI_MEMORY_READER` names, and the mismatch surfaces when the reader is built rather than at boot.
  `GitHubReader` needs `repo`, `ref` and `pat`; `LocalReader` needs `root`.
- **Which database rung you took.** The library cannot know which is right for your deployment, so
  it neither guesses nor warns. `cascade.log` records the answer; read it rather than reasoning
  about where each environment variable was set.
- **The `vector` extension, at boot.** It is checked when you run `cascade_migrate`, not when the
  game starts. A game that boots is not yet a game whose migrations will apply.
- **That your model returns the width you configured.** A wrong-length vector is refused when it
  arrives rather than stored, so the mismatch shows up on the first embedding call.

## When it goes wrong

| What you see | What it means |
|---|---|
| `AI_MEMORY_EMBEDDING_… is not set` | That setting is missing or empty. If you used `os.environ[...]`, see step 4 — the crash may be pre-empting your secret settings |
| `KeyError` during settings import | Same cause, one step earlier. Use `.get()` |
| `no such table: evennia_ai_memory_…` | `cascade_migrate` was not run. Step 6 |
| `type "vector" does not exist` | PostgreSQL without the extension, and `cascade_migrate` was not the thing that stopped you — so the extension check was bypassed. Step 6 |
| A refused migrate naming `CREATE EXTENSION` | The cascade doing its job: run the command it names, then migrate again. Step 6 |
| `AI_MEMORY_READER names … which could not be imported` | Check the dotted path against step 5, especially `github` versus `local` and the capital H |
| `index.yaml was not found` | Either the reader root or repo is wrong, or the manifest is missing. Step 7 |
| `auth failed reading … the token was rejected` | The PAT is wrong or lacks scope. A private repo needs `repo` scope; without it GitHub answers 404, which reports as *not found* rather than as an auth failure |
| `… was not found (named by the manifest)` | The manifest lists a file that is not there. Step 7 |
| `NameError` naming your PAT variable | The reader block sits above the `secret_settings` import. Step 5 |
| Import refused, problems listed | One or more entries are malformed. Nothing was written; fix them and re-run |
