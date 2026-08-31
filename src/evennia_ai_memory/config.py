# SPDX-License-Identifier: BSD-3-Clause
"""Read the library's configuration from Django settings.

Always use these accessors rather than reading ``settings.AI_MEMORY_*``
directly. Library code that touches ``settings`` itself is a defect — EM-12
asserts it statically.

The library ships **no provider defaults**. Endpoint, key and model are all
required: a default base URL or model name would choose a provider on the
consumer's behalf and bury that choice in library code. Absent any of them the
app refuses to start, naming the setting.
"""

import os

from .log import ai_memory_log

#: Environment variable naming a database for the memories alone.
MEMORY_URL_ENV = "DATABASE_URL_AI_MEMORY"

#: The game's own database URL. Used when the memories have no database of
#: their own, and so share the game's.
GAME_URL_ENV = "DATABASE_URL"

SETTING_BASE_URL = "AI_MEMORY_EMBEDDING_BASE_URL"
SETTING_API_KEY = "AI_MEMORY_EMBEDDING_API_KEY"
SETTING_MODEL = "AI_MEMORY_EMBEDDING_MODEL"

REQUIRED_SETTINGS = (SETTING_BASE_URL, SETTING_API_KEY, SETTING_MODEL)

#: Where a consumer is told to put the key when it is missing.
KEY_LOCATION_HINT = "settings.py, secret settings, or the environment"


def _required(name: str) -> str:
    """Return a required setting, or say precisely what is missing and where.

    Absent and empty are the same failure: a blank key is not a key.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    value = getattr(settings, name, None)
    if value is None or not str(value).strip():
        message = (
            f"{name} is not set. evennia_ai_memory ships no provider defaults, "
            f"so this must be set by the consuming project — in "
            f"{KEY_LOCATION_HINT}. Required alongside it: "
            f"{', '.join(s for s in REQUIRED_SETTINGS if s != name)}."
        )
        # Log as well as raise. The raise stops the app, which is what a
        # missing key deserves; the log puts the reason in the library's own
        # log, where an operator looks, rather than only in whatever the
        # consumer does with a startup traceback.
        ai_memory_log(message, level="ERROR")
        raise ImproperlyConfigured(message)
    return str(value)


def get_embedding_base_url() -> str:
    """Return the configured embeddings endpoint.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    return _required(SETTING_BASE_URL)


def get_embedding_api_key() -> str:
    """Return the configured embeddings API key.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    return _required(SETTING_API_KEY)


def get_embedding_model() -> str:
    """Return the configured embedding model name.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    return _required(SETTING_MODEL)


#: Dotted path to the reader class the import command uses. GitHub in
#: production; a consumer points it at the local reader for development.
SETTING_READER = "AI_MEMORY_READER"

#: Keyword arguments forwarded to that reader's constructor — the repository
#: and ref for GitHub, a root path for local.
SETTING_READER_KWARGS = "AI_MEMORY_READER_KWARGS"

DEFAULT_READER = "evennia_yaml_reader.github.GitHubReader"


def get_reader_class():
    """Resolve the configured reader class from its dotted path.

    Raises:
        ImproperlyConfigured: naming both reader settings, since a consumer
            hitting this has one of them wrong and nothing else to go on.
    """
    raise NotImplementedError


def get_configured_reader():
    """Instantiate the configured reader with its configured keyword arguments."""
    raise NotImplementedError


def ai_memory_database(sqlite_path: str) -> dict:
    """Resolve the memories database, for a consumer's ``DATABASES`` entry.

    Three rungs, in order:

    1. ``DATABASE_URL_AI_MEMORY`` — the memories have a database of their own.
    2. ``DATABASE_URL`` — the memories share the game's database.
    3. ``sqlite_path`` — a local file.

    Called from the consumer's settings::

        DATABASES["ai_memory"] = ai_memory_database(GAME_DIR / "ai_memory.db3")

    Which rung is *correct* depends on something the library cannot see, so
    this does not guess and does not warn. ``describe_ai_memory_database``
    puts the answer in the startup log instead.

    Rung two is worth understanding before relying on it: memories on the
    game's database are destroyed by a rebuild of that database, which is the
    thing a separate alias otherwise prevents.
    """
    import dj_database_url

    url = os.environ.get(MEMORY_URL_ENV) or os.environ.get(GAME_URL_ENV)
    if url:
        return dj_database_url.parse(url)
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(sqlite_path)}


def describe_ai_memory_database() -> str:
    """One phrase naming the memories database and where it came from.

    Written to the log at startup, so an operator can confirm which rung was
    taken by reading one line rather than reasoning about which environment
    variables were set where.

    Reports the database name and host only. The configuration holds
    credentials parsed out of a URL and they must never reach a log file.
    """
    from django.conf import settings

    from .db_router import DATABASE_ALIAS

    databases = getattr(settings, "DATABASES", {})
    memory = databases.get(DATABASE_ALIAS) or {}
    name = memory.get("NAME") or "?"
    host = memory.get("HOST")

    # Processes can share a SQLite database by symlinking one file into each
    # gamedir, so each has a different path to it. Report the target, or two
    # logs describing one file would disagree.
    if "sqlite" in str(memory.get("ENGINE", "")) and name != "?":
        name = os.path.realpath(name)

    where = f"{name!r} on {host!r}" if host else f"{name!r}"

    if os.environ.get(MEMORY_URL_ENV):
        return f"{where} (from {MEMORY_URL_ENV})"

    default = databases.get("default") or {}
    identity = ("ENGINE", "NAME", "HOST", "PORT")
    if all(memory.get(key) == default.get(key) for key in identity):
        return f"{where} (shared with the game database)"

    if "sqlite" in str(memory.get("ENGINE", "")):
        return f"{where} (local file)"
    return where


def validate_settings() -> None:
    """Check every required setting is present and non-empty.

    Called from ``AppConfig.ready()`` so a missing setting stops the app at
    startup rather than at the first NPC conversation.

    Raises:
        ImproperlyConfigured: naming the missing setting and where to put it.
    """
    for name in REQUIRED_SETTINGS:
        _required(name)
