# SPDX-License-Identifier: BSD-3-Clause
"""The database alias this library declares to evennia-database-cascade.

The cascade derives the ``DATABASES`` entry, the router and the migration list
from this declaration — the library ships no router and no resolution code of
its own.

Both ``allow_`` flags are left at their defaults, and each is a decision.
Sharing the common database is allowed because nothing here shares a table
name with the framework, so a single-instance game pointing this alias at its
own database gets a second set of tables rather than Evennia's; what it loses
is the memories when it rebuilds, which is its call to make. Foreign tables
are refused because these two tables are all that belongs here.

``vector`` is required because the embedding columns are pgvector's. The
cascade checks before migrating and reports what to run; creating an extension
needs superuser, which an application role deliberately is not.

On the consumer's settings path, so it imports nothing from Django.
"""

from evennia_database_cascade import AliasSpec

from .config import AI_MEMORY_ALIAS

SPEC = AliasSpec(
    app_label="evennia_ai_memory",
    alias=AI_MEMORY_ALIAS,
    required_extensions=("vector",),
)
