# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig for evennia-ai-memory."""

from django.apps import AppConfig

from .log import ai_memory_log


class EvenniaAiMemoryConfig(AppConfig):
    name = "evennia_ai_memory"
    label = "evennia_ai_memory"
    verbose_name = "AI memory"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        """Validate the settings, and name the database this instance resolved.

        The validation stops a consumer who installed the library without
        configuring it. The log line exists because which database the memories
        landed on depends on environment variables set outside this process —
        two instances that should share one are confirmed by reading two log
        lines, rather than by reasoning about where each variable was set.
        """
        from . import config

        config.validate_settings()
        ai_memory_log(f"memories on {config.describe_ai_memory_database()}")
