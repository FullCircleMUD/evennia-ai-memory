# SPDX-License-Identifier: BSD-3-Clause
"""Standalone validator for a lore repository.

The same validation the import command runs, reachable without a game — for a
pre-commit hook or a CI job, where the point is to catch a malformed entry
before it is pushed rather than when someone tries to import it.

Always reads locally. A validation run is against a checkout by definition, so
this ignores the reader setting rather than resolving it.
"""

import sys


def main(argv=None):
    """Validate a lore checkout. Returns a process exit code.

    Reports every problem it finds, each naming the file and the title, and
    exits non-zero if there are any.
    """
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
