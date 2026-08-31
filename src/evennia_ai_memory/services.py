# SPDX-License-Identifier: BSD-3-Clause
"""Store, search and retrieve NPC memories and world lore.

Every function here is synchronous. The consumer owns the dispatch — wrap these
in ``deferToThread`` or equivalent so they do not block a reactor.

Dual backend, detected from the engine on the library's own database alias:

- **PostgreSQL** — pgvector's cosine distance operator, HNSW-indexed.
- **SQLite** — numpy cosine similarity in a Python loop.

Reads and writes fail differently, deliberately. A write is dispatched with
nothing waiting on it, so a transient failure is retried before being logged and
dropped. A read has a player waiting, so it makes one attempt and reports that
it could not search — ``None`` means "could not search", ``[]`` means "searched,
found nothing".

Every case these functions must satisfy is in ``docs/test-plan.md``.
"""

from functools import lru_cache

from .db_router import DATABASE_ALIAS
from .log import ai_memory_log

#: Attempts made for a write before it is logged and dropped.
WRITE_ATTEMPTS = 3

#: Seconds between write attempts.
WRITE_RETRY_DELAY = 1.0


class EmbeddingError(Exception):
    """The embeddings endpoint did not return a usable vector."""


class TransientEmbeddingError(EmbeddingError):
    """A failure a retry could plausibly clear — timeout, 429, 5xx."""


class PermanentEmbeddingError(EmbeddingError):
    """A failure a retry cannot clear — bad key, malformed request."""


# ── Backend detection ────────────────────────────────────────────────


def _is_postgres() -> bool:
    """Return True if the library's database alias is PostgreSQL.

    Reads the resolved engine rather than the environment. ``DATABASE_URL``
    being set says a URL was supplied, not which database it names — a MySQL
    URL would take the pgvector path and fail. The engine is the exact answer.
    """
    from django.conf import settings

    from .db_router import DATABASE_ALIAS

    engine = settings.DATABASES.get(DATABASE_ALIAS, {}).get("ENGINE", "")
    return "postgresql" in engine


def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two vectors, 0.0 when either has no magnitude."""
    import numpy as np

    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    magnitude = np.linalg.norm(a) * np.linalg.norm(b)
    if magnitude < 1e-8:
        return 0.0
    return float(np.dot(a, b) / magnitude)


def _time_ago_str(dt) -> str:
    """Relative-time phrase for prompt context — "yesterday", "back in December".

    Deliberately vague at the coarse end. This goes into a prompt so an NPC can
    greet a returning player differently from a stranger, not so it can quote a
    date at them.
    """
    from django.utils import timezone

    seconds = (timezone.now() - dt).total_seconds()

    if seconds < 3600:
        return "a few minutes ago"
    if seconds < 86400:
        return "earlier today"
    if seconds < 172800:
        return "yesterday"
    if seconds < 604800:
        return "a few days ago"
    if seconds < 2592000:
        return "a couple of weeks ago"
    if seconds < 31536000:
        return f"back in {dt.strftime('%B')}"
    return "over a year ago"


# ── Scope ────────────────────────────────────────────────────────────


def _can_access_lore(entry_scope_tags, caller_scope_tags) -> bool:
    """Whether a caller holding ``caller_scope_tags`` may see this entry.

    Every tag the entry carries must be in the caller's list. An entry with no
    tags is visible to everyone.
    """
    if not entry_scope_tags:
        return True
    held = set(caller_scope_tags or ())
    return all(tag in held for tag in entry_scope_tags)


def _lore_scope_filter(caller_scope_tags):
    """Build the ``Q`` that admits exactly the entries the caller may see.

    On PostgreSQL ``contained_by`` *is* the access rule — the row's tags must
    all appear in the caller's list — so the filter is exact and the ranking
    only ever sees admissible rows.

    SQLite has no JSON containment lookup, so the filter there is permissive
    and ``_can_access_lore`` does the real work before ranking. That is the
    contract this function carries on both backends: **never restrictive**. It
    may admit rows the rule will reject, and the caller must apply the rule; it
    may never exclude a row the rule would admit.

    Filtering precedes ranking either way (D1). Post-filtering a ranked window
    lets inadmissible rows occupy every candidate slot and starve a result that
    qualifying rows would have filled.
    """
    from django.db.models import Q

    if _is_postgres():
        return Q(scope_tags__contained_by=list(caller_scope_tags or []))
    return Q()


# ── Memory ───────────────────────────────────────────────────────────


def _vector_fields(vector):
    """Split a vector across the two backend columns.

    pgvector takes the list; SQLite takes a float32 blob.
    """
    if _is_postgres():
        return {"embedding": None, "embedding_vector": vector}
    import numpy as np

    return {
        "embedding": np.asarray(vector, dtype=np.float32).tobytes(),
        "embedding_vector": None,
    }


def _blob_to_vector(blob):
    """Read a stored SQLite blob back, or None if it is the wrong width."""
    import numpy as np

    from .models import EMBEDDING_DIMENSIONS

    vector = np.frombuffer(bytes(blob), dtype=np.float32)
    if vector.shape != (EMBEDDING_DIMENSIONS,):
        return None
    return vector


def _memory_result(row, similarity=None):
    """One search or recency result. Both shapes match but for ``similarity``."""
    result = {
        "summary": row.summary,
        "interaction_type": row.interaction_type,
        "initiator": row.initiator,
        "created_at": row.created_at,
        "time_ago": _time_ago_str(row.created_at),
        "pc_name": row.pc_name,
    }
    if similarity is not None:
        result["similarity"] = similarity
    return result


def store_memory(
    npc_uuid,
    pc_uuid,
    pc_name,
    summary,
    interaction_type="say",
    initiator=None,
):
    """Embed and store one interaction between an NPC and a character.

    An event rather than a conversation: words exchanged, or a purchase, a
    theft, an attack. ``summary`` is what happened, written by the caller —
    the library phrases nothing, because only the consuming game knows how its
    own interactions read.

    Args:
        summary: what happened. Embedded, and returned by every search.
        interaction_type: the caller's own word for what kind of event it was.
        initiator: ``"pc"`` or ``"npc"``. Defaults to the character.

    Retries a transient failure, then logs the cause and drops the event. Never
    raises into the caller, and never writes a row with no vector — a row no
    search can return is not a stored memory.
    """
    import time

    from .models import EMBEDDING_DIMENSIONS, INITIATOR_PC, INITIATORS, NpcMemory

    initiator = INITIATOR_PC if initiator is None else initiator
    if initiator not in INITIATORS:
        raise ValueError(
            f"initiator must be one of {INITIATORS}, not {initiator!r}. It has "
            f"two possible values, so an unrecognised one is a mistake rather "
            f"than a new kind of event."
        )
    if not summary or not str(summary).strip():
        raise ValueError(
            "summary is empty — there would be nothing to embed and nothing "
            "for a search to return."
        )
    if not interaction_type or not str(interaction_type).strip():
        raise ValueError("interaction_type is empty")

    vector = _embed(summary, attempts=WRITE_ATTEMPTS)
    if vector is None:
        return  # already logged by _embed
    if len(vector) != EMBEDDING_DIMENSIONS:
        ai_memory_log(
            f"embedder returned {len(vector)} dimensions, expected "
            f"{EMBEDDING_DIMENSIONS} — dropping the exchange rather than storing "
            f"a row no search can return. Check the configured model.",
            level="ERROR",
        )
        return

    for attempt in range(1, WRITE_ATTEMPTS + 1):
        try:
            NpcMemory.objects.using(DATABASE_ALIAS).create(
                npc_uuid=npc_uuid,
                pc_uuid=pc_uuid,
                pc_name=pc_name,
                summary=summary,
                interaction_type=interaction_type,
                initiator=initiator,
                **_vector_fields(vector),
            )
            return
        except Exception as exc:  # noqa: BLE001 - a write must not reach the caller
            ai_memory_log(
                f"storing a memory failed, attempt {attempt} of "
                f"{WRITE_ATTEMPTS}: {exc}",
                level="WARN",
            )
            if attempt < WRITE_ATTEMPTS:
                time.sleep(WRITE_RETRY_DELAY)

    ai_memory_log(
        "storing a memory failed on every attempt; the exchange is lost.",
        level="ERROR",
        trace=True,
    )


def _pair(npc_uuid, pc_uuid):
    """The rows belonging to one NPC-and-character pair, and nothing else."""
    from .models import NpcMemory

    return NpcMemory.objects.using(DATABASE_ALIAS).filter(
        npc_uuid=npc_uuid, pc_uuid=pc_uuid
    )


def search_memories(npc_uuid, pc_uuid, query_text, top_k=5):
    """Return this pair's memories most similar to ``query_text``.

    Returns:
        A list of results, most similar first; ``[]`` when nothing matched;
        ``None`` when the query could not be embedded and no search ran.
    """
    query = _embed(query_text)
    if query is None:
        ai_memory_log(
            "a memory search could not embed its query, so no search ran. "
            "Reporting that rather than substituting something else.",
            level="WARN",
        )
        return None

    rows = _pair(npc_uuid, pc_uuid)

    if _is_postgres():
        from pgvector.django import CosineDistance

        ranked = (
            rows.filter(embedding_vector__isnull=False)
            .annotate(distance=CosineDistance("embedding_vector", query))
            .order_by("distance", "created_at")[:top_k]
        )
        return [_memory_result(row, 1.0 - row.distance) for row in ranked]

    scored = []
    for row in rows.order_by("created_at").iterator():
        if not row.embedding:
            continue
        vector = _blob_to_vector(row.embedding)
        if vector is None:
            continue
        scored.append((_cosine_similarity(query, vector), row))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_memory_result(row, score) for score, row in scored[:top_k]]


def get_recent_memories(npc_uuid, pc_uuid, limit=10):
    """Return this pair's most recent exchanges, oldest first.

    Embeds nothing, so it cannot fail the way a search can. Newest ``limit``
    rows are selected, then reversed — a prompt reads better in the order the
    conversation happened.
    """
    newest = _pair(npc_uuid, pc_uuid).order_by("-created_at")[:limit]
    return [_memory_result(row) for row in reversed(list(newest))]


def get_last_interaction_time(npc_uuid, pc_uuid):
    """Return when this pair last spoke.

    Returns:
        ``(datetime, phrase)`` for the most recent exchange, or
        ``(None, None)`` when there is no history.
    """
    last = _pair(npc_uuid, pc_uuid).order_by("-created_at").first()
    if last is None:
        return None, None
    return last.created_at, _time_ago_str(last.created_at)


# ── Lore ─────────────────────────────────────────────────────────────


def store_lore(title, content, scope_level, scope_tags, source=""):
    """Store or update one lore entry, keyed on ``(source, title)``.

    Idempotent. Unchanged content is left alone and embeds nothing; changed
    content is re-embedded. A re-embed that fails leaves the stored vector in
    place rather than replacing a working one with nothing.

    Returns:
        ``(entry, status)`` where status is ``"created"``, ``"updated"``,
        ``"unchanged"`` or ``"failed"``.
    """
    import time

    from .models import EMBEDDING_DIMENSIONS, LoreMemory

    rows = LoreMemory.objects.using(DATABASE_ALIAS)
    existing = rows.filter(source=source, title=title).first()

    if (
        existing is not None
        and existing.content == content
        and existing.scope_level == scope_level
        and existing.scope_tags == list(scope_tags)
    ):
        return existing, "unchanged"

    vector = _embed(content, attempts=WRITE_ATTEMPTS)
    if vector is None or len(vector) != EMBEDDING_DIMENSIONS:
        if vector is not None:
            ai_memory_log(
                f"embedder returned {len(vector)} dimensions, expected "
                f"{EMBEDDING_DIMENSIONS} — leaving {title!r} as it was.",
                level="ERROR",
            )
        # An entry that already exists keeps the vector it has. Replacing a
        # working one with nothing would make the entry unsearchable, which is
        # worse than leaving it a revision behind.
        return existing, "failed"

    fields = {
        "content": content,
        "scope_level": scope_level,
        "scope_tags": list(scope_tags),
        **_vector_fields(vector),
    }

    for attempt in range(1, WRITE_ATTEMPTS + 1):
        try:
            if existing is not None:
                for name, value in fields.items():
                    setattr(existing, name, value)
                existing.save(using=DATABASE_ALIAS)
                return existing, "updated"
            entry = rows.create(title=title, source=source, **fields)
            return entry, "created"
        except Exception as exc:  # noqa: BLE001 - an import must not be halted by one row
            ai_memory_log(
                f"storing lore {title!r} failed, attempt {attempt} of "
                f"{WRITE_ATTEMPTS}: {exc}",
                level="WARN",
            )
            if attempt < WRITE_ATTEMPTS:
                time.sleep(WRITE_RETRY_DELAY)

    ai_memory_log(
        f"storing lore {title!r} failed on every attempt.",
        level="ERROR",
        trace=True,
    )
    return existing, "failed"


def search_lore(query_text, scope_tags, top_k=3):
    """Return the lore entries ``scope_tags`` admits, most similar first.

    Args:
        query_text: what to search for.
        scope_tags: the tags this caller holds. An entry is admitted only when
            every tag it carries is in this list.
        top_k: how many to return.

    Returns:
        A list of results, most similar first; ``[]`` when nothing matched;
        ``None`` when the query could not be embedded and no search ran.
    """
    from .models import LoreMemory

    query = _embed(query_text)
    if query is None:
        ai_memory_log(
            "a lore search could not embed its query, so no search ran. "
            "Reporting that rather than substituting something else.",
            level="WARN",
        )
        return None

    admitted = LoreMemory.objects.using(DATABASE_ALIAS).filter(
        _lore_scope_filter(scope_tags)
    )

    if _is_postgres():
        from pgvector.django import CosineDistance

        ranked = (
            admitted.filter(embedding_vector__isnull=False)
            .annotate(distance=CosineDistance("embedding_vector", query))
            .order_by("distance", "title")[:top_k]
        )
        return [_lore_result(row, 1.0 - row.distance) for row in ranked]

    scored = []
    for row in admitted.order_by("title").iterator():
        # The SQLite filter is permissive, so the rule is applied here — and
        # before scoring, so an inadmissible row can never displace an
        # admissible one from the result.
        if not _can_access_lore(row.scope_tags, scope_tags):
            continue
        if not row.embedding:
            continue
        vector = _blob_to_vector(row.embedding)
        if vector is None:
            continue
        scored.append((_cosine_similarity(query, vector), row))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_lore_result(row, score) for score, row in scored[:top_k]]


def _lore_result(row, similarity):
    """One lore search result."""
    return {
        "title": row.title,
        "content": row.content,
        "scope_level": row.scope_level,
        "similarity": similarity,
    }


# ── Embedding ────────────────────────────────────────────────────────


def _build_client(*, base_url, api_key):
    """Construct the embeddings client for the configured endpoint."""
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key)


@lru_cache(maxsize=1)
def _embedding_client():
    """The process-wide embeddings client, built from the configured settings."""
    from . import config

    return _build_client(
        base_url=config.get_embedding_base_url(),
        api_key=config.get_embedding_api_key(),
    )


def _permanent_error_types():
    """Provider exceptions a retry cannot clear.

    A rejected key or a malformed request fails identically however many times
    it is sent. Everything else — timeouts, dropped connections, 429s, 5xx —
    is treated as transient, including exceptions this list does not name: an
    unclassified fault is more often a transport hiccup than a permanent one,
    and the cost of being wrong is a couple of seconds.
    """
    import openai

    return (
        openai.AuthenticationError,
        openai.PermissionDeniedError,
        openai.BadRequestError,
        openai.NotFoundError,
        openai.UnprocessableEntityError,
    )


def _embed_once(text):
    """One embeddings call, with no retry.

    Raises:
        PermanentEmbeddingError: on a failure a retry cannot clear.
        Exception: anything else, which the caller may retry.
    """
    from . import config

    try:
        response = _embedding_client().embeddings.create(
            model=config.get_embedding_model(), input=text
        )
    except _permanent_error_types() as exc:
        raise PermanentEmbeddingError(str(exc)) from exc
    return response.data[0].embedding


def _embed(text, attempts=1):
    """Turn text into a vector, retrying a transient failure.

    ``attempts`` is 1 on a read — a player is waiting on it — and
    ``WRITE_ATTEMPTS`` on a write, which nothing is waiting on. A permanent
    failure is never retried whichever it is.

    Returns:
        The vector, or None if it could not be obtained.
    """
    import time

    for attempt in range(1, attempts + 1):
        try:
            return _embed_once(text)
        except PermanentEmbeddingError as exc:
            ai_memory_log(
                f"embedding refused and not retryable: {exc}. This is a "
                f"configuration fault rather than an outage — check the "
                f"endpoint, key and model.",
                level="ERROR",
                trace=True,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - classified above; retry the rest
            last = exc
            ai_memory_log(
                f"embedding attempt {attempt} of {attempts} failed: {exc}",
                level="WARN",
            )
            if attempt < attempts:
                time.sleep(WRITE_RETRY_DELAY)

    ai_memory_log(
        f"embedding failed after {attempts} attempt(s), giving up: {last}",
        level="ERROR",
        trace=True,
    )
    return None
