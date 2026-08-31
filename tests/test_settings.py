# SPDX-License-Identifier: BSD-3-Clause
"""Minimal Django settings for evennia-ai-memory unit tests.

Imports Evennia's defaults, adds the library to INSTALLED_APPS, and runs two
in-memory sqlite databases with the library's router. No gamedir required.
"""

import os
import sys
import tempfile

import evennia

# Evennia 6.0.0+ ships migrations that import ``typeclasses.objects``
# (a gamedir module). Put Evennia's game_template on sys.path so the
# import resolves without requiring a real gamedir.
_game_template = os.path.join(os.path.dirname(evennia.__file__), "game_template")
if _game_template not in sys.path:
    sys.path.insert(0, _game_template)

from evennia.settings_default import *  # noqa: F401, F403, E402

# Evennia path bits — point at safe scratch locations so settings_default's
# path-derived defaults resolve without needing a real gamedir.
GAME_DIR = tempfile.gettempdir()
LOG_DIR = os.path.join(tempfile.gettempdir(), "evennia_ai_memory_test_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Library under test
INSTALLED_APPS = list(INSTALLED_APPS) + ["evennia_ai_memory"]  # noqa: F405

# Two in-memory databases, mirroring a real consumer install: the game, and
# the memories it keeps separately from it.
#
# The TEST names are not decoration. Two aliases both saying ":memory:" look
# like one database to Django's test runner, which then treats the second as
# a mirror of the first — so the router would appear to work while both
# aliases pointed at the same physical database. Distinct shared-cache URIs
# keep them genuinely separate.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:evennia_ai_memory_test_default?mode=memory&cache=shared"},
    },
    "ai_memory": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:evennia_ai_memory_test_memories?mode=memory&cache=shared"},
    },
}

DATABASE_ROUTERS = ["evennia_ai_memory.db_router.AiMemoryRouter"]

# The library ships no provider defaults, so the suite supplies all three.
# Cases that exercise a missing setting override these locally.
AI_MEMORY_EMBEDDING_BASE_URL = "https://embeddings.test.invalid/v1"
AI_MEMORY_EMBEDDING_API_KEY = "test-only-key"
AI_MEMORY_EMBEDDING_MODEL = "test-embedding-model"

# Required Django bits
SECRET_KEY = "test-only-secret"
TEST_ENVIRONMENT = True
ROOT_URLCONF = "tests.urls"
