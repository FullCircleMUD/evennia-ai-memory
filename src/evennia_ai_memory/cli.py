# SPDX-License-Identifier: BSD-3-Clause
"""Standalone validator for a lore repository.

The same validation the import command runs, reachable without a game — for a
pre-commit hook or a CI job, where the point is to catch a malformed entry
before it is pushed rather than when someone tries to import it.

Always reads locally. A validation run is against a checkout by definition, so
this ignores the reader setting rather than resolving it.
"""

import argparse
import sys


def main(argv=None):
    """Validate a lore checkout. Returns a process exit code.

    Reports every problem it finds, each naming the file and the title, and
    exits non-zero if there are any.
    """
    from evennia_yaml_reader import LocalReader

    from .lore_import import LoreImportError, discover, load_entries, validate

    parser = argparse.ArgumentParser(description="Validate a lore repository.")
    parser.add_argument("root", help="path to a checkout of the lore repository")
    args = parser.parse_args(argv)

    reader = LocalReader(root=args.root)
    try:
        entries = load_entries(reader, discover(reader))
    except LoreImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = validate(entries)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1

    print(f"ok: {len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
