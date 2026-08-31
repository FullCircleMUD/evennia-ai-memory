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

    The rule is expressed in SQL so filtering happens before ranking — D1. The
    Python rule and this filter must agree; SC-12 asserts it.
    """
    raise NotImplementedError


# ── Memory ───────────────────────────────────────────────────────────


def store_memory(
    npc_uuid,
    speaker_uuid,
    speaker_name,
    user_msg,
    assistant_msg,
    interaction_type="say",
):
    """Embed and store one conversational exchange.

    Retries a transient failure, then logs the cause and drops the exchange.
    Never raises into the caller, and never writes a row with no vector — a row
    that cannot be returned by a search is not a stored memory.
    """
    raise NotImplementedError


def search_memories(npc_uuid, speaker_uuid, query_text, top_k=5):
    """Return the memories of this pair most similar to ``query_text``.

    Returns:
        A list of results, most similar first; ``[]`` when nothing matched;
        ``None`` when the query could not be embedded and no search ran.
    """
    raise NotImplementedError


def get_recent_memories(npc_uuid, speaker_uuid, limit=10):
    """Return this pair's most recent exchanges, oldest first.

    Embeds nothing, so it cannot fail the way a search can.
    """
    raise NotImplementedError


def get_last_interaction_time(npc_uuid, speaker_uuid):
    """Return when this pair last spoke.

    Returns:
        ``(datetime, phrase)`` for the most recent exchange, or
        ``(None, None)`` when there is no history.
    """
    raise NotImplementedError


# ── Lore ─────────────────────────────────────────────────────────────


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
    raise NotImplementedError


# ── Embedding ────────────────────────────────────────────────────────


def _build_client(*, base_url, api_key):
    """Construct the embeddings client for the configured endpoint."""
    raise NotImplementedError


@lru_cache(maxsize=1)
def _embedding_client():
    """The process-wide embeddings client, built from the configured settings."""
    raise NotImplementedError


def _embed_once(text):
    """One embeddings call, with no retry.

    Raises:
        TransientEmbeddingError: on a failure a retry could clear.
        PermanentEmbeddingError: on one it could not.
    """
    raise NotImplementedError


def _embed(text, attempts=1):
    """Turn text into a vector, retrying a transient failure ``attempts`` times.

    ``attempts`` is 1 on a read — a player is waiting — and ``WRITE_ATTEMPTS``
    on a write. A permanent failure is never retried.

    Returns:
        The vector, or None if it could not be obtained.
    """
    raise NotImplementedError
