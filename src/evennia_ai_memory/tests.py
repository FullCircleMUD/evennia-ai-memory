# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-ai-memory, run via ``python runtests.py``.

Every test here covers a case in ``docs/test-plan.md`` and is named for it. The
plan's **Test function** column names these back, and the library-standards
linter checks the mapping in both directions — a test no case claims, or a case
naming a test that does not exist, is an error.
"""

import os
import unittest
import uuid
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone

import evennia_ai_memory
from evennia_ai_memory import config, services
from evennia_ai_memory.db_router import AiMemoryRouter
from evennia_ai_memory.models import EMBEDDING_DIMENSIONS, LoreMemory, NpcMemory

# ── Fixtures ─────────────────────────────────────────────────────────

ALIAS = "ai_memory"

_PG = "postgresql" in settings.DATABASES.get(ALIAS, {}).get("ENGINE", "")
needs_postgres = unittest.skipUnless(_PG, "requires a PostgreSQL test database")


def vec(index, dims=EMBEDDING_DIMENSIONS):
    """A unit vector along one axis — two different indices are orthogonal."""
    v = [0.0] * dims
    v[index % dims] = 1.0
    return v


class StubEmbedder:
    """Deterministic ``text -> vector``; the same text always gives the same one."""

    def __init__(self, dims=EMBEDDING_DIMENSIONS):
        self.dims = dims

    def __call__(self, text, *args, **kwargs):
        return vec(abs(hash(text)) % self.dims, self.dims)


class OrthogonalEmbedder:
    """Maps a fixed vocabulary to orthogonal axes, so ranking is predictable."""

    def __init__(self, vocabulary):
        self.vocabulary = {word: i for i, word in enumerate(vocabulary)}

    def __call__(self, text, *args, **kwargs):
        for word, index in self.vocabulary.items():
            if word in text:
                return vec(index)
        return vec(len(self.vocabulary))


class RaisingEmbedder:
    """Raises on every call."""

    def __init__(self, exc=None):
        self.exc = exc or RuntimeError("embedding service unreachable")
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class FlakyEmbedder:
    """Fails a set number of times, then succeeds."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def __call__(self, text, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient")
        return vec(1)


class ShortEmbedder:
    """Returns a vector of the wrong dimension."""

    def __call__(self, *args, **kwargs):
        return [0.1] * 8


class CountingEmbedder:
    """Records every call for "was it called / how often" assertions."""

    def __init__(self):
        self.texts = []

    def __call__(self, text, *args, **kwargs):
        self.texts.append(text)
        return vec(len(self.texts))


def patch_embedder(embedder):
    """Supply vectors, bypassing the provider and the retry logic.

    For tests that need an embedding to exist. To exercise a *failure*, patch
    the provider call instead — see ``patch_provider``. Patching this with
    something that raises would bypass the handler under test.
    """
    return mock.patch.object(services, "_embed", side_effect=embedder)


def patch_provider(embedder):
    """Replace the raw provider call, leaving the retry and logging in place."""
    return mock.patch.object(services, "_embed_once", side_effect=embedder)


def make_memory(npc_uuid=None, speaker_uuid=None, **kwargs):
    """Build an ``NpcMemory`` row directly, bypassing ``store_memory``."""
    fields = {
        "npc_uuid": npc_uuid or uuid.uuid4(),
        "speaker_uuid": speaker_uuid or uuid.uuid4(),
        "speaker_name": "Bob",
        "user_message": "did you sell my brother a sword?",
        "assistant_message": "Aye, a fine one.",
        "summary": "Bob said: ... | You replied: ...",
        "interaction_type": "say",
    }
    fields.update(kwargs)
    return NpcMemory.objects.using(ALIAS).create(**fields)


def make_lore(**kwargs):
    """Build a ``LoreMemory`` row directly."""
    fields = {
        "title": "Founding of Millholm",
        "content": "Millholm was founded four hundred years ago.",
        "scope_level": "regional",
        "scope_tags": [],
        "source": "millholm/regional.yaml",
    }
    fields.update(kwargs)
    return LoreMemory.objects.using(ALIAS).create(**fields)


def aged(row, delta):
    """Force a row's timestamps past ``auto_now_add`` to a chosen age."""
    when = timezone.now() - delta
    type(row).objects.using(ALIAS).filter(pk=row.pk).update(created_at=when)
    if hasattr(row, "updated_at"):
        type(row).objects.using(ALIAS).filter(pk=row.pk).update(updated_at=when)
    row.refresh_from_db(using=ALIAS)
    return row


def library_source():
    """Every line of the library's own source, for static assertions."""
    import pathlib

    root = pathlib.Path(evennia_ai_memory.__file__).parent
    out = {}
    for path in root.rglob("*.py"):
        if path.name == "tests.py" or "migrations" in path.parts:
            continue
        out[path.name] = path.read_text()
    return out


class MemoryTestCase(TestCase):
    """Base for tests that touch the library's tables."""

    databases = {"default", ALIAS}

    def setUp(self):
        self.npc = uuid.uuid4()
        self.speaker = uuid.uuid4()
        self.other = uuid.uuid4()


# ── EM — embedding ───────────────────────────────────────────────────


class EmbeddingTests(MemoryTestCase):
    def test_em_01_embeds_the_documented_text(self):
        counting = CountingEmbedder()
        with patch_embedder(counting):
            services.store_memory(
                self.npc, self.speaker, "Bob", "hello there", "well met"
            )
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertEqual(counting.texts, [row.summary])

    def test_em_02_transient_write_failure_is_retried_then_dropped(self):
        flaky = FlakyEmbedder(failures=services.WRITE_ATTEMPTS)
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with mock.patch.object(services, "_embed_once", side_effect=flaky):
                services.store_memory(
                    self.npc, self.speaker, "Bob", "hello", "hi"
                )
        self.assertEqual(flaky.calls, services.WRITE_ATTEMPTS)
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_em_03_permanent_write_failure_is_not_retried(self):
        raising = RaisingEmbedder(services.PermanentEmbeddingError("bad key"))
        with mock.patch.object(services, "_embed_once", side_effect=raising):
            services.store_memory(self.npc, self.speaker, "Bob", "hello", "hi")
        self.assertEqual(raising.calls, 1)

    def test_em_06_embeds_once_per_row(self):
        counting = CountingEmbedder()
        with patch_embedder(counting):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertEqual(len(counting.texts), 1)

    def test_em_07_wrong_length_vector_is_refused(self):
        with patch_embedder(ShortEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_em_08_no_rate_limiter_or_cost_tracking_in_source(self):
        banned = ("rate_limit", "ratelimit", "cost_cents", "cost_track", "daily_cap")
        for name, source in library_source().items():
            for token in banned:
                self.assertNotIn(token, source.lower(), f"{token} in {name}")

    def test_em_17_permanent_error_types_exist_in_the_installed_sdk(self):
        types = services._permanent_error_types()
        self.assertTrue(types)
        for exc_type in types:
            self.assertTrue(issubclass(exc_type, Exception), exc_type)

    def test_em_09_read_failure_is_not_retried(self):
        raising = RaisingEmbedder()
        with mock.patch.object(services, "_embed_once", side_effect=raising):
            result = services.search_memories(self.npc, self.speaker, "anything")
        self.assertIsNone(result)
        self.assertEqual(raising.calls, 1)


class EmbeddingConfigTests(TestCase):
    databases = {"default", ALIAS}

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY=None)
    def test_em_04_missing_api_key_raises_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            config.validate_settings()

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY=None)
    def test_em_05_error_names_the_setting_and_where_to_put_it(self):
        with self.assertRaises(ImproperlyConfigured) as caught:
            config.validate_settings()
        message = str(caught.exception)
        self.assertIn(config.SETTING_API_KEY, message)
        self.assertIn(config.KEY_LOCATION_HINT, message)

    @override_settings(AI_MEMORY_EMBEDDING_BASE_URL=None)
    def test_em_10_missing_base_url_raises_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            config.validate_settings()

    @override_settings(AI_MEMORY_EMBEDDING_MODEL=None)
    def test_em_11_missing_model_raises_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            config.validate_settings()

    def test_em_12_settings_are_read_only_through_config(self):
        for name, source in library_source().items():
            if name == "config.py":
                continue
            self.assertNotIn("settings.AI_MEMORY", source, f"direct read in {name}")

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY="")
    def test_em_13_empty_setting_counts_as_missing(self):
        with self.assertRaises(ImproperlyConfigured):
            config.validate_settings()

    def test_em_14_configured_base_url_builds_the_client(self):
        with mock.patch.object(services, "_build_client") as build:
            services._embedding_client.cache_clear()
            services._embedding_client()
        _, kwargs = build.call_args
        self.assertEqual(kwargs["base_url"], config.get_embedding_base_url())

    def test_em_15_reads_its_own_settings_namespace(self):
        for name, source in library_source().items():
            self.assertNotIn("LLM_EMBEDDING", source, f"foreign setting in {name}")

    def test_em_16_no_provider_defaults_in_source(self):
        for name, source in library_source().items():
            self.assertNotIn("https://", source, f"endpoint literal in {name}")
            self.assertNotIn("text-embedding", source, f"model literal in {name}")


# ── SM — store_memory ────────────────────────────────────────────────


class StoreMemoryTests(MemoryTestCase):
    def store(self, **kwargs):
        fields = {
            "npc_uuid": self.npc,
            "speaker_uuid": self.speaker,
            "speaker_name": "Bob",
            "user_msg": "did you sell my brother a sword?",
            "assistant_msg": "Aye, a fine one.",
        }
        fields.update(kwargs)
        with patch_embedder(StubEmbedder()):
            return services.store_memory(**fields)

    def test_sm_01_stored_exchange_is_retrievable(self):
        self.store()
        results = services.get_recent_memories(self.npc, self.speaker)
        self.assertEqual(len(results), 1)

    def test_sm_02_row_records_uuids_name_messages_and_type(self):
        self.store(interaction_type="whisper")
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertEqual(row.npc_uuid, self.npc)
        self.assertEqual(row.speaker_uuid, self.speaker)
        self.assertEqual(row.speaker_name, "Bob")
        self.assertEqual(row.user_message, "did you sell my brother a sword?")
        self.assertEqual(row.assistant_message, "Aye, a fine one.")
        self.assertEqual(row.interaction_type, "whisper")

    def test_sm_03_summary_uses_second_person_for_the_npc(self):
        self.store()
        summary = NpcMemory.objects.using(ALIAS).get().summary
        self.assertIn("Bob", summary)
        self.assertIn("You replied", summary)

    def test_sm_04_sqlite_stores_a_float32_blob(self):
        if _PG:
            self.skipTest("SQLite path")
        self.store()
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertIsNotNone(row.embedding)
        self.assertEqual(len(bytes(row.embedding)), EMBEDDING_DIMENSIONS * 4)

    @needs_postgres
    def test_sm_05_postgres_stores_the_vector_column(self):
        self.store()
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertIsNotNone(row.embedding_vector)
        self.assertIsNone(row.embedding)

    def test_sm_06_blob_round_trips(self):
        import numpy as np

        expected = vec(7)
        with patch_embedder(lambda text, *a, **k: expected):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        row = NpcMemory.objects.using(ALIAS).get()
        stored = np.frombuffer(bytes(row.embedding), dtype=np.float32).tolist()
        self.assertEqual(stored, expected)

    def test_sm_07_embedding_failure_does_not_raise_into_the_caller(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                services.store_memory(self.npc, self.speaker, "Bob", "a", "b")

    def test_sm_08_transient_write_failure_is_retried_then_dropped(self):
        with patch_embedder(StubEmbedder()):
            with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
                with mock.patch.object(
                    NpcMemory.objects, "using", side_effect=RuntimeError("db down")
                ):
                    services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_sm_09_never_writes_a_row_without_a_vector(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_sm_10_empty_messages_still_store(self):
        self.store(user_msg="", assistant_msg="")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 1)

    def test_sm_11_identical_exchanges_are_not_deduplicated(self):
        self.store()
        self.store()
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 2)

    def test_sm_12_created_at_is_set_and_aware(self):
        self.store()
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertIsNotNone(row.created_at)
        self.assertIsNotNone(row.created_at.tzinfo)

    def test_sm_13_row_lands_on_the_library_alias(self):
        from django.db import OperationalError

        self.store()
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 1)
        # Not "zero rows on default" — the router keeps the table off that
        # database entirely, so asking for it there is an error, which is the
        # stronger evidence.
        with self.assertRaises(OperationalError):
            NpcMemory.objects.using("default").count()

    def test_sm_14_no_npc_name_is_stored(self):
        self.assertNotIn(
            "npc_name", [f.name for f in NpcMemory._meta.get_fields()]
        )


# ── MS — search_memories ─────────────────────────────────────────────


class SearchMemoriesTests(MemoryTestCase):
    def setUp(self):
        super().setUp()
        self.embedder = OrthogonalEmbedder(["sword", "bread", "weather"])

    def seed(self, count=3, **kwargs):
        rows = []
        for i, word in enumerate(["sword", "bread", "weather"][:count]):
            rows.append(
                make_memory(
                    npc_uuid=kwargs.get("npc_uuid", self.npc),
                    speaker_uuid=kwargs.get("speaker_uuid", self.speaker),
                    summary=f"talk about {word}",
                    embedding=self._blob(vec(i)),
                )
            )
        return rows

    @staticmethod
    def _blob(vector):
        import numpy as np

        return np.asarray(vector, dtype="float32").tobytes()

    def search(self, text="sword", **kwargs):
        with patch_embedder(self.embedder):
            return services.search_memories(
                kwargs.get("npc_uuid", self.npc),
                kwargs.get("speaker_uuid", self.speaker),
                text,
                **{k: v for k, v in kwargs.items() if k == "top_k"},
            )

    def test_ms_01_nearest_memories_come_first(self):
        self.seed()
        results = self.search("sword")
        self.assertIn("sword", results[0]["summary"])

    def test_ms_02_returns_at_most_top_k(self):
        self.seed()
        self.assertEqual(len(self.search(top_k=2)), 2)

    def test_ms_03_fewer_matches_than_top_k_returns_all(self):
        self.seed(count=1)
        self.assertEqual(len(self.search(top_k=5)), 1)

    def test_ms_04_no_memories_returns_empty_list(self):
        self.assertEqual(self.search(), [])

    def test_ms_05_result_carries_the_documented_keys(self):
        self.seed(count=1)
        result = self.search()[0]
        for key in (
            "summary",
            "user_message",
            "assistant_message",
            "similarity",
            "created_at",
            "speaker_name",
        ):
            self.assertIn(key, result)

    def test_ms_06_both_uuids_are_required(self):
        with self.assertRaises(TypeError):
            services.search_memories(self.npc, query_text="sword")

    def test_ms_07_rows_without_an_embedding_are_skipped(self):
        make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker, embedding=None)
        self.assertEqual(self.search(), [])

    def test_ms_08_wrong_dimension_row_is_skipped_not_raised(self):
        make_memory(
            npc_uuid=self.npc,
            speaker_uuid=self.speaker,
            embedding=self._blob([0.1] * 8),
        )
        self.assertEqual(self.search(), [])

    def test_ms_09_similarity_is_bounded_and_exact_for_a_match(self):
        self.seed(count=1)
        result = self.search("sword")[0]
        self.assertGreaterEqual(result["similarity"], -1.0)
        self.assertLessEqual(result["similarity"], 1.0)
        self.assertAlmostEqual(result["similarity"], 1.0, places=5)

    def test_ms_10_another_npcs_memories_are_excluded(self):
        self.seed(count=1, npc_uuid=self.other)
        self.assertEqual(self.search(), [])

    def test_ms_11_uuid_matches_exactly_with_no_name_fallback(self):
        self.seed(count=1)
        self.assertEqual(self.search(npc_uuid=uuid.uuid4()), [])

    def test_ms_14_failed_embedding_returns_none_not_empty(self):
        self.seed()
        with mock.patch.object(services, "_embed", return_value=None):
            self.assertIsNone(
                services.search_memories(self.npc, self.speaker, "sword")
            )

    def test_ms_15_top_k_zero_returns_empty_list(self):
        self.seed()
        self.assertEqual(self.search(top_k=0), [])

    @needs_postgres
    def test_ms_16_backends_agree_on_ordering(self):
        self.seed()
        self.assertIn("sword", self.search("sword")[0]["summary"])

    def test_ms_17_ties_are_ordered_deterministically(self):
        same = vec(0)
        for _ in range(3):
            make_memory(
                npc_uuid=self.npc,
                speaker_uuid=self.speaker,
                embedding=self._blob(same),
            )
        first = [r["created_at"] for r in self.search()]
        second = [r["created_at"] for r in self.search()]
        self.assertEqual(first, second)


# ── MR — get_recent_memories ─────────────────────────────────────────


class RecentMemoriesTests(MemoryTestCase):
    def seed(self, count=3, **kwargs):
        rows = []
        for i in range(count):
            row = make_memory(
                npc_uuid=kwargs.get("npc_uuid", self.npc),
                speaker_uuid=kwargs.get("speaker_uuid", self.speaker),
                summary=f"exchange {i}",
            )
            rows.append(aged(row, timedelta(hours=count - i)))
        return rows

    def test_mr_01_returns_the_most_recent_limit(self):
        self.seed(count=5)
        self.assertEqual(len(services.get_recent_memories(self.npc, self.speaker, 2)), 2)

    def test_mr_02_selects_newest_then_orders_oldest_first(self):
        self.seed(count=3)
        results = services.get_recent_memories(self.npc, self.speaker, 2)
        self.assertEqual(
            [r["summary"] for r in results], ["exchange 1", "exchange 2"]
        )

    def test_mr_03_no_memories_returns_empty_list(self):
        self.assertEqual(services.get_recent_memories(self.npc, self.speaker), [])

    def test_mr_04_results_carry_no_similarity(self):
        self.seed(count=1)
        result = services.get_recent_memories(self.npc, self.speaker)[0]
        self.assertNotIn("similarity", result)

    def test_mr_05_embeds_nothing(self):
        self.seed(count=1)
        raising = RaisingEmbedder()
        with mock.patch.object(services, "_embed", side_effect=raising):
            services.get_recent_memories(self.npc, self.speaker)
        self.assertEqual(raising.calls, 0)

    def test_mr_06_both_uuids_are_required_and_exact(self):
        self.seed(count=1)
        self.assertEqual(
            services.get_recent_memories(uuid.uuid4(), self.speaker), []
        )

    def test_mr_07_another_speaker_is_excluded(self):
        self.seed(count=1, speaker_uuid=self.other)
        self.assertEqual(services.get_recent_memories(self.npc, self.speaker), [])


# ── LI — get_last_interaction_time ───────────────────────────────────


class LastInteractionTests(MemoryTestCase):
    def test_li_01_returns_the_most_recent_timestamp(self):
        old = aged(make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker), timedelta(days=5))
        new = aged(make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker), timedelta(hours=1))
        when, _ = services.get_last_interaction_time(self.npc, self.speaker)
        self.assertEqual(when.replace(microsecond=0), new.created_at.replace(microsecond=0))
        self.assertNotEqual(when.replace(microsecond=0), old.created_at.replace(microsecond=0))

    def test_li_02_no_history_returns_the_empty_result(self):
        self.assertEqual(
            services.get_last_interaction_time(self.npc, self.speaker), (None, None)
        )

    def test_li_03_another_speaker_does_not_satisfy_the_query(self):
        make_memory(npc_uuid=self.npc, speaker_uuid=self.other)
        self.assertEqual(
            services.get_last_interaction_time(self.npc, self.speaker), (None, None)
        )

    def test_li_04_both_uuids_must_match_with_no_name_fallback(self):
        make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker, speaker_name="Bob")
        self.assertEqual(
            services.get_last_interaction_time(uuid.uuid4(), self.speaker),
            (None, None),
        )

    def test_li_05_returns_a_timestamp_and_a_phrase(self):
        aged(make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker), timedelta(days=2))
        when, phrase = services.get_last_interaction_time(self.npc, self.speaker)
        self.assertIsNotNone(when)
        self.assertIsInstance(phrase, str)
        self.assertTrue(phrase)

    def test_li_06_returned_datetime_is_aware(self):
        make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker)
        when, _ = services.get_last_interaction_time(self.npc, self.speaker)
        self.assertIsNotNone(when.tzinfo)

    def test_li_07_each_relative_time_band_is_produced(self):
        now = timezone.now()
        bands = [
            timedelta(minutes=5),
            timedelta(hours=6),
            timedelta(days=1, hours=6),
            timedelta(days=4),
            timedelta(days=20),
            timedelta(days=120),
        ]
        phrases = [services._time_ago_str(now - delta) for delta in bands]
        self.assertEqual(len(set(phrases)), len(phrases))

    def test_li_08_beyond_a_year_does_not_fall_back_to_a_month(self):
        long_ago = timezone.now() - timedelta(days=500)
        phrase = services._time_ago_str(long_ago)
        self.assertIn("year", phrase)


# ── LS — search_lore ─────────────────────────────────────────────────


class SearchLoreTests(MemoryTestCase):
    def setUp(self):
        super().setUp()
        self.embedder = OrthogonalEmbedder(["war", "bread", "ley"])

    @staticmethod
    def _blob(vector):
        import numpy as np

        return np.asarray(vector, dtype="float32").tobytes()

    def seed(self):
        make_lore(title="The Great War", scope_tags=[], embedding=self._blob(vec(0)))
        make_lore(title="Bread Prices", scope_tags=["millholm"], embedding=self._blob(vec(1)))
        make_lore(
            title="Ley Lines",
            scope_tags=["millholm", "mages_guild"],
            embedding=self._blob(vec(2)),
        )

    def search(self, text="war", tags=None, **kwargs):
        with patch_embedder(self.embedder):
            return services.search_lore(text, tags if tags is not None else [], **kwargs)

    def test_ls_01_nearest_admitted_entries_come_first(self):
        self.seed()
        self.assertEqual(self.search("war")[0]["title"], "The Great War")

    def test_ls_02_returns_at_most_top_k(self):
        self.seed()
        self.assertLessEqual(len(self.search(tags=["millholm"], top_k=1)), 1)

    def test_ls_03_result_carries_the_documented_keys(self):
        self.seed()
        result = self.search("war")[0]
        for key in ("title", "content", "scope_level", "similarity"):
            self.assertIn(key, result)

    def test_ls_04_inadmissible_entry_never_appears(self):
        self.seed()
        titles = [r["title"] for r in self.search("ley", tags=["millholm"])]
        self.assertNotIn("Ley Lines", titles)

    def test_ls_05_untagged_entries_reach_a_caller_with_no_tags(self):
        self.seed()
        self.assertEqual(self.search("war", tags=[])[0]["title"], "The Great War")

    def test_ls_06_entries_without_an_embedding_are_skipped(self):
        make_lore(title="Unembedded", scope_tags=[], embedding=None)
        self.assertEqual(self.search("war"), [])

    def test_ls_07_wrong_dimension_entry_is_skipped_not_raised(self):
        make_lore(title="Short", scope_tags=[], embedding=self._blob([0.1] * 8))
        self.assertEqual(self.search("war"), [])

    def test_ls_08_empty_corpus_returns_empty_list(self):
        self.assertEqual(self.search(), [])

    def test_ls_09_failed_embedding_returns_none_not_empty(self):
        self.seed()
        with mock.patch.object(services, "_embed", return_value=None):
            self.assertIsNone(services.search_lore("war", []))

    @needs_postgres
    def test_ls_10_inadmissible_entries_do_not_starve_the_result(self):
        for i in range(9):
            make_lore(
                title=f"Guild secret {i}",
                scope_tags=["millholm", "mages_guild"],
                source=f"guild/{i}.yaml",
                embedding=self._blob(vec(0)),
            )
        make_lore(title="Common knowledge", scope_tags=[], embedding=self._blob(vec(1)))
        results = self.search("war", tags=["millholm"], top_k=3)
        self.assertEqual([r["title"] for r in results], ["Common knowledge"])

    @needs_postgres
    def test_ls_11_backends_agree_on_entries_and_order(self):
        self.seed()
        self.assertEqual(self.search("war")[0]["title"], "The Great War")

    def test_ls_12_a_short_result_is_returned_not_padded(self):
        self.seed()
        self.assertEqual(len(self.search("war", tags=[], top_k=3)), 1)

    def test_ls_13_takes_no_speaker(self):
        import inspect

        params = inspect.signature(services.search_lore).parameters
        self.assertNotIn("speaker_uuid", params)


# ── SC — scope access rules ──────────────────────────────────────────


class ScopeTests(TestCase):
    databases = {"default", ALIAS}

    def admits(self, entry_tags, caller_tags):
        return services._can_access_lore(entry_tags, caller_tags)

    def test_sc_01_empty_entry_tags_reach_everyone(self):
        self.assertTrue(self.admits([], ["millholm", "mages_guild"]))

    def test_sc_02_empty_entry_tags_reach_a_caller_with_none(self):
        self.assertTrue(self.admits([], []))

    def test_sc_03_single_matching_tag_grants_access(self):
        self.assertTrue(self.admits(["millholm"], ["millholm"]))

    def test_sc_04_single_non_matching_tag_denies_access(self):
        self.assertFalse(self.admits(["millholm"], ["riverford"]))

    def test_sc_05_two_entry_tags_with_one_held_denies_access(self):
        self.assertFalse(self.admits(["millholm", "mages_guild"], ["millholm"]))

    def test_sc_06_two_entry_tags_with_both_held_grants_access(self):
        self.assertTrue(
            self.admits(["millholm", "mages_guild"], ["millholm", "mages_guild"])
        )

    def test_sc_07_a_superset_of_holder_tags_grants_access(self):
        self.assertTrue(
            self.admits(["millholm"], ["millholm", "mages_guild", "temple"])
        )

    def test_sc_08_comparison_is_exact(self):
        self.assertFalse(self.admits(["Millholm"], ["millholm"]))
        self.assertFalse(self.admits([" millholm"], ["millholm"]))

    def test_sc_09_duplicates_do_not_change_the_answer(self):
        self.assertTrue(self.admits(["millholm", "millholm"], ["millholm"]))
        self.assertTrue(self.admits(["millholm"], ["millholm", "millholm"]))

    def test_sc_10_order_does_not_change_the_answer(self):
        self.assertEqual(
            self.admits(["a", "b"], ["b", "a"]), self.admits(["b", "a"], ["a", "b"])
        )

    def test_sc_11_tags_compare_by_equality_with_no_type_imposed(self):
        self.assertTrue(self.admits([1, 2], [1, 2, 3]))
        self.assertFalse(self.admits([1, 9], [1, 2, 3]))

    def test_sc_12_the_sql_filter_is_never_restrictive(self):
        make_lore(title="Open", scope_tags=[], source="a.yaml", embedding=b"")
        make_lore(title="Town", scope_tags=["millholm"], source="b.yaml", embedding=b"")
        make_lore(
            title="Guild",
            scope_tags=["millholm", "mages_guild"],
            source="c.yaml",
            embedding=b"",
        )
        held = ["millholm"]
        by_sql = set(
            LoreMemory.objects.using(ALIAS)
            .filter(services._lore_scope_filter(held))
            .values_list("title", flat=True)
        )
        by_rule = {
            row.title
            for row in LoreMemory.objects.using(ALIAS).all()
            if self.admits(row.scope_tags, held)
        }
        # The filter may admit more than the rule — SQLite has no containment
        # lookup, so there it admits everything and the rule runs in Python.
        # What it may never do is exclude something the rule would admit.
        self.assertTrue(by_rule <= by_sql)

    @needs_postgres
    def test_sc_13_the_query_expresses_the_tag_rule_itself(self):
        make_lore(title="Guild", scope_tags=["millholm", "mages_guild"], embedding=b"")
        admitted = LoreMemory.objects.using(ALIAS).filter(
            services._lore_scope_filter(["millholm"])
        )
        self.assertEqual(admitted.count(), 0)

    def test_sc_14_scope_level_is_stored_and_returned_but_does_not_gate(self):
        self.assertTrue(self.admits([], []))
        row = make_lore(scope_level="faction", scope_tags=[])
        self.assertEqual(row.scope_level, "faction")
        self.assertTrue(self.admits(row.scope_tags, []))

    def test_sc_15_empty_tags_are_admitted_whatever_the_level(self):
        for level in ("continental", "regional", "local", "faction"):
            self.assertTrue(self.admits([], []), level)


# ── BE — backend dispatch ────────────────────────────────────────────


class DatabaseResolutionTests(TestCase):
    databases = {"default", ALIAS}

    def resolve(self, env, sqlite_path="/tmp/ai_memory.db3"):
        with mock.patch.dict(os.environ, env, clear=True):
            return config.ai_memory_database(sqlite_path)

    def test_db_01_own_url_resolves_to_its_own_database(self):
        resolved = self.resolve(
            {config.MEMORY_URL_ENV: "postgres://u:p@own-host/memories"}
        )
        self.assertEqual(resolved["NAME"], "memories")
        self.assertEqual(resolved["HOST"], "own-host")

    def test_db_02_game_url_is_the_second_rung(self):
        resolved = self.resolve({config.GAME_URL_ENV: "postgres://u:p@game-host/game"})
        self.assertEqual(resolved["NAME"], "game")

    def test_db_03_neither_set_falls_back_to_sqlite(self):
        resolved = self.resolve({}, sqlite_path="/tmp/memories.db3")
        self.assertIn("sqlite", resolved["ENGINE"])
        self.assertEqual(resolved["NAME"], "/tmp/memories.db3")

    def test_db_04_own_url_wins_over_the_game_url(self):
        resolved = self.resolve(
            {
                config.MEMORY_URL_ENV: "postgres://u:p@own-host/memories",
                config.GAME_URL_ENV: "postgres://u:p@game-host/game",
            }
        )
        self.assertEqual(resolved["NAME"], "memories")

    def test_db_05_description_names_the_database_and_the_rung(self):
        with mock.patch.dict(
            os.environ, {config.MEMORY_URL_ENV: "postgres://u:p@h/memories"}, clear=True
        ):
            with override_settings(
                DATABASES={
                    **settings.DATABASES,
                    ALIAS: {"ENGINE": "django.db.backends.postgresql", "NAME": "memories", "HOST": "h"},
                }
            ):
                described = config.describe_ai_memory_database()
        self.assertIn("memories", described)
        self.assertIn(config.MEMORY_URL_ENV, described)

    def test_db_06_description_reports_no_credentials(self):
        with mock.patch.dict(
            os.environ,
            {config.MEMORY_URL_ENV: "postgres://someuser:secretpw@h/memories"},
            clear=True,
        ):
            with override_settings(
                DATABASES={
                    **settings.DATABASES,
                    ALIAS: config.ai_memory_database("/tmp/x.db3"),
                }
            ):
                described = config.describe_ai_memory_database()
        self.assertNotIn("secretpw", described)
        self.assertNotIn("someuser", described)

    def test_db_07_a_sqlite_path_is_reported_resolved(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "memories.db3")
            open(real, "w").close()
            link = os.path.join(tmp, "linked.db3")
            os.symlink(real, link)
            with mock.patch.dict(os.environ, {}, clear=True):
                with override_settings(
                    DATABASES={
                        **settings.DATABASES,
                        ALIAS: config.ai_memory_database(link),
                    }
                ):
                    described = config.describe_ai_memory_database()
            self.assertIn(os.path.realpath(real), described)

    def test_db_09_startup_names_the_resolved_database(self):
        from evennia_ai_memory.apps import EvenniaAiMemoryConfig

        with mock.patch("evennia_ai_memory.apps.ai_memory_log") as logged:
            EvenniaAiMemoryConfig.ready(mock.Mock())
        emitted = " ".join(str(call) for call in logged.call_args_list)
        self.assertIn(config.describe_ai_memory_database(), emitted)

    def test_db_08_sharing_the_game_database_is_named_as_such(self):
        shared = {"ENGINE": "django.db.backends.postgresql", "NAME": "game", "HOST": "h"}
        with mock.patch.dict(os.environ, {}, clear=True):
            with override_settings(
                DATABASES={**settings.DATABASES, "default": shared, ALIAS: shared}
            ):
                described = config.describe_ai_memory_database()
        self.assertIn("shared with the game database", described)


class BackendTests(TestCase):
    databases = {"default", ALIAS}

    def test_be_01_sqlite_alias_selects_the_numpy_path(self):
        if _PG:
            self.skipTest("SQLite path")
        self.assertFalse(services._is_postgres())

    @needs_postgres
    def test_be_02_postgres_alias_selects_the_pgvector_path(self):
        self.assertTrue(services._is_postgres())

    def test_be_03_detection_reads_the_library_alias(self):
        with override_settings(
            DATABASES={
                **settings.DATABASES,
                "default": {"ENGINE": "django.db.backends.postgresql"},
            }
        ):
            self.assertEqual(services._is_postgres(), _PG)

    def test_be_04_selection_reads_the_engine_not_the_environment(self):
        mysql = {
            **settings.DATABASES,
            ALIAS: {"ENGINE": "django.db.backends.mysql", "NAME": "x"},
        }
        with mock.patch.dict(
            os.environ, {config.GAME_URL_ENV: "mysql://user@host/db"}
        ):
            with override_settings(DATABASES=mysql):
                self.assertFalse(services._is_postgres())

    def test_be_05_self_similarity_is_one(self):
        self.assertAlmostEqual(services._cosine_similarity(vec(3), vec(3)), 1.0, places=6)

    def test_be_06_orthogonal_similarity_is_zero(self):
        self.assertAlmostEqual(services._cosine_similarity(vec(1), vec(2)), 0.0, places=6)

    def test_be_07_zero_vector_does_not_divide_by_zero(self):
        zeros = [0.0] * EMBEDDING_DIMENSIONS
        self.assertEqual(services._cosine_similarity(zeros, vec(1)), 0.0)

    def test_be_08_similarity_is_symmetric(self):
        a, b = vec(1), vec(4)
        self.assertAlmostEqual(
            services._cosine_similarity(a, b), services._cosine_similarity(b, a)
        )


# ── RT — database router ─────────────────────────────────────────────


class _ForeignModel:
    class _meta:
        app_label = "some_other_app"


class RouterTests(TestCase):
    databases = {"default", ALIAS}

    def setUp(self):
        self.router = AiMemoryRouter()

    def test_rt_01_reads_route_to_the_library_alias(self):
        self.assertEqual(self.router.db_for_read(NpcMemory), ALIAS)

    def test_rt_02_writes_route_to_the_library_alias(self):
        self.assertEqual(self.router.db_for_write(LoreMemory), ALIAS)

    def test_rt_03_foreign_models_return_none(self):
        self.assertIsNone(self.router.db_for_read(_ForeignModel))
        self.assertIsNone(self.router.db_for_write(_ForeignModel))

    def test_rt_04_relations_between_own_models_are_allowed(self):
        self.assertTrue(self.router.allow_relation(NpcMemory, LoreMemory))

    def test_rt_05_relations_involving_a_foreign_model_return_none(self):
        self.assertIsNone(self.router.allow_relation(NpcMemory, _ForeignModel))

    def test_rt_06_own_migrations_apply_only_on_the_library_alias(self):
        self.assertTrue(self.router.allow_migrate(ALIAS, "evennia_ai_memory"))
        self.assertFalse(self.router.allow_migrate("default", "evennia_ai_memory"))

    def test_rt_07_foreign_migrations_are_refused_on_the_library_alias(self):
        self.assertFalse(self.router.allow_migrate(ALIAS, "some_other_app"))

    def test_rt_08_foreign_migrations_elsewhere_return_none(self):
        self.assertIsNone(self.router.allow_migrate("default", "some_other_app"))

    def test_rt_09_a_sibling_router_is_not_captured(self):
        for hook in ("db_for_read", "db_for_write"):
            self.assertIsNone(getattr(self.router, hook)(_ForeignModel))
        self.assertIsNone(self.router.allow_migrate("other_alias", "some_other_app"))


# ── LG — logging ─────────────────────────────────────────────────────


class LoggingTests(MemoryTestCase):
    def test_lg_01_lines_go_to_the_libraries_own_log_file(self):
        from evennia_ai_memory import log

        with mock.patch("evennia.utils.logger.log_file") as log_file:
            log.ai_memory_log("hello")
        self.assertEqual(log_file.call_args.kwargs["filename"], "ai_memory.log")

    def test_lg_02_a_dropped_write_logs_the_cause(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder(RuntimeError("service unreachable"))):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        emitted = " ".join(str(call) for call in logged.call_args_list)
        self.assertIn("service unreachable", emitted)

    def test_lg_03_each_retry_and_the_final_drop_are_logged(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertGreaterEqual(
            len(logged.call_args_list), services.WRITE_ATTEMPTS
        )

    def test_lg_04_an_unknown_level_degrades_rather_than_raising(self):
        from evennia_ai_memory import log

        with mock.patch("evennia.utils.logger.log_file") as log_file:
            log.ai_memory_log("hello", level="SHOUTING")
        self.assertIn("[INFO]", log_file.call_args.args[0])

    def test_lg_05_the_shim_is_a_no_op_outside_an_evennia_engine(self):
        from evennia_ai_memory import log

        with mock.patch.dict("sys.modules", {"evennia.utils.logger": None}):
            log.ai_memory_log("this must not raise")

    def test_lg_06_a_read_that_could_not_embed_is_logged(self):
        with mock.patch.object(services, "_embed_once", side_effect=RaisingEmbedder()):
            with mock.patch.object(services, "ai_memory_log") as logged:
                services.search_memories(self.npc, self.speaker, "anything")
        self.assertTrue(logged.call_args_list)

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY=None)
    def test_lg_07_a_refused_startup_is_logged_as_well_as_raised(self):
        with mock.patch.object(config, "ai_memory_log") as logged:
            with self.assertRaises(ImproperlyConfigured):
                config.validate_settings()
        emitted = " ".join(str(call) for call in logged.call_args_list)
        self.assertIn(config.SETTING_API_KEY, emitted)

    def test_lg_08_a_dropped_write_is_logged_at_error_with_a_traceback(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertTrue(
            any(
                call.kwargs.get("level") == "ERROR" and call.kwargs.get("trace")
                for call in logged.call_args_list
            )
        )

    def test_lg_09_nothing_is_written_to_stdout_or_stderr(self):
        for name, source in library_source().items():
            self.assertNotIn("print(", source, f"print in {name}")
            self.assertNotIn("sys.stdout", source, f"stdout in {name}")
            self.assertNotIn("sys.stderr", source, f"stderr in {name}")


# ── XC — cross-cutting ───────────────────────────────────────────────


class CrossCuttingTests(MemoryTestCase):
    def test_xc_13_the_standalone_validator_runs_without_evennia(self):
        # Not a boundary against Evennia — the library runs inside it. This is
        # functional: a pre-commit hook or a CI job validates a checkout with
        # no gamedir and no configured settings, so the validator cannot need
        # an engine to start.
        source = library_source()["cli.py"]
        self.assertNotIn("import evennia", source)
        self.assertNotIn("from evennia", source)

    def test_xc_02_public_functions_return_plain_data(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        for result in services.get_recent_memories(self.npc, self.speaker):
            self.assertIsInstance(result, dict)
            for value in result.values():
                self.assertNotIsInstance(value, NpcMemory)

    def test_xc_03_results_are_fresh_objects(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        first = services.get_recent_memories(self.npc, self.speaker)
        first[0]["summary"] = "mutated"
        second = services.get_recent_memories(self.npc, self.speaker)
        self.assertNotEqual(second[0]["summary"], "mutated")

    def test_xc_04_public_functions_are_synchronous(self):
        import inspect

        for name in evennia_ai_memory.__all__:
            if name == "__version__":
                continue
            func = getattr(evennia_ai_memory, name)
            self.assertFalse(inspect.iscoroutinefunction(func), name)

    def test_xc_05_memory_and_lore_searches_are_independent(self):
        make_lore(title="The Great War", scope_tags=[], embedding=b"")
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
            memories = services.search_memories(self.npc, self.speaker, "war")
        self.assertTrue(all("title" not in m for m in memories or []))

    def test_xc_06_scope_tags_arrive_as_plain_strings(self):
        with patch_embedder(StubEmbedder()):
            services.search_lore("anything", ["millholm"])

    def test_xc_07_a_default_rebuild_leaves_library_rows_intact(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 1)
        self.assertEqual(
            NpcMemory._meta.app_label, AiMemoryRouter.app_label
        )

    def test_xc_08_timestamps_are_aware_throughout(self):
        row = make_memory(npc_uuid=self.npc, speaker_uuid=self.speaker)
        self.assertIsNotNone(row.created_at.tzinfo)
        lore = make_lore()
        self.assertIsNotNone(lore.created_at.tzinfo)
        self.assertIsNotNone(lore.updated_at.tzinfo)

    def test_version(self):
        self.assertEqual(evennia_ai_memory.__version__, "0.0.1")

    def test_app_installed(self):
        self.assertIn("evennia_ai_memory", settings.INSTALLED_APPS)

    def test_ai_memory_alias_configured(self):
        self.assertIn(ALIAS, settings.DATABASES)

    def test_xc_12_every_read_returns_one_shape(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "a", "b")
            searched = services.search_memories(self.npc, self.speaker, "a")
        recent = services.get_recent_memories(self.npc, self.speaker)
        shared = set(recent[0]) - {"similarity"}
        self.assertEqual(set(searched[0]) - {"similarity"}, shared)
