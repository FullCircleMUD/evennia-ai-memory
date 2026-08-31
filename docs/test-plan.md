# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it.

**The baseline is the existing system.** The library is FCM's `src/game/ai_memory/` service module lifted
out: the same tables, the same function signatures, the same behaviour on the same rows. A consumer
should be able to delete the coupled game code, install the library, rename a few call sites, and have
everything run as before. Every case below therefore describes what the game does today — except the
ones listed under *Departures*, each of which traces to a specific discussion. A case that encodes a
change with no entry there is a defect in this plan.

## Stage 1 surface

`store_lore` and `get_recent_lore` are out of scope — see *Retired*.

```
store_memory(npc_uuid, speaker_uuid, speaker_name, user_msg, assistant_msg, interaction_type="say")
search_memories(npc_uuid, speaker_uuid, query_text, top_k=5)
get_recent_memories(npc_uuid, speaker_uuid, limit=10)
get_last_interaction_time(npc_uuid, speaker_uuid)
search_lore(query_text, scope_tags, top_k=3)
```

| Prefix | Covers |
|---|---|
| `EM` | Embedding |
| `SM` | `store_memory` |
| `MS` | `search_memories` |
| `MR` | `get_recent_memories` |
| `LI` | `get_last_interaction_time` |
| `LS` | `search_lore` |
| `SC` | Scope access rules |
| `DB` | Database resolution |
| `BE` | Backend dispatch and dual-backend equivalence |
| `RT` | Database router |
| `LG` | Logging |
| `XC` | Cross-cutting |

`CM`, `SL` and `LR` are reserved. They covered combat memory, `store_lore` and `get_recent_lore` — all
out of scope for stage 1, see *Retired*. Do not reuse those prefixes for anything else.

## Fixtures

The suite needs Django and a database, but no Evennia: the library takes identifiers and strings from
the caller and never resolves a game object.

| Fixture | Purpose |
|---|---|
| `StubEmbedder` | Deterministic `text -> list[float]`; same text always gives the same vector |
| `OrthogonalEmbedder` | Maps a small vocabulary to mutually orthogonal unit vectors, so similarity ordering is exactly predictable |
| `RaisingEmbedder` | Raises on call |
| `FlakyEmbedder` | Fails a set number of times then succeeds, for retry cases |
| `ShortEmbedder` | Returns a vector of the wrong dimension |
| `CountingEmbedder` | Records every call, for "was it called / how many times" cases |
| `make_memory(**kwargs)` | Builds an `NpcMemory` row directly, bypassing `store_memory` |
| `make_lore(**kwargs)` | Builds a `LoreMemory` row directly |
| `aged(row, delta)` | Forces `created_at` / `updated_at` to a chosen age past `auto_now_add` |

**Backend coverage.** The `_search_*_numpy` paths run on the suite's SQLite database. The
`_search_*_pgvector` paths cannot: `CosineDistance` compiles to a pgvector operator SQLite has no
answer for. Cases tagged **[pg]** require a PostgreSQL test database.

SQLite is proven first, following the substrate's `_is_postgres()` branching. PostgreSQL comes after,
and until it does the **[pg]** cases sit in the plan with empty cells — agreed, not yet covered.

## EM — embedding

The library owns the embeddings client and calls the provider itself. Configuration comes from Django
settings, read through accessors in the library's `config` module rather than by touching `settings`
directly — the pattern `evennia-shards` uses.

**The library ships no provider defaults.** Endpoint, key and model are all required settings. A
default base URL or model name would choose a provider on the consumer's behalf and bury that choice in
library code; both are provider-specific strings and neither is the library's to pick. Absent any of
the three, the app refuses to start.

`[TBD — naming: proposed `AI_MEMORY_EMBEDDING_API_KEY`, `AI_MEMORY_EMBEDDING_BASE_URL`,
`AI_MEMORY_EMBEDDING_MODEL`, following the sibling convention of prefixing by library. The game's
existing `LLM_EMBEDDING_*` names belong to its LLM layer, not here.]`

| ID | Case | Test function |
|---|---|---|
| EM-01 | The text embedded is exactly the text the library documents as the embedding source | `test_em_01_embeds_the_documented_text` |
| EM-02 | On a write, a transient failure is retried, then logged and dropped (**D4**) | `test_em_02_transient_write_failure_is_retried_then_dropped` |
| EM-03 | On a write, a permanent failure is dropped without retrying (**D4**) | `test_em_03_permanent_write_failure_is_not_retried` |
| EM-04 | A missing API key raises `ImproperlyConfigured` at startup, not at the first call | `test_em_04_missing_api_key_raises_at_startup` |
| EM-05 | The error names the setting and where to put it, rather than reporting a generic failure | `test_em_05_error_names_the_setting_and_where_to_put_it` |
| EM-06 | Embedding happens once per stored row, not once per field | `test_em_06_embeds_once_per_row` |
| EM-07 | A wrong-length vector is refused at the boundary rather than stored | `test_em_07_wrong_length_vector_is_refused` |
| EM-08 | The library holds no rate limiter and no cost tracking — asserted statically over the source tree | `test_em_08_no_rate_limiter_or_cost_tracking_in_source` |
| EM-09 | On a read, a failure is not retried — one attempt, then report (**D2**) | `test_em_09_read_failure_is_not_retried` |
| EM-10 | A missing base URL raises `ImproperlyConfigured` at startup | `test_em_10_missing_base_url_raises_at_startup` |
| EM-11 | A missing embedding model raises `ImproperlyConfigured` at startup | `test_em_11_missing_model_raises_at_startup` |
| EM-12 | Configuration is read only through the `config` accessors — no direct `settings` reads in library code, asserted statically | `test_em_12_settings_are_read_only_through_config` |
| EM-13 | A required setting present but empty is treated as missing, for all three | `test_em_13_empty_setting_counts_as_missing` |
| EM-14 | The configured base URL is the one the client is built with, so the provider is swappable | `test_em_14_configured_base_url_builds_the_client` |
| EM-15 | The library reads its own settings namespace and never the consumer's `LLM_*` names | `test_em_15_reads_its_own_settings_namespace` |
| EM-16 | No endpoint URL and no model name appear anywhere in library code — asserted statically | `test_em_16_no_provider_defaults_in_source` |

## SM — `store_memory`

| ID | Case | Test function |
|---|---|---|
| SM-01 | A stored exchange is retrievable by `get_recent_memories` | `test_sm_01_stored_exchange_is_retrievable` |
| SM-02 | The row records both UUIDs, the speaker name, both messages and the interaction type | `test_sm_02_row_records_uuids_name_messages_and_type` |
| SM-03 | The summary names the speaker but refers to the NPC in the second person, never by name (**D5**) | `test_sm_03_summary_uses_second_person_for_the_npc` |
| SM-04 | On SQLite the vector is stored as a float32 byte blob | `test_sm_04_sqlite_stores_a_float32_blob` |
| SM-05 | **[pg]** On PostgreSQL the vector is stored in `embedding_vector`, and `embedding` stays null | `test_sm_05_postgres_stores_the_vector_column` |
| SM-06 | The blob round-trips — what comes back out equals what went in, to float32 precision | `test_sm_06_blob_round_trips` |
| SM-07 | An embedding failure logs and returns without raising into the caller (**D4**) | `test_sm_07_embedding_failure_does_not_raise_into_the_caller` |
| SM-08 | A transient write failure is retried, then logged and dropped (**D4**) | `test_sm_08_transient_write_failure_is_retried_then_dropped` |
| SM-09 | A row is never written without a vector (**D4**) | `test_sm_09_never_writes_a_row_without_a_vector` |
| SM-10 | Empty `user_msg` or `assistant_msg` still stores | `test_sm_10_empty_messages_still_store` |
| SM-11 | Two identical exchanges both store — no deduplication | `test_sm_11_identical_exchanges_are_not_deduplicated` |
| SM-12 | `created_at` is set automatically and is timezone-aware | `test_sm_12_created_at_is_set_and_aware` |
| SM-13 | The row lands on the `ai_memory` alias, not `default` | `test_sm_13_row_lands_on_the_library_alias` |
| SM-14 | No NPC name is stored — the model carries the speaker's name only (**D5**) | `test_sm_14_no_npc_name_is_stored` |

## MS — `search_memories`

| ID | Case | Test function |
|---|---|---|
| MS-01 | Returns the semantically nearest memories first | `test_ms_01_nearest_memories_come_first` |
| MS-02 | Returns at most `top_k` | `test_ms_02_returns_at_most_top_k` |
| MS-03 | Fewer than `top_k` matches returns all of them, not an error | `test_ms_03_fewer_matches_than_top_k_returns_all` |
| MS-04 | No memories for the pair returns `[]` | `test_ms_04_no_memories_returns_empty_list` |
| MS-05 | Each result carries summary, both messages, similarity, `created_at` and speaker name | `test_ms_05_result_carries_the_documented_keys` |
| MS-06 | Both UUIDs are required — results are always scoped to the pair (**D3**) | `test_ms_06_both_uuids_are_required` |
| MS-07 | Rows with no embedding are skipped, not ranked as zero | `test_ms_07_rows_without_an_embedding_are_skipped` |
| MS-08 | A stored vector of a different dimension is skipped rather than raising | `test_ms_08_wrong_dimension_row_is_skipped_not_raised` |
| MS-09 | `similarity` is in `[-1.0, 1.0]` and is 1.0 for an exact text match | `test_ms_09_similarity_is_bounded_and_exact_for_a_match` |
| MS-10 | Another NPC's memories with the same speaker are excluded | `test_ms_10_another_npcs_memories_are_excluded` |
| MS-11 | A UUID matches exactly — a near-miss returns nothing, and there is no name fallback (**D3**) | `test_ms_11_uuid_matches_exactly_with_no_name_fallback` |
| MS-12 | Retired — see *Departures* D3 | — |
| MS-13 | Retired — see *Departures* D3 | — |
| MS-14 | A failed embedding returns `None`, distinct from `[]`, with no recency substitution (**D2**) | `test_ms_14_failed_embedding_returns_none_not_empty` |
| MS-15 | `top_k=0` returns `[]` | `test_ms_15_top_k_zero_returns_empty_list` |
| MS-16 | **[pg]** pgvector path returns the same ordering as the numpy path for the same corpus | `test_ms_16_backends_agree_on_ordering` |
| MS-17 | Ties in similarity produce a deterministic order | `test_ms_17_ties_are_ordered_deterministically` |

## MR — `get_recent_memories`

| ID | Case | Test function |
|---|---|---|
| MR-01 | Returns the most recent `limit` memories for the pair | `test_mr_01_returns_the_most_recent_limit` |
| MR-02 | Results are ordered oldest first, having selected the newest `limit` | `test_mr_02_selects_newest_then_orders_oldest_first` |
| MR-03 | No memories returns `[]` | `test_mr_03_no_memories_returns_empty_list` |
| MR-04 | Results carry no `similarity` key | `test_mr_04_results_carry_no_similarity` |
| MR-05 | Embeds nothing, and so cannot fail the way a search can | `test_mr_05_embeds_nothing` |
| MR-06 | Both UUIDs are required and match exactly (**D3**) | `test_mr_06_both_uuids_are_required_and_exact` |
| MR-07 | Another speaker's exchanges with the same NPC are excluded (**D3**) | `test_mr_07_another_speaker_is_excluded` |

## LI — `get_last_interaction_time`

| ID | Case | Test function |
|---|---|---|
| LI-01 | Returns the timestamp of the most recent exchange for the pair | `test_li_01_returns_the_most_recent_timestamp` |
| LI-02 | No history returns the documented empty result | `test_li_02_no_history_returns_the_empty_result` |
| LI-03 | Another speaker's memories do not satisfy the query | `test_li_03_another_speaker_does_not_satisfy_the_query` |
| LI-04 | Both UUIDs must match, and there is no name fallback (**D3**) | `test_li_04_both_uuids_must_match_with_no_name_fallback` |
| LI-05 | Returns both the timestamp and a relative-time phrase | `test_li_05_returns_a_timestamp_and_a_phrase` |
| LI-06 | The returned datetime is timezone-aware | `test_li_06_returned_datetime_is_aware` |
| LI-07 | Each relative-time band is produced at its boundary — under an hour, same day, yesterday, days, weeks, a month name, beyond a year | `test_li_07_each_relative_time_band_is_produced` |
| LI-08 | A delta beyond a year phrases as such rather than falling back to a month name | `test_li_08_beyond_a_year_does_not_fall_back_to_a_month` |

## LS — `search_lore`

| ID | Case | Test function |
|---|---|---|
| LS-01 | Returns the semantically nearest accessible entries first | `test_ls_01_nearest_admitted_entries_come_first` |
| LS-02 | Returns at most `top_k` | `test_ls_02_returns_at_most_top_k` |
| LS-03 | Each result carries title, content, scope level and similarity | `test_ls_03_result_carries_the_documented_keys` |
| LS-04 | An entry the caller's tags do not admit never appears, however similar | `test_ls_04_inadmissible_entry_never_appears` |
| LS-05 | Entries with an empty tag list are returned to a caller passing no tags | `test_ls_05_untagged_entries_reach_a_caller_with_no_tags` |
| LS-06 | Entries with no embedding are skipped | `test_ls_06_entries_without_an_embedding_are_skipped` |
| LS-07 | A wrong-dimension stored vector is skipped rather than raising | `test_ls_07_wrong_dimension_entry_is_skipped_not_raised` |
| LS-08 | Empty corpus returns `[]` | `test_ls_08_empty_corpus_returns_empty_list` |
| LS-09 | A failed embedding returns `None`, distinct from `[]`, with no recency substitution (**D2**) | `test_ls_09_failed_embedding_returns_none_not_empty` |
| LS-10 | **[pg]** Inadmissible entries occupying the nearest ranks do not starve the result (**D1**) | `test_ls_10_inadmissible_entries_do_not_starve_the_result` |
| LS-11 | **[pg]** pgvector and numpy paths return the same entries in the same order for the same corpus | `test_ls_11_backends_agree_on_entries_and_order` |
| LS-12 | A result set smaller than `top_k` because of tag filtering is returned, not padded | `test_ls_12_a_short_result_is_returned_not_padded` |
| LS-13 | Takes no speaker — lore is scoped by tags, never by who is asking | `test_ls_13_takes_no_speaker` |

## SC — scope access rules

The rule under test: an entry's tags are an **AND** requirement — a row is returned only when every tag
it carries is in the list the caller passed. A row tagged `["millholm", "mages_guild"]` reaches a caller
holding both and not one holding only the first. Rows say who may know them; callers say what they are
part of; return where the first is contained in the second.

`scope_level` sits alongside the tags: it is stored, indexed, returned in results, and carries the
`continental` term in the SQL pre-filter. The Python access rule reads tags only.

| ID | Case | Test function |
|---|---|---|
| SC-01 | Empty entry tags are accessible to everyone | `test_sc_01_empty_entry_tags_reach_everyone` |
| SC-02 | Empty entry tags are accessible to a caller passing no tags | `test_sc_02_empty_entry_tags_reach_a_caller_with_none` |
| SC-03 | Single matching tag grants access | `test_sc_03_single_matching_tag_grants_access` |
| SC-04 | Single non-matching tag denies access | `test_sc_04_single_non_matching_tag_denies_access` |
| SC-05 | Two entry tags with only one held denies access | `test_sc_05_two_entry_tags_with_one_held_denies_access` |
| SC-06 | Two entry tags with both held grants access | `test_sc_06_two_entry_tags_with_both_held_grants_access` |
| SC-07 | A caller holding a superset of the entry's tags is granted access | `test_sc_07_a_superset_of_holder_tags_grants_access` |
| SC-08 | Tag comparison is exact — case and whitespace are significant | `test_sc_08_comparison_is_exact` |
| SC-09 | Duplicate tags on either side do not change the answer | `test_sc_09_duplicates_do_not_change_the_answer` |
| SC-10 | Tag order does not change the answer | `test_sc_10_order_does_not_change_the_answer` |
| SC-11 | Tags compare by equality and set membership — the library imposes no type, as the game does not | `test_sc_11_tags_compare_by_equality_with_no_type_imposed` |
| SC-12 | The SQL filter is never restrictive — it may admit rows the rule rejects, never exclude ones it would admit | `test_sc_12_the_sql_filter_is_never_restrictive` |
| SC-13 | **[pg]** On PostgreSQL the filter is exact, so ranking only ever sees admissible rows (**D1**) | `test_sc_13_the_query_expresses_the_tag_rule_itself` |
| SC-14 | `scope_level` is stored and returned unchanged, and does not decide access | `test_sc_14_scope_level_is_stored_and_returned_but_does_not_gate` |
| SC-15 | A row with empty tags is returned whatever its `scope_level` | `test_sc_15_empty_tags_are_admitted_whatever_the_level` |

## DB — database resolution

`ai_memory_database(sqlite_path)` builds the consumer's `DATABASES` entry, called from their settings.
Three rungs, in order: `DATABASE_URL_AI_MEMORY`, then `DATABASE_URL`, then a SQLite file. The same
shape `evennia-message-bus` uses, so a consumer configuring both configures them the same way.

Which rung is right depends on something the library cannot see, so it does not guess and does not
warn. `describe_ai_memory_database()` puts the answer in the startup log instead, where it can be read
and compared. Rung two puts memories in the game's database, where a rebuild of that database destroys
them — the outcome a separate alias otherwise prevents.

| ID | Case | Test function |
|---|---|---|
| DB-01 | The library's own URL resolves to a database of its own | `test_db_01_own_url_resolves_to_its_own_database` |
| DB-02 | With only the game's URL set, the memories share the game's database | `test_db_02_game_url_is_the_second_rung` |
| DB-03 | With neither set, it falls back to the SQLite path given | `test_db_03_neither_set_falls_back_to_sqlite` |
| DB-04 | The library's own URL wins when both are set | `test_db_04_own_url_wins_over_the_game_url` |
| DB-05 | The description names the database and the rung that produced it | `test_db_05_description_names_the_database_and_the_rung` |
| DB-06 | The description carries no credentials | `test_db_06_description_reports_no_credentials` |
| DB-07 | A SQLite path is reported resolved, so processes sharing a symlinked file agree | `test_db_07_a_sqlite_path_is_reported_resolved` |
| DB-08 | Sharing the game's database is named as such in the description | `test_db_08_sharing_the_game_database_is_named_as_such` |

## BE — backend dispatch

| ID | Case | Test function |
|---|---|---|
| BE-01 | A SQLite alias selects the numpy path | `test_be_01_sqlite_alias_selects_the_numpy_path` |
| BE-02 | **[pg]** A PostgreSQL alias selects the pgvector path | `test_be_02_postgres_alias_selects_the_pgvector_path` |
| BE-03 | Backend detection reads the library's own alias, not `default` | `test_be_03_detection_reads_the_library_alias` |
| BE-04 | Backend selection reads the resolved engine, not the environment — a non-Postgres URL does not select the pgvector path | `test_be_04_selection_reads_the_engine_not_the_environment` |
| BE-05 | Cosine similarity of a vector with itself is 1.0 | `test_be_05_self_similarity_is_one` |
| BE-06 | Cosine similarity of orthogonal vectors is 0.0 | `test_be_06_orthogonal_similarity_is_zero` |
| BE-07 | A zero vector yields 0.0 rather than dividing by zero | `test_be_07_zero_vector_does_not_divide_by_zero` |
| BE-08 | Similarity is symmetric | `test_be_08_similarity_is_symmetric` |

## RT — database router

| ID | Case | Test function |
|---|---|---|
| RT-01 | Reads of the library's models route to its own alias | `test_rt_01_reads_route_to_the_library_alias` |
| RT-02 | Writes of the library's models route to its own alias | `test_rt_02_writes_route_to_the_library_alias` |
| RT-03 | Another app's model returns `None` for read and for write, so a sibling router gets its say | `test_rt_03_foreign_models_return_none` |
| RT-04 | Relations between two of the library's models are allowed | `test_rt_04_relations_between_own_models_are_allowed` |
| RT-05 | A relation involving a foreign model returns `None` | `test_rt_05_relations_involving_a_foreign_model_return_none` |
| RT-06 | The library's migrations apply only on its own alias | `test_rt_06_own_migrations_apply_only_on_the_library_alias` |
| RT-07 | Another app's migrations are refused on the library's alias | `test_rt_07_foreign_migrations_are_refused_on_the_library_alias` |
| RT-08 | Another app's migrations on another alias return `None` | `test_rt_08_foreign_migrations_elsewhere_return_none` |
| RT-09 | Co-installed with a second router claiming a different app, neither captures the other's models | `test_rt_09_a_sibling_router_is_not_captured` |

## LG — logging

Every line goes to the library's own `ai_memory.log`, under the running instance's `LOG_DIR` beside
`server.log`, through a shim over Evennia's `logger.log_file`. Diagnosing a dropped memory or an
embedding outage is then one file rather than a search through the main server log. The shim is the
pattern `evennia-shards` and `evennia-message-bus` use, and outside an Evennia engine it is a silent
no-op, so the suite needs no log directory.

| ID | Case | Test function |
|---|---|---|
| LG-01 | Lines go to the library's own `ai_memory.log`, not Evennia's main log | `test_lg_01_lines_go_to_the_libraries_own_log_file` |
| LG-02 | A dropped write logs the cause, not just that something failed | `test_lg_02_a_dropped_write_logs_the_cause` |
| LG-03 | Each retry attempt is logged, and so is the final drop | `test_lg_03_each_retry_and_the_final_drop_are_logged` |
| LG-04 | An unknown level degrades to INFO — a log call never raises into the caller | `test_lg_04_an_unknown_level_degrades_rather_than_raising` |
| LG-05 | The shim is a silent no-op outside an Evennia engine, so tests need no log directory | `test_lg_05_the_shim_is_a_no_op_outside_an_evennia_engine` |
| LG-06 | A read that could not embed is logged, so an outage is visible to an operator | `test_lg_06_a_read_that_could_not_embed_is_logged` |
| LG-07 | A refused startup logs the missing setting as well as raising | `test_lg_07_a_refused_startup_is_logged_as_well_as_raised` |
| LG-08 | A dropped write is logged at ERROR with the traceback attached | `test_lg_08_a_dropped_write_is_logged_at_error_with_a_traceback` |
| LG-09 | Nothing is written to stdout or stderr directly | `test_lg_09_nothing_is_written_to_stdout_or_stderr` |

## XC — cross-cutting

| ID | Case | Test function |
|---|---|---|
| XC-01 | Only the log shim imports Evennia — every other module is framework-neutral, asserted statically | `test_xc_01_only_the_log_shim_imports_evennia` |
| XC-02 | Every public function returns plain data — no model instances, no querysets, no formatted prose | `test_xc_02_public_functions_return_plain_data` |
| XC-03 | A search result is a new object each call; mutating it does not affect stored rows | `test_xc_03_results_are_fresh_objects` |
| XC-04 | Every public function is synchronous and returns rather than dispatching | `test_xc_04_public_functions_are_synchronous` |
| XC-05 | Interaction and lore searches are independent — a row of one kind never appears in the other's results | `test_xc_05_memory_and_lore_searches_are_independent` |
| XC-06 | Scope tags reach the library as a plain list of strings; the library resolves nothing | `test_xc_06_scope_tags_arrive_as_plain_strings` |
| XC-07 | A rebuild of the consumer's `default` database leaves the library's rows intact | `test_xc_07_a_default_rebuild_leaves_library_rows_intact` |
| XC-08 | Timestamps are timezone-aware throughout | `test_xc_08_timestamps_are_aware_throughout` |
| XC-09 | The package installs and the runner reaches it | `test_version` |
| XC-10 | The library is registered as a Django app | `test_app_installed` |
| XC-11 | The library's own database alias is configured | `test_ai_memory_alias_configured` |
| XC-12 | Every read returns the same result shape whichever path it took | `test_xc_12_every_read_returns_one_shape` |

## Departures

Everything else in this plan replicates the game's current behaviour. The entries below do not, and
each traces to a decision taken in discussion. Nothing may be added here without one.

**D1. Lore filtering happens before ranking, on both backends.** Today the two disagree: SQLite applies
the tag rule to every row and then ranks; PostgreSQL ranks first, takes `top_k * 3` as headroom, and
applies the rule inside that window — so rows the caller's tags don't admit can occupy every slot and
starve a result that qualifying rows would have filled. There is no single existing behaviour to
replicate, so one had to be chosen. The SQLite behaviour wins because it is what the lore design
describes. Covers LS-10, SC-12, SC-13.

**D2. A read that cannot embed reports it, and does not retry.** To search, the query text has to become
a vector, which is a call out to the embedding service. When that call fails there is nothing to search
with. Today the library quietly runs a recency query instead and returns the result as though the search
had worked — different shape, different ordering, and on the memory side the speaker filter is dropped
so another speaker's rows come back. The library instead returns `None`: `None` means "could not
search", `[]` means "searched, found nothing". The caller decides what to do about it — a read has
someone waiting on it, so there is no retry either. Covers MS-14, LS-09, EM-09, LG-06.

**D3. Rows are keyed by UUID.** Every entity that holds or appears in a memory carries a UUID, unique
and stable across instances and rebuilds. The caller supplies it, the library matches it exactly, and
both UUIDs are required on every memory read — a memory is the history between one NPC and one speaker,
so the pair is the scope.

This replaces an id-and-name pair with a conditional between them. Today a row carries an Evennia dbref
and an object key; a search filters on the dbref and falls back to the key only when the dbref query
returns nothing. The dbref is a bare integer with nothing anchoring it — a rebuild reassigns it from a
restarted sequence — and the fallback stops firing as soon as one row exists under the new dbref. A
UUID has neither problem. Covers MS-06, MS-11, MR-06, MR-07, LI-04; retires MS-12 and MS-13.

**D4. A write retries a transient failure, then logs and drops it.** Today an embedding failure is
swallowed and the row is written anyway with no vector — stored, and unreachable by any search. The
library retries what can succeed on a retry, drops a permanent failure immediately, logs either way,
never raises into the caller, and never writes a row it cannot return. Writes are dispatched off the
reactor with nothing waiting on them, which is what makes retrying affordable here and not on a read.
Covers SM-07 to SM-09, EM-02, EM-03.

**D5. The summary is written in the second person, and no NPC name is stored.** Today it reads
`Bob said: "…" | Bron replied: "…"`. It becomes `Bob said: "…" | You replied: "…"`, because the summary
is a prompt input for that NPC and second person is how it will be read. The NPC's name then has no
reader — it was never returned in results, and D3 removes the name fallback that was its other use — so
it goes from the signature and the model. The speaker's name stays: it is in the summary and it comes
back in every result. Covers SM-03, SM-14.

## Open decisions

None. Every case above is agreed and can be written.

The relative-time phrase from `get_last_interaction_time` stays: it exists so an NPC can greet a
returning player differently from a stranger, or from someone who was standing there a minute ago, and
the phrasing is tuned for that rather than for display. The caller discards the timestamp and uses only
the phrase and whether there was any history at all.

Questions that do not block a case — embedding dimensions, migration squashing, the lore importer,
`contrib/` — are listed under *Out of scope* in [../CLAUDE.md](../CLAUDE.md).

## Retired

**Combat memory (`CM`).** Out of scope: the substrate has a `CombatMemory` model and migrations but no
service and no caller, and the schema will change once there is a strategy bot to serve. `[TBD — needs
discussion: whether combat memory later lands in this library or in one of its own.]`

**`store_lore` (`SL`).** Out of scope for stage 1. Nothing in the game calls it — lore is written only
by the standalone importer in the lore content repo, which talks to the table directly. The importer
stays where it is, so `search_lore` is the only function that touches lore in stage 1. The `LoreMemory`
model and its migrations still ship, because something has to create the table the importer writes to.
Bringing the importer in, with the validator that gates an import and the `evennia-yaml-reader`
dependency that follows, is stage 2.

**`get_recent_lore` (`LR`).** Dropped. Its only job was being the fallback D2 removes, and "the most
recently updated lore" is not a useful answer to "what does this NPC know about the great war" — lore is
not time-ordered the way an interaction history is.

Prefixes stay reserved so the IDs are never reused.

## Settled

Properties the library carries over from the game unchanged, each pinned by a case:

- Two tables in one database of their own, behind the library's router (RT block, XC-07).
- Retrieval returns plain data, never prompt text (XC-02).
- Lore is scoped by tags on the row against tags supplied by the caller, and never by who is asking
  (SC block, LS-13).
- Scope tags arrive as a plain list of strings the library never resolves (XC-06).
- Every function is synchronous; the consumer owns the dispatch (XC-04).
- The library logs to its own named logger (LG block).
- No rate limiting and no cost tracking; a consumer caps spend with a budgeted API key and reads usage
  from the provider's dashboard (EM-08).
