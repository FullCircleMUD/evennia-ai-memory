# SPDX-License-Identifier: BSD-3-Clause
"""Encounter memory and semantic lore retrieval for LLM-driven NPCs.

The library stores what an NPC knows and what it remembers: lore, searched
semantically, and encounters, read back by who was in them. It returns data,
never prompt text.

See docs/INDEX.md for the design wiki.
"""

from .services import (
    get_nearest_encounters,
    get_recent_encounters,
    get_recent_transcripts,
    recall_encounters,
    search_lore,
    shortlist_encounters,
    store_encounter,
)

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "get_nearest_encounters",
    "get_recent_encounters",
    "get_recent_transcripts",
    "recall_encounters",
    "search_lore",
    "shortlist_encounters",
    "store_encounter",
]
