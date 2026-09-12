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

from dataclasses import dataclass, field

from .config import MANIFEST
from .log import ai_memory_log


@dataclass
class ImportPlan:
    """What an import would do, worked out without doing any of it."""

    entries: list = field(default_factory=list)
    create: list = field(default_factory=list)
    update: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    remove: list = field(default_factory=list)

    def __bool__(self):
        return True


@dataclass
class ImportReport:
    """What an import actually did, which a failed store can make differ."""

    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    failed: list = field(default_factory=list)


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
    from . import config

    parsed = _read(reader, MANIFEST, what="the manifest")
    if not isinstance(parsed, dict) or "sources" not in parsed:
        raise LoreImportError(
            f"{MANIFEST} must be a mapping with a `sources` list naming the "
            f"repository's content files. Check {config.reader_settings_hint()} "
            f"if you expected a different repository."
        )
    sources = parsed["sources"]
    if not isinstance(sources, list) or not sources:
        raise LoreImportError(
            f"{MANIFEST} names no sources. It must list the content files."
        )
    return [str(path) for path in sources]


def _read(reader, path, what):
    """Read one path, turning a reader's typed error into an import error.

    The reader's errors are precise but arrive without context: a consumer
    seeing "not found" needs to know which file, and which settings chose the
    repository it was looked for in.
    """
    from evennia_yaml_reader import (
        ReaderAuthError,
        ReaderNotFoundError,
        ReaderParseError,
    )

    from . import config

    try:
        return reader.read(path).parsed
    except ReaderAuthError as exc:
        raise LoreImportError(
            f"auth failed reading {path} — the token was rejected. "
            f"Check {config.reader_settings_hint()}. ({exc})"
        ) from exc
    except ReaderNotFoundError as exc:
        raise LoreImportError(
            f"{path} was not found ({what}). Check "
            f"{config.reader_settings_hint()}. ({exc})"
        ) from exc
    except ReaderParseError as exc:
        raise LoreImportError(f"{path} is not valid YAML: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - a reader may raise its own
        raise LoreImportError(f"reading {path} failed: {exc}") from exc


def load_entries(reader, paths):
    """Read and parse each path into entries, tagged with the source they came from.

    Raises:
        LoreImportError: if any named file is missing or malformed YAML.
    """
    loaded = []
    for path in paths:
        parsed = _read(reader, path, what="named by the manifest")
        if parsed is None:
            continue
        if not isinstance(parsed, dict):
            raise LoreImportError(f"{path} must be a mapping, not a list or scalar")
        source = parsed.get("source") or path
        for entry in parsed.get("entries") or []:
            loaded.append((path, source, entry))
    return loaded


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
    problems = []
    seen = set()

    for path, source, entry in entries:
        if not isinstance(entry, dict):
            problems.append(f"{path}: an entry is not a mapping")
            continue

        title = entry.get("title")
        where = f"{path}: {title!r}" if title else f"{path}: an untitled entry"

        if not title or not str(title).strip():
            problems.append(f"{path}: an entry has no title")
        if not entry.get("content") or not str(entry["content"]).strip():
            problems.append(f"{where} has no content")

        level = entry.get("scope_level")
        if not level or not isinstance(level, str) or not level.strip():
            # Shape, not vocabulary. Which words a game uses for its scopes is
            # the game's business; that there is one is the library's.
            problems.append(f"{where} has no scope_level")

        tags = entry.get("scope_tags", [])
        if not isinstance(tags, list):
            problems.append(f"{where} has scope_tags that are not a list")

        key = (source, title)
        if title and key in seen:
            problems.append(
                f"{where} appears twice under the same source — the two would "
                f"collide, since an entry is identified by its source and title"
            )
        seen.add(key)

    return problems


def plan_import(reader):
    """Work out what an import would change, without changing anything.

    Returns:
        A plan naming the entries to create, update, leave alone and remove.

    Raises:
        EmptyRepositoryError: if the read succeeded but resolved no entries.
        LoreValidationError: if any entry is malformed.
    """
    from .config import AI_MEMORY_ALIAS
    from .models import LoreMemory

    entries = load_entries(reader, discover(reader))

    if not entries:
        raise EmptyRepositoryError(
            "the repository was read successfully but holds no lore entries. "
            "Refusing, because applying that would remove every entry stored. "
            "If you mean to empty the lore table, use the wipe command, which "
            "asks first."
        )

    problems = validate(entries)
    if problems:
        raise LoreValidationError(problems)

    stored = {
        (row.source, row.title): row
        for row in LoreMemory.objects.using(AI_MEMORY_ALIAS).all()
    }

    plan = ImportPlan(entries=entries)
    claimed = set()

    for _, source, entry in entries:
        key = (source, entry["title"])
        claimed.add(key)
        row = stored.get(key)
        if row is None:
            plan.create.append(key)
        elif (
            row.content == entry["content"]
            and row.scope_level == entry["scope_level"]
            and row.scope_tags == list(entry.get("scope_tags") or [])
        ):
            plan.unchanged.append(key)
        else:
            plan.update.append(key)

    plan.remove = sorted(set(stored) - claimed)
    return plan


def apply_import(plan):
    """Carry out a plan — embed, upsert, and remove what the YAML no longer holds.

    Returns:
        A report of what actually happened, which may differ from the plan if
        a store failed and was dropped.
    """
    from . import services

    report = ImportReport(unchanged=list(plan.unchanged))

    for _, source, entry in plan.entries:
        key = (source, entry["title"])
        if key in plan.unchanged:
            continue
        _, status = services.store_lore(
            title=entry["title"],
            content=entry["content"],
            scope_level=entry["scope_level"],
            scope_tags=list(entry.get("scope_tags") or []),
            source=source,
        )
        if status == "created":
            report.created.append(key)
        elif status == "updated":
            report.updated.append(key)
        else:
            report.failed.append(key)

    report.removed = prune(
        {(source, entry["title"]) for _, source, entry in plan.entries}
    )
    return report


def prune(keep):
    """Remove every lore row whose ``(source, title)`` is not in ``keep``.

    A row nobody's YAML claims is stale by definition, whatever produced it —
    the repository is the source of truth, so the table mirrors it.

    Returns:
        The rows removed, so the report can name them rather than count them.
    """
    from .config import AI_MEMORY_ALIAS
    from .models import LoreMemory

    rows = LoreMemory.objects.using(AI_MEMORY_ALIAS)
    stale = [
        (row.source, row.title)
        for row in rows.all()
        if (row.source, row.title) not in keep
    ]
    for source, title in stale:
        rows.filter(source=source, title=title).delete()
    if stale:
        ai_memory_log(
            f"removed {len(stale)} lore entries the repository no longer holds: "
            + ", ".join(f"{source}:{title}" for source, title in stale)
        )
    return sorted(stale)


def wipe():
    """Remove every lore row.

    Safe because the table is derived data: the repository is the original, and
    an import restores it. Touches lore only — memories are a different table.

    Returns:
        The number of rows removed.
    """
    from .config import AI_MEMORY_ALIAS
    from .models import LoreMemory

    removed, _ = LoreMemory.objects.using(AI_MEMORY_ALIAS).all().delete()
    ai_memory_log(f"lore table wiped: {removed} entries removed", level="WARN")
    return removed
