# SPDX-License-Identifier: BSD-3-Clause
"""Logging shim for evennia-ai-memory.

Every line the library emits goes to its own ``ai_memory.log``, co-located with
Evennia's other logs under ``settings.LOG_DIR``, so diagnosing an embedding
outage or a dropped memory means reading one file rather than picking it out of
the main server log.

Lines are timestamped by Evennia, not here. ``logger.log_file`` prefixes every
line with ``<timestamp> [-] `` in UTC, the same format the rest of the server
logs use — so a memory line and a ``server.log`` line can be read against each
other directly. Adding our own would stamp every line twice.

Outside an Evennia engine — tests, or any caller where Evennia is not
bootstrapped — ``ai_memory_log`` is a silent no-op. The import is lazy and an
ImportError is swallowed; the library deliberately does not fall back to stderr
or a local file.

The pattern is ``evennia-shards``' ``log.py``, by way of
``evennia-message-bus``. Internal to the library, not part of the
consumer-facing API.
"""

import traceback

_LOG_FILENAME = "ai_memory.log"
_VALID_LEVELS = ("INFO", "WARN", "ERROR")


def ai_memory_log(message: str, level: str = "INFO", trace: bool = False) -> None:
    """Emit one line to ``ai_memory.log``.

    ``level`` is coerced to ``INFO`` if not one of ``INFO``/``WARN``/``ERROR``.
    A log call must never raise into the caller, so an unknown level degrades
    rather than rejecting.

    ``trace`` appends the active exception's traceback — call it from inside an
    ``except`` block, where ``format_exc()`` has something to report. Outside
    one it is a no-op, not an error.
    """
    try:
        from evennia.utils import logger
    except ImportError:
        return
    if logger is None:  # pragma: no cover - defensive
        return

    if level not in _VALID_LEVELS:
        level = "INFO"

    if trace:
        formatted = traceback.format_exc()
        # format_exc() returns "NoneType: None\n" when no exception is being
        # handled. Appending that would be noise.
        if formatted and not formatted.startswith("NoneType: None"):
            message = f"{message}\n{formatted.rstrip()}"

    logger.log_file(f"[{level}] {message}", filename=_LOG_FILENAME)
