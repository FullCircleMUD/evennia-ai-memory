# SPDX-License-Identifier: BSD-3-Clause
"""Test runner for evennia-ai-memory.

Runs the library's unit tests against tests/test_settings.py — no gamedir
required. Invoke from the library root:

    python runtests.py

Django is bootstrapped, Evennia is not. This is a deliberate divergence from
sibling libraries that call ``evennia._init()`` here: the library is a Django
app with no Evennia dependency, so the Evennia bootstrap would be dead weight.
See CLAUDE.md principle 6.
"""

import os
import sys

import django

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.test_settings")
    django.setup()

    from django.conf import settings
    from django.test.utils import get_runner

    runner = get_runner(settings)()
    failures = runner.run_tests(["evennia_ai_memory"])
    sys.exit(bool(failures))
