# SPDX-License-Identifier: BSD-3-Clause
"""The library's superuser commands.

Administering the library's own table is infrastructure rather than a game
concept, so these ship in core rather than ``contrib/`` — the same reasoning
that puts ``wb_build`` in ``evennia-world-builder``'s core.

Both defer their work off the reactor, so an import of a large repository does
not stop play. Because the work is deferred, a confirmation has to come back
through ``get_input()`` rather than ``yield``: the two are incompatible, and
the deferred one is not optional here.
"""

from evennia import Command

from .log import ai_memory_log


class CmdLoreImport(Command):
    """Bring the lore table into line with the lore repository.

    Usage:
        lore import
        lore import dry

    Reads the configured repository, validates all of it, and applies what
    changed — creating new entries, re-embedding changed ones, leaving
    unchanged ones alone, and removing entries the repository no longer holds.

    The repository is the source of truth. Nothing is written unless every
    entry validates; a read that resolves no entries is refused rather than
    taken to mean the lore was deleted.

    ``dry`` reports what would change and stops.
    """

    key = "lore import"
    locks = "cmd:perm(Developer) or perm(Admin) or superuser()"
    help_category = "Admin"

    def func(self):
        raise NotImplementedError


class CmdLoreWipe(Command):
    """Remove every entry from the lore table.

    Usage:
        lore wipe

    Asks for confirmation and does nothing without an explicit yes. Safe
    because the table is derived data — an import restores it from the
    repository. Memories are a different table and are not touched.
    """

    key = "lore wipe"
    locks = "cmd:perm(Developer) or perm(Admin) or superuser()"
    help_category = "Admin"

    def func(self):
        raise NotImplementedError
