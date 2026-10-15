#!/usr/bin/env python3
"""Apply SERAPHIM SQLite migrations to a runtime database (S05 dev tool).

This is a thin developer/operator entry point, not the ``seraphim`` CLI (that
arrives in S10).  It performs one state-changing operation only when asked.

Usage::

    python backend/scripts/migrate.py --root <SERAPHIM_ROOT>            # apply
    python backend/scripts/migrate.py --root <SERAPHIM_ROOT> --check    # status
    python backend/scripts/migrate.py --db-path <tmp.sqlite> --json     # temp DB
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from seraphim.contracts.errors import SeraphimError  # noqa: E402
from seraphim.storage import Database, MigrationRunner  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply SERAPHIM schema migrations.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", help="SERAPHIM root; database resolves to <root>/data/seraphim.sqlite")
    group.add_argument(
        "--db-path",
        help="Explicit database file. Relative values are resolved against the current directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report schema status without creating or modifying anything.",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.db_path:
            explicit = Path(args.db_path)
            if not explicit.is_absolute():
                explicit = Path.cwd() / explicit
            db = Database(path=explicit)
        else:
            db = Database.open(args.root)
        runner = MigrationRunner(db)
        payload = runner.status().to_dict() if args.check else runner.run().to_dict()
    except SeraphimError as error:
        if args.json:
            print(json.dumps({"ok": False, "error": error.to_diagnostic_dict()}, ensure_ascii=False))
        else:
            print(f"ERROR {error.code}: {error.safe_message}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"ERROR OS_{type(exc).__name__}: {exc.strerror}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
    else:
        print(f"database: {db.path}")
        if args.check:
            print(
                f"initialized: {payload['initialized']} "
                f"version: {payload['current_version']}/{payload['head_version']} "
                f"pending: {list(payload['pending'])}"
            )
        else:
            applied = payload["applied"]
            names = ", ".join(f"{m['version']:04d}:{m['name']}" for m in applied) or "none"
            print(
                f"fresh_database: {payload['fresh_database']} "
                f"version: {payload['version_before']} -> {payload['version_after']} "
                f"applied: {names}"
            )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
