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

## Surface

**Stage 1 — the functions.** Implemented; the cases below carry their tests.

```
store_memory(npc_uuid, speaker_uuid, speaker_name, user_msg, assistant_msg, interaction_type="say")
search_memories(npc_uuid, speaker_uuid, query_text, top_k=5)
get_recent_memories(npc_uuid, speaker_uuid, limit=10)
get_last_interaction_time(npc_uuid, speaker_uuid)
store_lore(title, content, scope_level, scope_tags, source="")
search_lore(query_text, scope_tags, top_k=3)
```

**Stage 2 — the lore commands.** Agreed, not yet written. The library gains two superuser commands and,
with them, real Evennia coupling: `Command`, and a cmdset patch at `ready()`, following
`evennia-world-builder`'s `wb_build`.

| Prefix | Covers |
|---|---|
| `EM` | Embedding |
| `SM` | `store_memory` |
| `MS` | `search_memories` |
| `MR` | `get_recent_memories` |
| `LI` | `get_last_interaction_time` |
| `SL` | `store_lore` |
| `LS` | `search_lore` |
| `SC` | Scope access rules |
| `IM` | The lore import command |
| `WP` | The lore wipe command |
| `DB` | Database resolution |
| `BE` | Backend dispatch and dual-backend equivalence |
| `RT` | Database router |
| `LG` | Logging |
| `XC` | Cross-cutting |

`CM` and `LR` are reserved. They covered combat memory and `get_recent_lore`, both out of scope — see
*Retired*. Do not reuse those prefixes for anything else.

## Fixtures

The suite bootstraps Django and Evennia against two in-memory databases, and needs no gamedir. It builds
no rooms, mobs or characters: the library takes identifiers and strings from the caller and never
resolves a game object, so a fixture is a UUID and a vector rather than a world.

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

The settings are `AI_MEMORY_EMBEDDING_BASE_URL`, `AI_MEMORY_EMBEDDING_API_KEY` and
`AI_MEMORY_EMBEDDING_MODEL`, prefixed by library as the siblings are. The game's existing
`LLM_EMBEDDING_*` names belong to its LLM layer, not here — EM-15 keeps them out.

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
| EM-17 | Every exception type the permanent-failure classification names exists in the installed SDK | `test_em_17_permanent_error_types_exist_in_the_installed_sdk` |

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

## SL — `store_lore`

The idempotent upsert the import command sits on, keyed on `(source, title)`. Lifted from the standalone
importer in the lore content repo, which used raw SQL against the table and carried a comment warning
that its column list had to be kept in sync with the model by hand. Going through the ORM removes that.

| ID | Case | Test function |
|---|---|---|
| SL-01 | A new entry is created and reports `"created"` | `test_sl_01_a_new_entry_is_created` |
| SL-02 | Re-storing identical content reports `"unchanged"` and embeds nothing | `test_sl_02_identical_content_is_unchanged_and_embeds_nothing` |
| SL-03 | Changed content reports `"updated"` and re-embeds | `test_sl_03_changed_content_is_updated_and_re_embedded` |
| SL-04 | Changed `scope_level` alone reports `"updated"` | `test_sl_04_changed_scope_level_alone_is_an_update` |
| SL-05 | Changed `scope_tags` alone reports `"updated"` | `test_sl_05_changed_scope_tags_alone_is_an_update` |
| SL-06 | Identity is `(source, title)` — the same title under a different source is a separate entry | `test_sl_06_the_same_title_under_another_source_is_a_separate_entry` |
| SL-07 | The same `(source, title)` twice does not create a duplicate row | `test_sl_07_the_same_source_and_title_never_duplicates` |
| SL-08 | A re-embed that fails leaves the existing vector in place rather than nulling it (**D4**) | `test_sl_08_a_failed_re_embed_leaves_the_stored_vector` |
| SL-09 | An infrastructure failure on the update path retries, then logs and drops (**D4**) | `test_sl_09_an_update_failure_retries_then_logs_and_drops` |
| SL-10 | An infrastructure failure on the create path retries, then logs and drops (**D4**) | `test_sl_10_a_create_failure_retries_then_logs_and_drops` |
| SL-11 | Empty `scope_tags` stores as reachable by everyone | `test_sl_11_empty_scope_tags_are_reachable_by_everyone` |
| SL-12 | `updated_at` advances on update and not on `"unchanged"` | `test_sl_12_updated_at_advances_on_update_but_not_on_unchanged` |
| SL-13 | A bulk import embeds exactly once per new or changed entry | `test_sl_13_a_bulk_run_embeds_once_per_new_or_changed_entry` |
| SL-14 | Any `scope_level` string is accepted — the library validates no vocabulary | `test_sl_14_any_scope_level_string_is_accepted` |
| SL-15 | Create and update behave identically on the same fault (**D4**) | `test_sl_15_create_and_update_behave_alike_on_the_same_fault` |

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

## IM — the lore import command

A superuser command that reads the lore content repo, validates all of it, and brings the lore table
into line with it. The YAML is the source of truth: the table mirrors it, so an entry deleted from the
YAML is deleted from the database.

It runs in two phases with a decision between them, which is a different shape from `wb_build`'s single
`run_async`. Phase one reads, validates and works out what would change, off the reactor. The result is
reported on the reactor thread. Phase two applies it — embed, upsert, prune — off the reactor again. A
dry run is phase one alone, which is why it needs no separate logic.

The reader is resolved from settings the way `evennia-world-builder` does it, so a consumer configures
GitHub for production and a local checkout for development by the convention they already know.

A `Reader` reads a named path and cannot enumerate, so the repository declares its own contents in an
`index.yaml` at the root holding a flat list of `sources`. Flat, because lore has no hierarchy —
nothing like world-builder's `definitions.yaml` and per-folder indexes is warranted. The manifest is
the source of truth for what belongs: a file it does not name is not read, and a file it names but
which is absent stops the run. Enumeration could not tell that second case from a file that never
existed.

| ID | Case | Test function |
|---|---|---|
| IM-01 | The command reads through the configured reader | `test_im_01_the_command_reads_through_the_configured_reader` |
| IM-02 | A missing repo or ref is an error naming the settings that select the reader | `test_im_02_a_missing_repo_names_the_reader_settings` |
| IM-03 | A rejected token reports as an auth failure, distinctly from "not found" | `test_im_03_a_rejected_token_reports_as_an_auth_failure` |
| IM-04 | The standalone validator always reads locally, whatever the setting says | `test_im_04_the_standalone_validator_always_reads_locally` |
| IM-05 | Every file the manifest names is read | `test_im_05_every_file_the_manifest_names_is_read` |
| IM-06 | A manifest naming a file that is not there refuses the run, naming it | `test_im_06_a_manifest_naming_an_absent_file_refuses` |
| IM-32 | A missing manifest is an error naming the file the command expected | `test_im_32_a_missing_manifest_names_the_expected_file` |
| IM-33 | A manifest that is malformed, or has no `sources`, is an error | `test_im_33_a_malformed_manifest_is_an_error` |
| IM-34 | A file present in the repository but absent from the manifest is not read | `test_im_34_a_file_the_manifest_omits_is_not_read` |
| IM-07 | A read that succeeds but resolves zero entries refuses, and changes nothing | `test_im_07_a_read_resolving_no_entries_refuses` |
| IM-08 | That refusal names where it looked, and points at the wipe command for the deliberate case | `test_im_08_that_refusal_points_at_the_wipe_command` |
| IM-09 | One invalid entry anywhere means nothing at all is written | `test_im_09_one_invalid_entry_writes_nothing` |
| IM-10 | A missing required field is refused, naming the file and the title | `test_im_10_a_missing_field_names_the_file_and_title` |
| IM-11 | Malformed YAML is refused, naming the file | `test_im_11_malformed_yaml_names_the_file` |
| IM-12 | A `scope_tags` that is not a list is refused | `test_im_12_scope_tags_that_are_not_a_list_are_refused` |
| IM-13 | Two entries sharing a title within one source are refused — they would collide on the unique constraint | `test_im_13_a_duplicate_title_within_one_source_is_refused` |
| IM-14 | Validation checks shape, not vocabulary: an unrecognised `scope_level` passes | `test_im_14_an_unrecognised_scope_level_passes_validation` |
| IM-15 | Every problem is reported in one pass, not just the first | `test_im_15_every_problem_is_reported_in_one_pass` |
| IM-16 | A new entry is created and reported created | `test_im_16_a_new_entry_is_created_and_reported` |
| IM-17 | An unchanged entry is skipped and embeds nothing | `test_im_17_an_unchanged_entry_is_skipped_and_embeds_nothing` |
| IM-18 | A changed entry is updated and re-embedded | `test_im_18_a_changed_entry_is_updated_and_re_embedded` |
| IM-19 | Identity is `(source, title)` throughout | `test_im_19_identity_is_source_and_title` |
| IM-20 | A run interrupted by an infrastructure failure completes on re-run, skipping what landed | `test_im_20_an_interrupted_run_completes_on_re_run` |
| IM-21 | An entry in the database but absent from the imported YAML is removed | `test_im_21_an_entry_absent_from_the_yaml_is_removed` |
| IM-22 | An entry removed from a file that still exists is treated the same as one whose whole file went | `test_im_22_a_removed_entry_and_a_removed_file_are_treated_alike` |
| IM-23 | Removals are named in the report, not merely counted | `test_im_23_removals_are_named_not_merely_counted` |
| IM-24 | A run refused at validation removes nothing, exactly as it writes nothing | `test_im_24_a_refused_run_removes_nothing` |
| IM-25 | A row whose `(source, title)` appears in no YAML file is removed whatever produced it | `test_im_25_a_row_no_yaml_claims_is_removed_whatever_made_it` |
| IM-26 | Superuser only | `test_im_26_the_import_command_is_superuser_only` |
| IM-27 | Both phases run off the reactor; play continues while an import is running | `test_im_27_both_phases_run_off_the_reactor` |
| IM-28 | Database connections opened on a worker are closed there | `test_im_28_worker_connections_are_closed` |
| IM-29 | The report reaches the caller on the reactor thread, in one batch | `test_im_29_the_report_reaches_the_caller_in_one_batch` |
| IM-30 | The report gives created, updated, unchanged and removed | `test_im_30_the_report_gives_all_four_outcomes` |
| IM-31 | A dry run stops after phase one and changes nothing | `test_im_31_a_dry_run_changes_nothing` |

IM-07 is load-bearing rather than tidy. With the table mirroring the YAML, an empty read is the one
thing standing between a mis-set path or a half-finished fetch and an empty lore table. IM-25 is the
consequence worth being sure of: a row nobody's YAML claims is stale by definition, so lore cannot be
hand-inserted into the database and survive the next import.

## WP — the lore wipe command

Emptying the lore table is a separate command so that it has to be named, rather than arrived at as a
side effect of an import that read the wrong path. It is safe because the lore table is derived data:
the YAML is the original, and an import restores it.

| ID | Case | Test function |
|---|---|---|
| WP-01 | Superuser only | `test_wp_01_the_wipe_command_is_superuser_only` |
| WP-02 | Prompts for confirmation, defaulting to no | `test_wp_02_it_prompts_for_confirmation` |
| WP-03 | Anything but an explicit yes leaves the table untouched — a bare return, `n`, or an unrecognised answer | `test_wp_03_anything_but_yes_leaves_the_table_untouched` |
| WP-04 | On confirmation every lore row is removed, and the count reported | `test_wp_04_confirmation_removes_every_row_and_reports_the_count` |
| WP-05 | It touches lore only — memories are a different table and are never affected | `test_wp_05_it_touches_lore_only` |

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
| DB-09 | Startup writes the resolved database to the log, so two instances can be compared | `test_db_09_startup_names_the_resolved_database` |

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
| XC-01 | Retired — see *Retired* | — |
| XC-02 | Every public function returns plain data — no model instances, no querysets, no formatted prose | `test_xc_02_public_functions_return_plain_data` |
| XC-03 | A search result is a new object each call; mutating it does not affect stored rows | `test_xc_03_results_are_fresh_objects` |
| XC-04 | Every public function is synchronous and returns rather than dispatching | `test_xc_04_public_functions_are_synchronous` |
| XC-14 | Only the commands dispatch off the calling thread — nothing in the data layer reaches for one | `test_xc_14_only_the_commands_dispatch_off_the_calling_thread` |
| XC-05 | Interaction and lore searches are independent — a row of one kind never appears in the other's results | `test_xc_05_memory_and_lore_searches_are_independent` |
| XC-06 | Scope tags reach the library as a plain list of strings; the library resolves nothing | `test_xc_06_scope_tags_arrive_as_plain_strings` |
| XC-07 | A rebuild of the consumer's `default` database leaves the library's rows intact | `test_xc_07_a_default_rebuild_leaves_library_rows_intact` |
| XC-08 | Timestamps are timezone-aware throughout | `test_xc_08_timestamps_are_aware_throughout` |
| XC-09 | The package installs and the runner reaches it | `test_version` |
| XC-10 | The library is registered as a Django app | `test_app_installed` |
| XC-11 | The library's own database alias is configured | `test_ai_memory_alias_configured` |
| XC-12 | Every read returns the same result shape whichever path it took | `test_xc_12_every_read_returns_one_shape` |
| XC-13 | The standalone validator runs without an Evennia engine, so a pre-commit hook or CI job can validate a checkout | `test_xc_13_the_standalone_validator_runs_without_evennia` |

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
service and no caller, and the schema will change once there is a strategy bot to serve. A body of work
in its own right, whenever it is started.

**"The library imports no Evennia" (`XC-01`).** Retired. It asserted a boundary that was never the
boundary. Evennia is the platform the library runs on and will only ever run on, so using its core
infrastructure — a `Command`, a cmdset, the logger — costs nothing and defends nothing. What the library
must not own is what the **consumer** defines: rooms, mobs, typeclasses, factions, the vocabulary of a
particular game. That is a matter of judgement about what belongs where, and no import check can stand
in for it.

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
