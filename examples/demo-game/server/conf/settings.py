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

# Use the defaults from Evennia unless explicitly overridden
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "demo-game"

from evennia_ai_memory.config import ai_memory_database

INSTALLED_APPS += ["evennia_ai_memory"]

DATABASES["ai_memory"] = ai_memory_database(os.path.join(GAME_DIR, "ai_memory.db3"))

_AI_MEMORY_ROUTER = "evennia_ai_memory.db_router.AiMemoryRouter"
DATABASE_ROUTERS = list(globals().get("DATABASE_ROUTERS", []))
if _AI_MEMORY_ROUTER not in DATABASE_ROUTERS:
    DATABASE_ROUTERS.append(_AI_MEMORY_ROUTER)

AI_MEMORY_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
AI_MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
AI_MEMORY_EMBEDDING_API_KEY = os.environ.get("AI_MEMORY_EMBEDDING_API_KEY", "")

# local test
AI_MEMORY_READER = "evennia_yaml_reader.local.LocalReader"
AI_MEMORY_READER_KWARGS = {"root": "/Users/timbaird/Documents/fcm-umbrella/lore"}





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
#   "pat": AI_MEMORY_READER_GITHUB_PAT,
#}

# PAT LOADED FROM SECRET SETTINGS