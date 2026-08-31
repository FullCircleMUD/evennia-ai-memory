# SPDX-License-Identifier: BSD-3-Clause
"""Minimal Django settings for evennia-ai-memory unit tests.

Plain Django — no ``evennia.settings_default`` import, no gamedir. The library
is a Django app with no Evennia dependency, so nothing here needs Evennia's
settings surface. See CLAUDE.md principle 6.

Two database aliases are configured because the library keeps its tables in a
database of their own, separate from the consumer's game database, so memories
survive a game DB rebuild. The router that enforces the split is the library's;
tests exercise it against these two aliases.
"""

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "evennia_ai_memory",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    "ai_memory": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

DATABASE_ROUTERS = ["evennia_ai_memory.db_router.AiMemoryRouter"]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# The library ships no provider defaults, so the suite supplies all three.
# Cases that exercise a missing setting override these locally.
AI_MEMORY_EMBEDDING_BASE_URL = "https://embeddings.test.invalid/v1"
AI_MEMORY_EMBEDDING_API_KEY = "test-only-key"
AI_MEMORY_EMBEDDING_MODEL = "test-embedding-model"

SECRET_KEY = "test-only-secret"
ROOT_URLCONF = "tests.urls"

USE_TZ = True
