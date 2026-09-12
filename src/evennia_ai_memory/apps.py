# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig for evennia-ai-memory."""

from django.apps import AppConfig


class EvenniaAiMemoryConfig(AppConfig):
    name = "evennia_ai_memory"
    label = "evennia_ai_memory"
    verbose_name = "AI memory"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        """Validate the settings, and install the lore commands.

        The validation stops a consumer who installed the library without
        configuring it. Where the alias landed is `evennia-database-cascade`'s
        to report, and it logs that itself.
        """
        # The commands are installed by wrapping evennia._init below, so this
        # module needs the engine to reach it.
        import evennia

        from . import config

        config.check_settings()

        # Evennia's lazy ``Command`` export is still None at ready() time —
        # ``evennia._init()`` populates it, and the real entry points call that
        # *after* django.setup() has already triggered this hook. So wrap
        # _init() and install once it has run, rather than importing commands
        # here and getting None for a base class.
        if getattr(evennia, "_evennia_ai_memory_init_wrapped", False):
            return

        original_init = evennia._init

        def wrapped_init(*args, **kwargs):
            original_init(*args, **kwargs)
            install_commands()

        evennia._init = wrapped_init
        evennia._evennia_ai_memory_init_wrapped = True


def install_commands():
    """Add the lore commands to ``AccountCmdSet``.

    That cmdset is the right home: its commands are available out of character
    and merge with the character's on puppet, so one patch serves both.

    Idempotent — repeated ``_init()`` calls, or another library wrapping the
    same hook, must not install them twice.
    """
    from evennia.commands.default.cmdset_account import AccountCmdSet

    if getattr(AccountCmdSet, "_evennia_ai_memory_patched", False):
        return

    original_at_cmdset_creation = AccountCmdSet.at_cmdset_creation

    def patched_at_cmdset_creation(self):
        original_at_cmdset_creation(self)
        from .commands import CmdLoreImport, CmdLoreWipe

        self.add(CmdLoreImport())
        self.add(CmdLoreWipe())

    AccountCmdSet.at_cmdset_creation = patched_at_cmdset_creation
    AccountCmdSet._evennia_ai_memory_patched = True
