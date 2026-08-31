# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-ai-memory, run via ``python runtests.py``."""

import unittest

from django.conf import settings
from django.test import TestCase

import evennia_ai_memory


class SmokeTest(unittest.TestCase):
    """Proves the package installs and the runner reaches it."""

    def test_version(self):
        self.assertEqual(evennia_ai_memory.__version__, "0.0.1")


class SettingsSmokeTest(TestCase):
    """Proves Django is configured and both database aliases are present."""

    databases = {"default", "ai_memory"}

    def test_app_installed(self):
        self.assertIn("evennia_ai_memory", settings.INSTALLED_APPS)

    def test_ai_memory_alias_configured(self):
        self.assertIn("ai_memory", settings.DATABASES)
