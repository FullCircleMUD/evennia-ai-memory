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

#: The ``DATABASES`` key the library's two tables live on. Declared to
#: ``evennia-database-cascade`` in ``db_spec``, which derives the entry and
#: the router from it; every query that names an alias names this one.
AI_MEMORY_ALIAS = "ai_memory"

#: Width of the stored vectors. Unlike the endpoint, the key and the model,
#: this one carries a default: 1536 names no provider's product, it is a
#: storage width, so choosing it for a consumer picks nothing on their behalf.
#: It must match what the configured model returns — a mismatch is refused at
#: the boundary rather than stored.
SETTING_DIMENSIONS = "AI_MEMORY_EMBEDDING_DIMENSIONS"

DEFAULT_DIMENSIONS = 1536

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

    from .log import ai_memory_log  # lazy — the module-scope form is a cycle

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


def get_embedding_dimensions() -> int:
    """Return the configured vector width, or the library's default.

    Read at import time by the models and by the initial migration, so the
    column is created at whatever width the consuming project asked for.
    Changing it once rows exist means re-embedding them: vectors of two widths
    are not comparable, and the old ones would be skipped in silence.
    """
    from django.conf import settings

    return int(getattr(settings, SETTING_DIMENSIONS, DEFAULT_DIMENSIONS))


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


def reader_settings_hint() -> str:
    """Name both reader settings, for any error a consumer might hit here.

    A misconfigured reader surfaces as "not found" or "auth failed" from deep
    inside a read, where the cause is invisible. Naming the two settings that
    could be wrong is the whole of the help available.
    """
    return f"{SETTING_READER} and {SETTING_READER_KWARGS}"


def get_reader_class():
    """Resolve the configured reader class from its dotted path.

    Raises:
        ImproperlyConfigured: naming both reader settings, since a consumer
            hitting this has one of them wrong and nothing else to go on.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured
    from django.utils.module_loading import import_string

    dotted = getattr(settings, SETTING_READER, DEFAULT_READER)
    try:
        return import_string(dotted)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"{SETTING_READER} names {dotted!r}, which could not be imported. "
            f"Check {reader_settings_hint()}."
        ) from exc


def get_configured_reader():
    """Instantiate the configured reader with its configured keyword arguments."""
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    reader_class = get_reader_class()
    kwargs = getattr(settings, SETTING_READER_KWARGS, {}) or {}
    try:
        return reader_class(**kwargs)
    except TypeError as exc:
        raise ImproperlyConfigured(
            f"{reader_class.__name__} could not be built from "
            f"{SETTING_READER_KWARGS}: {exc}. Check {reader_settings_hint()}."
        ) from exc


def validate_settings() -> None:
    """Check every required setting is present and non-empty.

    Called from ``AppConfig.ready()`` so a missing setting stops the app at
    startup rather than at the first NPC conversation.

    Raises:
        ImproperlyConfigured: naming the missing setting and where to put it.
    """
    for name in REQUIRED_SETTINGS:
        _required(name)
