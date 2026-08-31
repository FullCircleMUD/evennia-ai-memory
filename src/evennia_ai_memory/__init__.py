# SPDX-License-Identifier: BSD-3-Clause
"""Embedding-backed memory and lore retrieval for LLM-driven NPCs.

The library stores what an NPC knows and what it remembers, and retrieves both
semantically. It returns data, never prompt text.

See docs/INDEX.md for the design wiki.
"""

from .services import (
    get_last_interaction_time,
    get_recent_memories,
    search_lore,
    search_memories,
    store_memory,
)

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "get_last_interaction_time",
    "get_recent_memories",
    "search_lore",
    "search_memories",
    "store_memory",
]
