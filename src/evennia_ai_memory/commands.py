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


#: The answers that count as consent at a destructive prompt. Deliberately
#: short: "y" is a keystroke away from a stray character, and this empties a
#: table.
CONSENT = ("yes",)


def confirmed(answer: str) -> bool:
    """Whether an answer at a confirmation prompt means yes.

    Only an explicit yes counts. A bare return, an unrecognised word, or
    anything the operator typed by reflex leaves the destructive path untaken —
    the default has to be the safe one.
    """
    return (answer or "").strip().lower() in CONSENT


def _off_thread(work, on_done, on_error):
    """Run ``work`` on a worker thread, with the callbacks on the reactor.

    Django hands each thread its own connections and Twisted never closes
    them, so the worker closes its own before returning — the callbacks run on
    the reactor thread and would walk the wrong thread's connections.
    """
    from django.db import connections
    from evennia.utils.utils import run_async

    def wrapped():
        try:
            return work()
        finally:
            connections.close_all()

    return run_async(wrapped, at_return=on_done, at_err=on_error)


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
        from . import config, lore_import

        dry = self.args.strip().lower() == "dry"
        reader = config.get_configured_reader()

        # Acknowledge before dispatching. The work happens on a worker thread,
        # so without this the operator types the command and gets silence until
        # every entry has been embedded — long enough to assume it was missed
        # and type it again.
        self._report(
            "Reading the lore repository"
            + (" (dry run — nothing will be written)…" if dry else "…")
        )

        def plan():
            return lore_import.plan_import(reader)

        def planned(plan_result):
            if dry:
                self._report(self._describe_plan(plan_result), "Nothing was written.")
                return
            # Report the plan before applying it. Embedding is the slow part,
            # and this is what tells the operator how much of it is coming —
            # so only say it when there is something to embed.
            work = len(plan_result.create) + len(plan_result.update)
            self._report(
                self._describe_plan(plan_result),
                "Embedding and storing — this may take a moment…" if work else None,
            )
            _off_thread(
                lambda: lore_import.apply_import(plan_result), applied, self._failed
            )

        def applied(report):
            self._report(self._describe_report(report))

        _off_thread(plan, planned, self._failed)

    def _report(self, *lines):
        """One message per phase — a report dribbled out a line at a time is
        harder to read and interleaves with whatever else the room is saying."""
        self.caller.msg("\n".join(str(line) for line in lines if line))

    def _failed(self, failure):
        from .lore_import import LoreValidationError

        error = getattr(failure, "value", failure)
        if isinstance(error, LoreValidationError):
            self._report(
                "Lore import refused. Nothing was written.",
                *error.problems,
            )
            return
        self._report(f"Lore import failed: {error}")

    @staticmethod
    def _describe_plan(plan):
        return (
            f"Would create {len(plan.create)}, update {len(plan.update)}, "
            f"leave {len(plan.unchanged)} unchanged, remove {len(plan.remove)}."
        )

    @staticmethod
    def _describe_report(report):
        lines = [
            f"Lore import complete: {len(report.created)} created, "
            f"{len(report.updated)} updated, {len(report.unchanged)} unchanged, "
            f"{len(report.removed)} removed."
        ]
        # Removals are named rather than counted. It is the only line that says
        # something is gone, and an operator who did not expect it needs to know
        # what went.
        for source, title in report.removed:
            lines.append(f"  removed: {source} — {title}")
        for source, title in report.failed:
            lines.append(f"  FAILED: {source} — {title}")
        return "\n".join(lines)


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
        from evennia.utils.evmenu import get_input

        from .db_router import DATABASE_ALIAS
        from .models import LoreMemory

        held = LoreMemory.objects.using(DATABASE_ALIAS).count()
        if not held:
            self.caller.msg("The lore table is already empty.")
            return

        # Set apart and coloured, because it reads past easily otherwise. A
        # destructive prompt buried in a paragraph of ordinary text is one an
        # operator answers without registering what it asked.
        get_input(
            self.caller,
            f"\n|rThis removes all {held} lore entries.|n An import restores "
            f"them from the repository.\n\n"
            f"|rType 'yes' to confirm, anything else to abort:|n ",
            self._answered,
        )

    @staticmethod
    def _answered(caller, prompt, answer):
        from .lore_import import wipe

        if not confirmed(answer):
            caller.msg("\nAborted. Nothing was removed.")
            return False
        caller.msg(f"\n|rLore table wiped: {wipe()} entries removed.|n")
        return False
