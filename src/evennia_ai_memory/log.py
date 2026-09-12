# SPDX-License-Identifier: BSD-3-Clause
"""Logging shim for evennia-ai-memory.

Every line the library emits goes to its own ``ai_memory.log`` under
``settings.LOG_DIR``, so diagnosing an embedding outage or a dropped memory
means reading one file rather than picking it out of the main server log. The
mechanism belongs to ``evennia-logging-extension``; this file names the file
and nothing else.

Internal to the library, not part of the consumer-facing API.
"""

from evennia_logging_extension import make_logger

ai_memory_log = make_logger("ai_memory.log")
