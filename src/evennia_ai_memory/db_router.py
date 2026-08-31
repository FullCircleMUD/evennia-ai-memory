# SPDX-License-Identifier: BSD-3-Clause
"""Route this library's models to their own database alias.

The router answers only for this library's app label and returns ``None`` for
everything else, so a sibling library's router in the same
``DATABASE_ROUTERS`` list still gets its say.

Migrate with:  ``evennia migrate --database ai_memory``
"""

DATABASE_ALIAS = "ai_memory"
APP_LABEL = "evennia_ai_memory"


class AiMemoryRouter:
    """Send ``evennia_ai_memory`` models to the ``ai_memory`` alias."""

    app_label = APP_LABEL
    database_alias = DATABASE_ALIAS

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database_alias
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database_alias
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if (
            obj1._meta.app_label == self.app_label
            and obj2._meta.app_label == self.app_label
        ):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.app_label:
            return db == self.database_alias
        if db == self.database_alias:
            return False
        return None
