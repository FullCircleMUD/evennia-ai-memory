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

import logging

logger = logging.getLogger("evennia_ai_memory.config")

SETTING_BASE_URL = "AI_MEMORY_EMBEDDING_BASE_URL"
SETTING_API_KEY = "AI_MEMORY_EMBEDDING_API_KEY"
SETTING_MODEL = "AI_MEMORY_EMBEDDING_MODEL"

REQUIRED_SETTINGS = (SETTING_BASE_URL, SETTING_API_KEY, SETTING_MODEL)

#: Where a consumer is told to put the key when it is missing.
KEY_LOCATION_HINT = "settings.py, secret settings, or the environment"


def get_embedding_base_url() -> str:
    """Return the configured embeddings endpoint.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    raise NotImplementedError


def get_embedding_api_key() -> str:
    """Return the configured embeddings API key.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    raise NotImplementedError


def get_embedding_model() -> str:
    """Return the configured embedding model name.

    Raises:
        ImproperlyConfigured: if the setting is absent or empty.
    """
    raise NotImplementedError


def validate_settings() -> None:
    """Check every required setting is present and non-empty.

    Called from ``AppConfig.ready()`` so a missing setting stops the app at
    startup rather than at the first NPC conversation.

    Raises:
        ImproperlyConfigured: naming the missing setting and where to put it.
    """
    # Unlike every other stub here, this one logs rather than raising. It is
    # called from AppConfig.ready(), so raising would stop the app — and the
    # test suite — before anything ran, which would hide the other 122 cases
    # rather than surfacing this one. Logging keeps the call site wired up and
    # makes the gap impossible to miss on every startup.
    logger.error(
        "NOT IMPLEMENTED: %s.validate_settings() — the required settings %s "
        "are NOT being checked at startup. A missing one will surface as a "
        "failure at the first embedding call instead. Covered by EM-04, "
        "EM-05, EM-10, EM-11 and EM-13 in docs/test-plan.md.",
        __name__,
        ", ".join(REQUIRED_SETTINGS),
    )
