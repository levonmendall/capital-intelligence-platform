"""Verify or restore a complete canonical Capital Intelligence backup archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from operations import BackupError
from run_backup import build_manager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or restore a canonical backup archive."
    )
    parser.add_argument("archive")
    parser.add_argument("--target", default="restored-database")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manager = build_manager()
        manifest = manager.verify_archive(args.archive)
        if args.verify_only:
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "archive": str(Path(args.archive).expanduser()),
                        "schema_version": manifest["schema_version"],
                        "database_count": len(manifest["files"]),
                        "required_logical_names": manifest.get(
                            "required_logical_names",
                            [],
                        ),
                        "baseline_identifier": manifest.get(
                            "baseline_identifier"
                        ),
                        "process_version": manifest.get("process_version"),
                        "code_version": manifest.get("code_version"),
                        "real_money_authorized": False,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        restored = manager.restore(
            args.archive,
            args.target,
            overwrite=args.overwrite,
        )
        expected = len(manifest["files"])
        if len(restored) != expected:
            raise BackupError(
                "restore did not reproduce the complete manifest authority set"
            )
        print(
            json.dumps(
                {
                    "status": "restored",
                    "archive": str(Path(args.archive).expanduser()),
                    "target": str(Path(args.target).expanduser()),
                    "schema_version": manifest["schema_version"],
                    "database_count": len(restored),
                    "restored_files": [str(path) for path in restored],
                    "required_logical_names": manifest.get(
                        "required_logical_names",
                        [],
                    ),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (BackupError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
