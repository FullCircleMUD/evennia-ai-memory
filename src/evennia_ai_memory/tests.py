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
from evennia_ai_memory import config, db_spec, lore_import, services
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


def make_memory(npc_uuid=None, pc_uuid=None, **kwargs):
    """Build an ``NpcMemory`` row directly, bypassing ``store_memory``."""
    fields = {
        "npc_uuid": npc_uuid or uuid.uuid4(),
        "pc_uuid": pc_uuid or uuid.uuid4(),
        "pc_name": "Bob",
        "summary": "Bob asked about a sword, and you sold him one.",
        "interaction_type": "say",
        "initiator": "pc",
    }
    fields.update(kwargs)
    return NpcMemory.objects.using(ALIAS).create(**fields)


class FakeReader:
    """Serves a fixed set of paths, and raises like a real reader otherwise.

    Stands in for `GitHubReader` and `LocalReader` alike — the import cares
    only that a path either yields YAML or raises `ReaderNotFoundError`.
    """

    def __init__(self, files=None, on_read=None):
        self.files = dict(files or {})
        self.on_read = on_read
        self.reads = []

    def read(self, path):
        import yaml
        from evennia_yaml_reader import ReaderNotFoundError, ReaderResult

        self.reads.append(path)
        if self.on_read is not None:
            self.on_read(path)
        if path not in self.files:
            raise ReaderNotFoundError(f"no such path: {path}")
        raw = self.files[path]
        return ReaderResult(
            raw_bytes=raw.encode("utf-8"), parsed=yaml.safe_load(raw)
        )


def manifest(*sources):
    """The repository manifest naming its content files."""
    listed = "\n".join(f"  - {s}" for s in sources)
    return f"sources:\n{listed}\n"


def lore_file(source, *entries):
    """One lore YAML file holding the given entries."""
    import yaml

    return yaml.safe_dump(
        {
            "source": source,
            "entries": [
                {
                    "title": title,
                    "scope_level": level,
                    "scope_tags": list(tags),
                    "content": content,
                }
                for title, level, tags, content in entries
            ],
        },
        sort_keys=False,
    )


ENTRY = ("The Great War", "continental", [], "It lasted a hundred years.")


def repo(*files):
    """A FakeReader over a manifest and the files it names."""
    sources = [source for source, _ in files]
    served = {lore_import.MANIFEST: manifest(*sources)}
    served.update(dict(files))
    return FakeReader(served)


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


def imported_names(source):
    """Every module name a source file imports.

    Parsed rather than matched, so a docstring describing a rule does not read
    as a breach of it.
    """
    import ast

    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def imports_evennia(source):
    """Whether a source file imports Evennia itself.

    Matched on the module name, not on the text: `evennia_yaml_reader` is a
    sibling library, not Evennia, and a substring check reads it as one.
    """
    return any(
        name == "evennia" or name.startswith("evennia.")
        for name in imported_names(source)
    )


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
                services.store_memory(self.npc, self.speaker, "Bob", "Bob greeted you.")
        self.assertEqual(flaky.calls, services.WRITE_ATTEMPTS)
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_em_03_permanent_write_failure_is_not_retried(self):
        raising = RaisingEmbedder(services.PermanentEmbeddingError("bad key"))
        with mock.patch.object(services, "_embed_once", side_effect=raising):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob greeted you.")
        self.assertEqual(raising.calls, 1)

    def test_em_06_embeds_once_per_row(self):
        counting = CountingEmbedder()
        with patch_embedder(counting):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertEqual(len(counting.texts), 1)

    def test_em_07_wrong_length_vector_is_refused(self):
        with patch_embedder(ShortEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_em_08_no_rate_limiter_or_cost_tracking_in_source(self):
        banned = ("rate_limit", "ratelimit", "cost_cents", "cost_track", "daily_cap")
        for name, source in library_source().items():
            for token in banned:
                self.assertNotIn(token, source.lower(), f"{token} in {name}")

    def test_em_18_dimensions_default_when_the_consumer_sets_none(self):
        # The suite deliberately leaves this one unset, so the unconfigured
        # case is the default case and needs no contrivance to reach.
        self.assertFalse(hasattr(settings, config.SETTING_DIMENSIONS))
        self.assertEqual(
            config.get_embedding_dimensions(), config.DEFAULT_DIMENSIONS
        )

    @override_settings(AI_MEMORY_EMBEDDING_DIMENSIONS=768)
    def test_em_19_a_configured_width_overrides_the_default(self):
        self.assertEqual(config.get_embedding_dimensions(), 768)

    def test_em_20_the_vector_column_is_built_at_the_configured_width(self):
        field = NpcMemory._meta.get_field("embedding_vector")
        self.assertEqual(field.dimensions, config.get_embedding_dimensions())

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
            config.check_settings()

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY=None)
    def test_em_05_error_names_the_setting_and_where_to_put_it(self):
        with self.assertRaises(ImproperlyConfigured) as caught:
            config.check_settings()
        message = str(caught.exception)
        self.assertIn(config.SETTING_API_KEY, message)
        self.assertIn(config.KEY_LOCATION_HINT, message)

    @override_settings(AI_MEMORY_EMBEDDING_BASE_URL=None)
    def test_em_10_missing_base_url_raises_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            config.check_settings()

    @override_settings(AI_MEMORY_EMBEDDING_MODEL=None)
    def test_em_11_missing_model_raises_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            config.check_settings()

    def test_em_12_settings_are_read_only_through_config(self):
        for name, source in library_source().items():
            if name == "config.py":
                continue
            self.assertNotIn("settings.AI_MEMORY", source, f"direct read in {name}")

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY="")
    def test_em_13_empty_setting_counts_as_missing(self):
        with self.assertRaises(ImproperlyConfigured):
            config.check_settings()

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
    SUMMARY = "Bob asked about a sword, and you sold him one."

    def store(self, **kwargs):
        fields = {
            "npc_uuid": self.npc,
            "pc_uuid": self.speaker,
            "pc_name": "Bob",
            "summary": self.SUMMARY,
        }
        fields.update(kwargs)
        with patch_embedder(StubEmbedder()):
            return services.store_memory(**fields)

    def test_sm_01_stored_event_is_retrievable(self):
        self.store()
        results = services.get_recent_memories(self.npc, self.speaker)
        self.assertEqual(len(results), 1)

    def test_sm_02_row_records_the_pair_name_summary_type_and_initiator(self):
        self.store(interaction_type="pickpocket", initiator="npc")
        row = NpcMemory.objects.using(ALIAS).get()
        self.assertEqual(row.npc_uuid, self.npc)
        self.assertEqual(row.pc_uuid, self.speaker)
        self.assertEqual(row.pc_name, "Bob")
        self.assertEqual(row.summary, self.SUMMARY)
        self.assertEqual(row.interaction_type, "pickpocket")
        self.assertEqual(row.initiator, "npc")

    def test_sm_03_the_summary_is_stored_exactly_as_given(self):
        self.store(summary="Bob picked your pocket and got away with it.")
        self.assertEqual(
            NpcMemory.objects.using(ALIAS).get().summary,
            "Bob picked your pocket and got away with it.",
        )

    def test_sm_10_the_summary_is_what_gets_embedded(self):
        counting = CountingEmbedder()
        with patch_embedder(counting):
            services.store_memory(self.npc, self.speaker, "Bob", self.SUMMARY)
        self.assertEqual(counting.texts, [self.SUMMARY])

    def test_sm_15_initiator_defaults_to_the_character(self):
        self.store()
        self.assertEqual(NpcMemory.objects.using(ALIAS).get().initiator, "pc")
        NpcMemory.objects.using(ALIAS).all().delete()
        self.store(initiator="npc")
        self.assertEqual(NpcMemory.objects.using(ALIAS).get().initiator, "npc")

    def test_sm_16_an_unrecognised_initiator_is_refused(self):
        for bad in ("player", "PC", "", "mob"):
            with self.assertRaises(ValueError):
                self.store(initiator=bad)

    def test_sm_17_any_interaction_type_is_accepted(self):
        for kind in ("say", "pickpocket", "taunted", "bought_from", "fled"):
            self.store(interaction_type=kind)
        stored = set(
            NpcMemory.objects.using(ALIAS).values_list("interaction_type", flat=True)
        )
        self.assertEqual(len(stored), 5)

    def test_sm_18_an_empty_summary_is_refused(self):
        for empty in ("", "   ", None):
            with self.assertRaises(ValueError):
                self.store(summary=empty)

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
            services.store_memory(self.npc, self.speaker, "Bob", self.SUMMARY)
        row = NpcMemory.objects.using(ALIAS).get()
        stored = np.frombuffer(bytes(row.embedding), dtype=np.float32).tolist()
        self.assertEqual(stored, expected)

    def test_sm_07_embedding_failure_does_not_raise_into_the_caller(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")

    def test_sm_08_transient_write_failure_is_retried_then_dropped(self):
        with patch_embedder(StubEmbedder()):
            with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
                with mock.patch.object(
                    NpcMemory.objects, "using", side_effect=RuntimeError("db down")
                ):
                    services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_sm_09_never_writes_a_row_without_a_vector(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 0)

    def test_sm_11_identical_events_are_not_deduplicated(self):
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
                    pc_uuid=kwargs.get("pc_uuid", self.speaker),
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
                kwargs.get("pc_uuid", self.speaker),
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
            "similarity",
            "created_at",
            "pc_name",
            "interaction_type",
            "initiator",
        ):
            self.assertIn(key, result)

    def test_ms_06_both_uuids_are_required(self):
        with self.assertRaises(TypeError):
            services.search_memories(self.npc, query_text="sword")

    def test_ms_07_rows_without_an_embedding_are_skipped(self):
        make_memory(npc_uuid=self.npc, pc_uuid=self.speaker, embedding=None)
        self.assertEqual(self.search(), [])

    def test_ms_08_wrong_dimension_row_is_skipped_not_raised(self):
        make_memory(
            npc_uuid=self.npc,
            pc_uuid=self.speaker,
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

    def test_ms_18_an_event_of_any_type_is_searchable(self):
        make_memory(
            npc_uuid=self.npc,
            pc_uuid=self.speaker,
            summary="Bob picked your pocket",
            interaction_type="pickpocket",
            embedding=self._blob(vec(0)),
        )
        found = self.search("sword")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["interaction_type"], "pickpocket")

    def test_ms_17_ties_are_ordered_deterministically(self):
        same = vec(0)
        for _ in range(3):
            make_memory(
                npc_uuid=self.npc,
                pc_uuid=self.speaker,
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
                pc_uuid=kwargs.get("pc_uuid", self.speaker),
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

    def test_mr_08_results_carry_the_type_and_initiator(self):
        make_memory(
            npc_uuid=self.npc,
            pc_uuid=self.speaker,
            interaction_type="pickpocket",
            initiator="pc",
        )
        result = services.get_recent_memories(self.npc, self.speaker)[0]
        self.assertEqual(result["interaction_type"], "pickpocket")
        self.assertEqual(result["initiator"], "pc")

    def test_mr_07_another_speaker_is_excluded(self):
        self.seed(count=1, pc_uuid=self.other)
        self.assertEqual(services.get_recent_memories(self.npc, self.speaker), [])


# ── LI — get_last_interaction_time ───────────────────────────────────


class LastInteractionTests(MemoryTestCase):
    def test_li_01_returns_the_most_recent_timestamp(self):
        old = aged(make_memory(npc_uuid=self.npc, pc_uuid=self.speaker), timedelta(days=5))
        new = aged(make_memory(npc_uuid=self.npc, pc_uuid=self.speaker), timedelta(hours=1))
        when, _ = services.get_last_interaction_time(self.npc, self.speaker)
        self.assertEqual(when.replace(microsecond=0), new.created_at.replace(microsecond=0))
        self.assertNotEqual(when.replace(microsecond=0), old.created_at.replace(microsecond=0))

    def test_li_02_no_history_returns_the_empty_result(self):
        self.assertEqual(
            services.get_last_interaction_time(self.npc, self.speaker), (None, None)
        )

    def test_li_03_another_speaker_does_not_satisfy_the_query(self):
        make_memory(npc_uuid=self.npc, pc_uuid=self.other)
        self.assertEqual(
            services.get_last_interaction_time(self.npc, self.speaker), (None, None)
        )

    def test_li_04_both_uuids_must_match_with_no_name_fallback(self):
        make_memory(npc_uuid=self.npc, pc_uuid=self.speaker, pc_name="Bob")
        self.assertEqual(
            services.get_last_interaction_time(uuid.uuid4(), self.speaker),
            (None, None),
        )

    def test_li_05_returns_a_timestamp_and_a_phrase(self):
        aged(make_memory(npc_uuid=self.npc, pc_uuid=self.speaker), timedelta(days=2))
        when, phrase = services.get_last_interaction_time(self.npc, self.speaker)
        self.assertIsNotNone(when)
        self.assertIsInstance(phrase, str)
        self.assertTrue(phrase)

    def test_li_06_returned_datetime_is_aware(self):
        make_memory(npc_uuid=self.npc, pc_uuid=self.speaker)
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
        self.assertNotIn("pc_uuid", params)


# ── SL — store_lore ──────────────────────────────────────────────────


class StoreLoreTests(MemoryTestCase):
    def store(self, **kwargs):
        fields = {
            "title": "Founding of Millholm",
            "content": "Millholm was founded four hundred years ago.",
            "scope_level": "regional",
            "scope_tags": ["millholm"],
            "source": "millholm/regional.yaml",
        }
        fields.update(kwargs)
        with patch_embedder(StubEmbedder()):
            return services.store_lore(**fields)

    def test_sl_01_a_new_entry_is_created(self):
        _, status = self.store()
        self.assertEqual(status, "created")
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_sl_02_identical_content_is_unchanged_and_embeds_nothing(self):
        self.store()
        counting = CountingEmbedder()
        with patch_embedder(counting):
            _, status = services.store_lore(
                title="Founding of Millholm",
                content="Millholm was founded four hundred years ago.",
                scope_level="regional",
                scope_tags=["millholm"],
                source="millholm/regional.yaml",
            )
        self.assertEqual(status, "unchanged")
        self.assertEqual(counting.texts, [])

    def test_sl_03_changed_content_is_updated_and_re_embedded(self):
        self.store()
        counting = CountingEmbedder()
        with patch_embedder(counting):
            _, status = services.store_lore(
                title="Founding of Millholm",
                content="Millholm was founded five hundred years ago.",
                scope_level="regional",
                scope_tags=["millholm"],
                source="millholm/regional.yaml",
            )
        self.assertEqual(status, "updated")
        self.assertEqual(len(counting.texts), 1)

    def test_sl_04_changed_scope_level_alone_is_an_update(self):
        self.store()
        _, status = self.store(scope_level="local")
        self.assertEqual(status, "updated")

    def test_sl_05_changed_scope_tags_alone_is_an_update(self):
        self.store()
        _, status = self.store(scope_tags=["millholm", "mages_guild"])
        self.assertEqual(status, "updated")

    def test_sl_06_the_same_title_under_another_source_is_a_separate_entry(self):
        self.store()
        _, status = self.store(source="factions/mages_guild.yaml")
        self.assertEqual(status, "created")
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 2)

    def test_sl_07_the_same_source_and_title_never_duplicates(self):
        self.store()
        self.store(content="different")
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_sl_08_a_failed_re_embed_leaves_the_stored_vector(self):
        self.store()
        before = LoreMemory.objects.using(ALIAS).get().embedding
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                services.store_lore(
                    title="Founding of Millholm",
                    content="rewritten",
                    scope_level="regional",
                    scope_tags=["millholm"],
                    source="millholm/regional.yaml",
                )
        self.assertEqual(LoreMemory.objects.using(ALIAS).get().embedding, before)

    def test_sl_09_an_update_failure_retries_then_logs_and_drops(self):
        self.store()
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()) as embed:
                _, status = services.store_lore(
                    title="Founding of Millholm",
                    content="rewritten",
                    scope_level="regional",
                    scope_tags=["millholm"],
                    source="millholm/regional.yaml",
                )
        self.assertEqual(status, "failed")
        self.assertEqual(embed.call_count, services.WRITE_ATTEMPTS)

    def test_sl_10_a_create_failure_retries_then_logs_and_drops(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()) as embed:
                _, status = services.store_lore(
                    title="New", content="x", scope_level="local",
                    scope_tags=[], source="a.yaml",
                )
        self.assertEqual(status, "failed")
        self.assertEqual(embed.call_count, services.WRITE_ATTEMPTS)
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 0)

    def test_sl_11_empty_scope_tags_are_reachable_by_everyone(self):
        self.store(scope_tags=[])
        row = LoreMemory.objects.using(ALIAS).get()
        self.assertTrue(services._can_access_lore(row.scope_tags, []))

    def test_sl_12_updated_at_advances_on_update_but_not_on_unchanged(self):
        self.store()
        row = aged(LoreMemory.objects.using(ALIAS).get(), timedelta(days=1))
        stale = row.updated_at
        self.store()
        self.assertEqual(LoreMemory.objects.using(ALIAS).get().updated_at, stale)
        self.store(content="rewritten")
        self.assertGreater(LoreMemory.objects.using(ALIAS).get().updated_at, stale)

    def test_sl_13_a_bulk_run_embeds_once_per_new_or_changed_entry(self):
        counting = CountingEmbedder()
        with patch_embedder(counting):
            for i in range(3):
                services.store_lore(
                    title=f"Entry {i}", content=f"body {i}",
                    scope_level="local", scope_tags=[], source="a.yaml",
                )
            for i in range(3):  # unchanged second pass
                services.store_lore(
                    title=f"Entry {i}", content=f"body {i}",
                    scope_level="local", scope_tags=[], source="a.yaml",
                )
        self.assertEqual(len(counting.texts), 3)

    def test_sl_14_any_scope_level_string_is_accepted(self):
        _, status = self.store(scope_level="whatever-the-consumer-calls-it")
        self.assertEqual(status, "created")

    def test_sl_15_create_and_update_behave_alike_on_the_same_fault(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                _, on_create = services.store_lore(
                    title="A", content="x", scope_level="local",
                    scope_tags=[], source="a.yaml",
                )
        self.store()
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                _, on_update = services.store_lore(
                    title="Founding of Millholm", content="rewritten",
                    scope_level="regional", scope_tags=["millholm"],
                    source="millholm/regional.yaml",
                )
        self.assertEqual(on_create, on_update)


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


# ── IM — the lore import command ─────────────────────────────────────


class LoreImportTests(MemoryTestCase):
    def setUp(self):
        super().setUp()
        self.reader = repo(("a.yaml", lore_file("a.yaml", ENTRY)))

    def plan(self, reader=None):
        with patch_embedder(StubEmbedder()):
            return lore_import.plan_import(reader or self.reader)

    def run_import(self, reader=None):
        with patch_embedder(StubEmbedder()):
            return lore_import.apply_import(
                lore_import.plan_import(reader or self.reader)
            )

    def bad_repo(self, body):
        return FakeReader({lore_import.MANIFEST: manifest("a.yaml"), "a.yaml": body})

    # -- source and reader --

    def test_im_01_the_command_reads_through_the_configured_reader(self):
        with mock.patch.object(
            config, "get_configured_reader", return_value=self.reader
        ) as configured:
            self.run_import(config.get_configured_reader())
        self.assertTrue(configured.called)
        self.assertIn(lore_import.MANIFEST, self.reader.reads)

    def test_im_02_a_missing_repo_names_the_reader_settings(self):
        from evennia_yaml_reader import ReaderNotFoundError

        def absent(path):
            raise ReaderNotFoundError("no such ref")

        with self.assertRaises(lore_import.LoreImportError) as caught:
            self.plan(FakeReader(on_read=absent))
        message = str(caught.exception)
        self.assertIn(config.SETTING_READER, message)
        self.assertIn(config.SETTING_READER_KWARGS, message)

    def test_im_03_a_rejected_token_reports_as_an_auth_failure(self):
        from evennia_yaml_reader import ReaderAuthError

        def refused(path):
            raise ReaderAuthError("bad credentials")

        with self.assertRaises(lore_import.LoreImportError) as caught:
            self.plan(FakeReader(on_read=refused))
        self.assertIn("auth", str(caught.exception).lower())

    def test_im_04_the_standalone_validator_always_reads_locally(self):
        import inspect

        from evennia_ai_memory import cli

        source = inspect.getsource(cli)
        self.assertIn("LocalReader", source)
        self.assertNotIn(config.SETTING_READER, source)

    # -- manifest and discovery --

    def test_im_05_every_file_the_manifest_names_is_read(self):
        reader = repo(
            ("a.yaml", lore_file("a.yaml", ENTRY)),
            ("b/c.yaml", lore_file("b/c.yaml", ("Bread", "local", ["millholm"], "x"))),
        )
        self.plan(reader)
        self.assertIn("a.yaml", reader.reads)
        self.assertIn("b/c.yaml", reader.reads)

    def test_im_06_a_manifest_naming_an_absent_file_refuses(self):
        reader = FakeReader({
            lore_import.MANIFEST: manifest("a.yaml", "gone.yaml"),
            "a.yaml": lore_file("a.yaml", ENTRY),
        })
        with self.assertRaises(lore_import.LoreImportError) as caught:
            self.plan(reader)
        self.assertIn("gone.yaml", str(caught.exception))

    def test_im_32_a_missing_manifest_names_the_expected_file(self):
        with self.assertRaises(lore_import.LoreImportError) as caught:
            self.plan(FakeReader({}))
        self.assertIn(lore_import.MANIFEST, str(caught.exception))

    def test_im_33_a_malformed_manifest_is_an_error(self):
        for bad in ("not a mapping\n", "sources: {}\n", "other: [a.yaml]\n"):
            with self.assertRaises(lore_import.LoreImportError):
                self.plan(FakeReader({lore_import.MANIFEST: bad}))

    def test_im_34_a_file_the_manifest_omits_is_not_read(self):
        reader = FakeReader({
            lore_import.MANIFEST: manifest("a.yaml"),
            "a.yaml": lore_file("a.yaml", ENTRY),
            "unlisted.yaml": lore_file("unlisted.yaml", ENTRY),
        })
        self.plan(reader)
        self.assertNotIn("unlisted.yaml", reader.reads)

    def test_im_07_a_read_resolving_no_entries_refuses(self):
        reader = FakeReader({lore_import.MANIFEST: manifest("a.yaml"),
                             "a.yaml": lore_file("a.yaml")})
        with self.assertRaises(lore_import.EmptyRepositoryError):
            self.plan(reader)
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 0)

    def test_im_08_that_refusal_points_at_the_wipe_command(self):
        reader = FakeReader({lore_import.MANIFEST: manifest("a.yaml"),
                             "a.yaml": lore_file("a.yaml")})
        with self.assertRaises(lore_import.EmptyRepositoryError) as caught:
            self.plan(reader)
        self.assertIn("wipe", str(caught.exception).lower())

    # -- validation --

    def test_im_09_one_invalid_entry_writes_nothing(self):
        make_lore(title="Existing", source="a.yaml")
        body = "source: a.yaml\nentries:\n  - title: No content\n    scope_level: local\n"
        with self.assertRaises(lore_import.LoreValidationError):
            self.plan(self.bad_repo(body))
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_im_10_a_missing_field_names_the_file_and_title(self):
        body = "source: a.yaml\nentries:\n  - title: Half Done\n    scope_level: local\n"
        with self.assertRaises(lore_import.LoreValidationError) as caught:
            self.plan(self.bad_repo(body))
        reported = " ".join(caught.exception.problems)
        self.assertIn("a.yaml", reported)
        self.assertIn("Half Done", reported)

    def test_im_11_malformed_yaml_names_the_file(self):
        with self.assertRaises(lore_import.LoreImportError) as caught:
            self.plan(self.bad_repo("entries: [unclosed\n"))
        self.assertIn("a.yaml", str(caught.exception))

    def test_im_12_scope_tags_that_are_not_a_list_are_refused(self):
        body = (
            "source: a.yaml\nentries:\n  - title: T\n    scope_level: local\n"
            "    scope_tags: millholm\n    content: x\n"
        )
        with self.assertRaises(lore_import.LoreValidationError):
            self.plan(self.bad_repo(body))

    def test_im_13_a_duplicate_title_within_one_source_is_refused(self):
        with self.assertRaises(lore_import.LoreValidationError) as caught:
            self.plan(self.bad_repo(lore_file("a.yaml", ENTRY, ENTRY)))
        self.assertIn(ENTRY[0], " ".join(caught.exception.problems))

    def test_im_14_an_unrecognised_scope_level_passes_validation(self):
        reader = repo(("a.yaml", lore_file(
            "a.yaml", ("T", "whatever-the-game-calls-it", [], "x"))))
        self.assertTrue(self.plan(reader))

    def test_im_15_every_problem_is_reported_in_one_pass(self):
        body = (
            "source: a.yaml\nentries:\n"
            "  - title: One\n    scope_level: local\n"
            "  - title: Two\n    scope_level: local\n"
        )
        with self.assertRaises(lore_import.LoreValidationError) as caught:
            self.plan(self.bad_repo(body))
        self.assertGreaterEqual(len(caught.exception.problems), 2)

    # -- apply --

    def test_im_16_a_new_entry_is_created_and_reported(self):
        report = self.run_import()
        self.assertEqual(report.created, [("a.yaml", ENTRY[0])])
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_im_17_an_unchanged_entry_is_skipped_and_embeds_nothing(self):
        self.run_import()
        counting = CountingEmbedder()
        with patch_embedder(counting):
            report = lore_import.apply_import(lore_import.plan_import(self.reader))
        self.assertEqual(report.unchanged, [("a.yaml", ENTRY[0])])
        self.assertEqual(counting.texts, [])

    def test_im_18_a_changed_entry_is_updated_and_re_embedded(self):
        self.run_import()
        changed = repo(("a.yaml", lore_file(
            "a.yaml", (ENTRY[0], ENTRY[1], ENTRY[2], "It lasted two hundred years."))))
        report = self.run_import(changed)
        self.assertEqual(report.updated, [("a.yaml", ENTRY[0])])

    def test_im_19_identity_is_source_and_title(self):
        both = repo(("a.yaml", lore_file("a.yaml", ENTRY)),
                    ("b.yaml", lore_file("b.yaml", ENTRY)))
        self.run_import(both)
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 2)

    def test_im_20_an_interrupted_run_completes_on_re_run(self):
        many = repo(("a.yaml", lore_file(
            "a.yaml", ENTRY, ("Second", "local", [], "y"))))
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                lore_import.apply_import(lore_import.plan_import(many))
        self.run_import(many)
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 2)

    # -- prune --

    def test_im_21_an_entry_absent_from_the_yaml_is_removed(self):
        self.run_import()
        emptied = repo(("a.yaml", lore_file("a.yaml", ("Other", "local", [], "z"))))
        self.run_import(emptied)
        titles = set(LoreMemory.objects.using(ALIAS).values_list("title", flat=True))
        self.assertEqual(titles, {"Other"})

    def test_im_22_a_removed_entry_and_a_removed_file_are_treated_alike(self):
        two = repo(("a.yaml", lore_file("a.yaml", ENTRY)),
                   ("b.yaml", lore_file("b.yaml", ("Bee", "local", [], "y"))))
        self.run_import(two)
        self.run_import()
        sources = set(LoreMemory.objects.using(ALIAS).values_list("source", flat=True))
        self.assertEqual(sources, {"a.yaml"})

    def test_im_23_removals_are_named_not_merely_counted(self):
        self.run_import()
        emptied = repo(("a.yaml", lore_file("a.yaml", ("Other", "local", [], "z"))))
        report = self.run_import(emptied)
        self.assertEqual(report.removed, [("a.yaml", ENTRY[0])])

    def test_im_24_a_refused_run_removes_nothing(self):
        self.run_import()
        body = "source: a.yaml\nentries:\n  - title: Broken\n    scope_level: local\n"
        with self.assertRaises(lore_import.LoreValidationError):
            self.plan(self.bad_repo(body))
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_im_25_a_row_no_yaml_claims_is_removed_whatever_made_it(self):
        make_lore(title="Hand written", source="nobody/claims.yaml")
        self.run_import()
        titles = set(LoreMemory.objects.using(ALIAS).values_list("title", flat=True))
        self.assertNotIn("Hand written", titles)

    # -- command surface --

    def test_im_37_the_command_acknowledges_before_the_work_starts(self):
        from evennia_ai_memory import commands

        command = commands.CmdLoreImport()
        command.caller = mock.Mock()
        command.args = ""
        # The dispatch is stubbed, so nothing can complete — any message the
        # caller receives must have been sent before the work began.
        with mock.patch.object(commands, "_off_thread"):
            with mock.patch.object(
                config, "get_configured_reader", return_value=self.reader
            ):
                command.func()
        self.assertTrue(command.caller.msg.called)

    def test_im_35_the_commands_are_installed_into_a_cmdset(self):
        from evennia.commands.default.cmdset_account import AccountCmdSet

        from evennia_ai_memory.apps import install_commands
        from evennia_ai_memory.commands import CmdLoreImport, CmdLoreWipe

        install_commands()
        cmdset = AccountCmdSet()
        cmdset.at_cmdset_creation()
        installed = {type(cmd) for cmd in cmdset.commands}
        self.assertIn(CmdLoreImport, installed)
        self.assertIn(CmdLoreWipe, installed)

    def test_im_36_installing_twice_does_not_duplicate_them(self):
        from evennia.commands.default.cmdset_account import AccountCmdSet

        from evennia_ai_memory.apps import install_commands
        from evennia_ai_memory.commands import CmdLoreImport

        install_commands()
        install_commands()
        cmdset = AccountCmdSet()
        cmdset.at_cmdset_creation()
        imports = [c for c in cmdset.commands if isinstance(c, CmdLoreImport)]
        self.assertEqual(len(imports), 1)

    def test_im_26_the_import_command_is_superuser_only(self):
        from evennia_ai_memory.commands import CmdLoreImport

        self.assertIn("superuser", CmdLoreImport.locks)

    def test_im_27_both_phases_run_off_the_reactor(self):
        import inspect

        from evennia_ai_memory import commands

        # The dispatch lives in a module-level helper both phases share, so
        # look at the module rather than the class, and assert both phases
        # reach it.
        self.assertIn("run_async", inspect.getsource(commands))
        self.assertEqual(
            inspect.getsource(commands.CmdLoreImport).count("_off_thread("), 2
        )

    def test_im_28_worker_connections_are_closed(self):
        import inspect

        from evennia_ai_memory import commands

        self.assertIn("close_all", inspect.getsource(commands))

    def test_im_29_the_report_reaches_the_caller_in_one_batch(self):
        import inspect

        from evennia_ai_memory import commands

        source = inspect.getsource(commands.CmdLoreImport)
        self.assertEqual(source.count("self.caller.msg("), 1)

    def test_im_30_the_report_gives_all_four_outcomes(self):
        report = self.run_import()
        for field in ("created", "updated", "unchanged", "removed"):
            self.assertTrue(hasattr(report, field), field)

    def test_im_31_a_dry_run_changes_nothing(self):
        self.plan()
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 0)


# ── WP — the lore wipe command ───────────────────────────────────────


class LoreWipeTests(MemoryTestCase):
    def test_wp_01_the_wipe_command_is_superuser_only(self):
        from evennia_ai_memory.commands import CmdLoreWipe

        self.assertIn("superuser", CmdLoreWipe.locks)

    def test_wp_02_it_prompts_for_confirmation(self):
        import inspect

        from evennia_ai_memory import commands

        self.assertIn("get_input", inspect.getsource(commands.CmdLoreWipe))

    def test_wp_03_anything_but_yes_leaves_the_table_untouched(self):
        from evennia_ai_memory import commands

        make_lore()
        for answer in ("", "n", "no", "maybe", "yep", "Y E S"):
            self.assertFalse(commands.confirmed(answer), answer)
        self.assertTrue(commands.confirmed("yes"))
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 1)

    def test_wp_04_confirmation_removes_every_row_and_reports_the_count(self):
        make_lore(title="One", source="a.yaml")
        make_lore(title="Two", source="b.yaml")
        self.assertEqual(lore_import.wipe(), 2)
        self.assertEqual(LoreMemory.objects.using(ALIAS).count(), 0)

    def test_wp_05_it_touches_lore_only(self):
        make_lore()
        make_memory(npc_uuid=self.npc, pc_uuid=self.speaker)
        lore_import.wipe()
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 1)


# ── BE — backend dispatch ────────────────────────────────────────────


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
        # A literal, not the cascade's own constant: the point of the case is
        # that this environment variable is *not* consulted here.
        with mock.patch.dict(os.environ, {"DATABASE_URL": "mysql://user@host/db"}):
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


# ── DS — the database spec ───────────────────────────────────────────


class DatabaseSpecTests(unittest.TestCase):
    """The declaration evennia-database-cascade derives everything from.

    No database and no Evennia: a spec is data, read straight off the module.
    """

    def test_ds_01_the_spec_names_the_config_alias(self):
        self.assertEqual(db_spec.SPEC.app_labels, ("evennia_ai_memory",))
        self.assertEqual(db_spec.SPEC.alias, config.AI_MEMORY_ALIAS)

    def test_ds_02_the_spec_allows_the_shared_rung(self):
        self.assertTrue(db_spec.SPEC.allow_sharing_common_db)

    def test_ds_03_the_spec_refuses_foreign_tables(self):
        self.assertFalse(db_spec.SPEC.allow_foreign_tables_in_own_db)

    def test_ds_04_the_spec_requires_the_vector_extension(self):
        self.assertIn("vector", tuple(db_spec.SPEC.required_extensions))

    def test_ds_05_the_spec_imports_nothing_from_django(self):
        source = library_source()["db_spec.py"]
        self.assertNotIn("django", source)

    def test_ds_06_the_library_declares_no_router_and_no_databases_entry(self):
        # Reported as a list of (file, marker) rather than through assertNotIn,
        # which would print the whole offending module as the failure message.
        found = [
            f"{name}: {marker}"
            for name, source in library_source().items()
            for marker in ("db_for_read", "allow_migrate", "DATABASES[", "dj_database_url")
            if marker in source
        ]
        self.assertEqual(found, [])

    def test_ds_07_the_spec_passes_the_cascade_validator(self):
        from evennia_database_cascade import spec_is_valid

        self.assertTrue(spec_is_valid(db_spec.SPEC))


# ── LG — logging ─────────────────────────────────────────────────────


class LoggingTests(MemoryTestCase):
    def test_lg_01_the_shim_binds_and_a_call_returns_none(self):
        from evennia_ai_memory import log

        self.assertIsNone(log.ai_memory_log("scaffold check"))

    def test_lg_02_a_dropped_write_logs_the_cause(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder(RuntimeError("service unreachable"))):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        emitted = " ".join(str(call) for call in logged.call_args_list)
        self.assertIn("service unreachable", emitted)

    def test_lg_03_each_retry_and_the_final_drop_are_logged(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertGreaterEqual(
            len(logged.call_args_list), services.WRITE_ATTEMPTS
        )

    def test_lg_06_a_read_that_could_not_embed_is_logged(self):
        with mock.patch.object(services, "_embed_once", side_effect=RaisingEmbedder()):
            with mock.patch.object(services, "ai_memory_log") as logged:
                services.search_memories(self.npc, self.speaker, "anything")
        self.assertTrue(logged.call_args_list)

    @override_settings(AI_MEMORY_EMBEDDING_API_KEY=None)
    def test_lg_07_a_refused_startup_is_logged_as_well_as_raised(self):
        # config.py imports the shim lazily, so the patch goes on log.py — the
        # name config reaches for at call time, not a module-scope binding.
        with mock.patch("evennia_ai_memory.log.ai_memory_log") as logged:
            with self.assertRaises(ImproperlyConfigured):
                config.check_settings()
        emitted = " ".join(str(call) for call in logged.call_args_list)
        self.assertIn(config.SETTING_API_KEY, emitted)

    def test_lg_08_a_dropped_write_is_logged_at_error_with_a_traceback(self):
        with mock.patch.object(services, "WRITE_RETRY_DELAY", 0):
            with patch_provider(RaisingEmbedder()):
                with mock.patch.object(services, "ai_memory_log") as logged:
                    services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertTrue(
            any(
                call.kwargs.get("level") == "ERROR" and call.kwargs.get("trace")
                for call in logged.call_args_list
            )
        )

    def test_lg_09_nothing_is_written_to_stdout_or_stderr(self):
        for name, source in library_source().items():
            # cli.py is exempt: it is a command-line tool, so its report to the
            # operator *is* stdout. Everything running inside the engine logs.
            if name == "cli.py":
                continue
            self.assertNotIn("print(", source, f"print in {name}")
            self.assertNotIn("sys.stdout", source, f"stdout in {name}")
            self.assertNotIn("sys.stderr", source, f"stderr in {name}")


# ── XC — cross-cutting ───────────────────────────────────────────────


class CrossCuttingTests(MemoryTestCase):
    def test_xc_14_only_the_commands_dispatch_off_the_calling_thread(self):
        # The functions are synchronous so a consumer can put a memory lookup,
        # a prompt render and a completion in one deferToThread. A library that
        # deferred internally would force a hop inside a hop. The commands are
        # the exception because they have no caller to hand the dispatch to.
        for name, source in library_source().items():
            if name == "commands.py":
                continue
            imported = " ".join(imported_names(source))
            for token in ("deferToThread", "run_async", "twisted"):
                self.assertNotIn(token, imported, f"{token} imported by {name}")

    def test_xc_13_the_standalone_validator_runs_without_evennia(self):
        # Not a boundary against Evennia — the library runs inside it. This is
        # functional: a pre-commit hook or a CI job validates a checkout with
        # no gamedir and no configured settings, so the validator cannot need
        # an engine to start.
        self.assertFalse(imports_evennia(library_source()["cli.py"]))

    def test_xc_02_public_functions_return_plain_data(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        for result in services.get_recent_memories(self.npc, self.speaker):
            self.assertIsInstance(result, dict)
            for value in result.values():
                self.assertNotIsInstance(value, NpcMemory)

    def test_xc_03_results_are_fresh_objects(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
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
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
            memories = services.search_memories(self.npc, self.speaker, "war")
        self.assertTrue(all("title" not in m for m in memories or []))

    def test_xc_06_scope_tags_arrive_as_plain_strings(self):
        with patch_embedder(StubEmbedder()):
            services.search_lore("anything", ["millholm"])

    def test_xc_07_a_default_rebuild_leaves_library_rows_intact(self):
        with patch_embedder(StubEmbedder()):
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
        self.assertEqual(NpcMemory.objects.using(ALIAS).count(), 1)
        # The rows survive a default rebuild because the spec claims this app
        # label for its own alias, which is what the cascade routes on.
        self.assertIn(NpcMemory._meta.app_label, db_spec.SPEC.app_labels)

    def test_xc_08_timestamps_are_aware_throughout(self):
        row = make_memory(npc_uuid=self.npc, pc_uuid=self.speaker)
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
            services.store_memory(self.npc, self.speaker, "Bob", "Bob and you spoke.")
            searched = services.search_memories(self.npc, self.speaker, "a")
        recent = services.get_recent_memories(self.npc, self.speaker)
        shared = set(recent[0]) - {"similarity"}
        self.assertEqual(set(searched[0]) - {"similarity"}, shared)
