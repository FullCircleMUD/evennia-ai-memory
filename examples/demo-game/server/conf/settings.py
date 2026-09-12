r"""
Evennia settings file.

The available options are found in the default settings file found
here:

https://www.evennia.com/docs/latest/Setup/Settings-Default.html

Remember:

Don't copy more from the default file than you actually intend to
change; this will make sure that you don't overload upstream updates
unnecessarily.

When changing a setting requiring a file system path (like
path/to/actual/file.py), use GAME_DIR and EVENNIA_DIR to reference
your game folder and the Evennia library folders respectively. Python
paths (path.to.module) should be given relative to the game's root
folder (typeclasses.foo) whereas paths within the Evennia library
needs to be given explicitly (evennia.foo).

If you want to share your game dir, including its settings, you can
put secret game- or server-specific settings in secret_settings.py.

"""

######################################################################
# macOS only: use a bundled, non-Apple SQLite build
#
# macOS ships /usr/lib/libsqlite3.dylib, which drives sqlite3_initialize()
# through libdispatch. libdispatch does not survive fork(), so once any
# SQLite connection has been opened, a daemonizing (forking) start deadlocks
# on the child's first SQLite call — silently, with no error or timeout.
# `evennia start` forks on Unix; `--nodaemon` and Windows do not, which is
# why this only bites daemonized starts on macOS.
#
# A connection is always open by then: evennia._init() imports
# evennia/utils/gametime.py, which runs a ServerConfig query at module scope.
#
# This has to run before anything imports sqlite3 — once the stdlib module is
# cached, Django's backend gets Apple's build regardless — so it sits above
# the settings_default import rather than with the rest of the demo's
# settings below. The executable half is the same in every sibling demo
# gamedir; a difference between two copies would be a defect rather than a
# variation.
######################################################################

import sys

if sys.platform == "darwin":
    try:
        import sqlean
        import sqlean.dbapi2

        class _AiMemoryConnection(sqlean.dbapi2.Connection):
            def getlimit(self, category):
                # Django uses this only to size bulk_create batches.
                return 999

        _sqlean_connect = sqlean.dbapi2.connect

        def _connect(*args, **kwargs):
            kwargs.setdefault("factory", _AiMemoryConnection)
            return _sqlean_connect(*args, **kwargs)

        sqlean.dbapi2.connect = _connect
        sqlean.connect = _connect
        sqlean.SQLITE_LIMIT_VARIABLE_NUMBER = 9
        sqlean.dbapi2.SQLITE_LIMIT_VARIABLE_NUMBER = 9

        sys.modules["sqlite3"] = sqlean
        sys.modules["sqlite3.dbapi2"] = sqlean.dbapi2
    except ImportError:
        pass


# Use the defaults from Evennia unless explicitly overridden
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "demo-game"

INSTALLED_APPS += ["evennia_ai_memory", "evennia_database_cascade"]

# The cascade reads every installed library's db_spec and resolves each alias:
# its own database where DATABASE_URL_<ALIAS> names one, the game's where the
# common URL does, otherwise a SQLite file under server/. The routers come
# from the same answer, so routing and migration cannot disagree.
from evennia_database_cascade import configure

DATABASES, DATABASE_ROUTERS = configure(DATABASES, INSTALLED_APPS, GAME_DIR, os.environ)

AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")

# local test
AI_MEMORY_READER = "evennia_yaml_reader.local.LocalReader"
AI_MEMORY_READER_KWARGS = {"root": "/Users/timbaird/Documents/fcm-umbrella/content/lore"}





######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")


#github test
#AI_MEMORY_READER = "evennia_yaml_reader.github.GitHubReader"
#AI_MEMORY_READER_KWARGS = {
#    "repo": "FullCircleMUD/lore",
#    "ref": "main",
#    "pat": AI_MEMORY_READER_GITHUB_PAT,
#}

# PAT LOADED FROM SECRET SETTINGS