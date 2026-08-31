# SPDX-License-Identifier: BSD-3-Clause
"""The library's two tables.

Both live on the ``ai_memory`` database alias, behind this library's router, so
a rebuild of the consumer's game database does not erase what NPCs have learned.

Two embedding fields coexist on each model for dual-backend support:

- ``embedding`` (BinaryField) — a numpy float32 blob, used on SQLite.
- ``embedding_vector`` (VectorField) — a pgvector column, used on PostgreSQL.
"""

from django.db import models

from pgvector.django import VectorField

from .config import get_embedding_dimensions

#: Resolved once at import. The initial migration reads the same accessor, so
#: the column is created at the width the consuming project configured.
EMBEDDING_DIMENSIONS = get_embedding_dimensions()


#: Who began an interaction. Two values and no more, so a typo is a defect
#: rather than a new category — a mis-spelled initiator would silently
#: mis-order however a consumer renders the event.
INITIATOR_PC = "pc"
INITIATOR_NPC = "npc"
INITIATORS = (INITIATOR_PC, INITIATOR_NPC)


class NpcMemory(models.Model):
    """One interaction between an NPC and a character.

    An event, not a conversation. It may be words exchanged, or a purchase, a
    theft, an attack, a taunt — whatever the consuming game does. ``summary``
    is what happened, written by the consumer and embedded here;
    ``interaction_type`` is what kind of thing it was, in the game's own
    vocabulary; ``initiator`` is which party began it.

    Both parties are identified by a UUID the consumer supplies, stable across
    instances and world rebuilds. The library matches those exactly and never
    infers that two identifiers mean the same entity.

    The character's name is stored because a prompt usually wants it. The NPC's
    is not: a memory belongs to one NPC, so the caller asking already knows.
    """

    npc_uuid = models.UUIDField(db_index=True)
    pc_uuid = models.UUIDField(db_index=True)
    pc_name = models.CharField(max_length=80)
    summary = models.TextField()
    interaction_type = models.CharField(max_length=40, default="say")
    initiator = models.CharField(max_length=8, default=INITIATOR_PC)
    embedding = models.BinaryField(null=True, blank=True)
    embedding_vector = VectorField(
        dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "evennia_ai_memory"
        verbose_name = "NPC memory"
        verbose_name_plural = "NPC memories"
        indexes = [
            models.Index(fields=["npc_uuid", "created_at"]),
            models.Index(fields=["npc_uuid", "pc_uuid"]),
        ]

    def __str__(self):
        return f"{self.npc_uuid} ↔ {self.pc_name} ({self.created_at:%Y-%m-%d %H:%M})"


class LoreMemory(models.Model):
    """One piece of world knowledge, embedded for semantic retrieval.

    ``scope_tags`` says who may know this. A row is returned only when every tag
    it carries is in the list the caller passed — rows require, callers hold.
    An empty list means everyone.

    ``scope_level`` is stored, indexed and returned, but no gate reads it.
    """

    title = models.CharField(max_length=200)
    content = models.TextField()
    scope_level = models.CharField(max_length=20, db_index=True)
    scope_tags = models.JSONField(default=list)
    embedding = models.BinaryField(null=True, blank=True)
    embedding_vector = VectorField(
        dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True
    )
    source = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "evennia_ai_memory"
        verbose_name = "lore memory"
        verbose_name_plural = "lore memories"
        indexes = [
            models.Index(fields=["scope_level"]),
            models.Index(fields=["scope_level", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "title"],
                name="uniq_lorememory_source_title",
            ),
        ]

    def __str__(self):
        tags = ", ".join(self.scope_tags) if self.scope_tags else "global"
        return f"{self.title} ({self.scope_level}: {tags})"
