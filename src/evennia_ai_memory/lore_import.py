# SPDX-License-Identifier: BSD-3-Clause
"""Bring the lore table into line with a repository of YAML.

The YAML is the source of truth. An entry added to it is created, one whose
content changed is updated and re-embedded, one that has not changed is left
alone, and one that is no longer there at all is removed. What the table holds
after a run is exactly what the repository held when it was read.

Two phases, with a decision between them:

1. :func:`plan_import` reads, validates, and works out what would change. It
   touches nothing. This runs off the reactor.
2. The result is reported to the operator, on the reactor thread.
3. :func:`apply_import` embeds, upserts and prunes. Off the reactor again.

A dry run is phase one on its own, which is why it needs no logic of its own.

Validation is all-or-nothing: one malformed entry anywhere refuses the whole
run, because a partial view of the repository cannot safely drive a prune.

Every case these functions must satisfy is in ``docs/test-plan.md`` under
``IM``.
"""

from .log import ai_memory_log


class LoreImportError(Exception):
    """The import cannot proceed. Carries what to tell the operator."""


class LoreValidationError(LoreImportError):
    """One or more entries are malformed. Nothing was written."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__(f"{len(self.problems)} problem(s) in the lore repository")


class EmptyRepositoryError(LoreImportError):
    """The read succeeded and resolved no entries.

    Refused rather than applied: with the table mirroring the YAML, an empty
    result would remove every row, and a mis-set path or a half-finished fetch
    looks exactly like a repository someone emptied on purpose. Emptying it
    deliberately is what the wipe command is for.
    """


#: The manifest at the root of a lore repository, naming its content files.
MANIFEST = "index.yaml"


def discover(reader):
    """Return the source paths the manifest names.

    A ``Reader`` reads a named path and cannot enumerate, so the repository
    declares its own contents. That is not merely a workaround: a manifest can
    tell a file that was deleted from one that never existed, which listing
    cannot, so a named-but-absent file stops the run instead of passing
    unnoticed.

    Raises:
        LoreImportError: if the manifest is missing, malformed, or names no
            sources.
    """
    raise NotImplementedError


def load_entries(reader, paths):
    """Read and parse each path into entries, tagged with the source they came from.

    Raises:
        LoreValidationError: if any file is malformed YAML.
    """
    raise NotImplementedError


def validate(entries):
    """Check every entry, and return every problem rather than the first.

    Shape, not vocabulary: an entry must carry a title, a content body, a
    non-empty ``scope_level`` string and a list of ``scope_tags``. Which
    strings those are is the consuming game's business — ``continental`` and
    ``faction`` are FCM's words, not this library's.

    Returns:
        A list of problems, each naming the source and the title. Empty when
        the repository is sound.
    """
    raise NotImplementedError


def plan_import(reader):
    """Work out what an import would change, without changing anything.

    Returns:
        A plan naming the entries to create, update, leave alone and remove.

    Raises:
        EmptyRepositoryError: if the read succeeded but resolved no entries.
        LoreValidationError: if any entry is malformed.
    """
    raise NotImplementedError


def apply_import(plan):
    """Carry out a plan — embed, upsert, and remove what the YAML no longer holds.

    Returns:
        A report of what actually happened, which may differ from the plan if
        a store failed and was dropped.
    """
    raise NotImplementedError


def prune(keep):
    """Remove every lore row whose ``(source, title)`` is not in ``keep``.

    A row nobody's YAML claims is stale by definition, whatever produced it.

    Returns:
        The rows removed, so the report can name them rather than count them.
    """
    raise NotImplementedError


def wipe():
    """Remove every lore row.

    Safe because the table is derived data: the YAML is the original, and an
    import restores it. Touches lore only — memories are a different table.

    Returns:
        The number of rows removed.
    """
    raise NotImplementedError
