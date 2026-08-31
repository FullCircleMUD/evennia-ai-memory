# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig for evennia-ai-memory."""

from django.apps import AppConfig


class EvenniaAiMemoryConfig(AppConfig):
    name = "evennia_ai_memory"
    label = "evennia_ai_memory"
    verbose_name = "AI memory"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        """Validate the required settings so a gap stops the app at startup."""
        from . import config

        config.validate_settings()
