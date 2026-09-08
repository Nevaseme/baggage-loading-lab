"""Command-line entrypoint for ``python -m tools.lab``."""

from __future__ import annotations

import argparse
import json
import sys

from .registry import LabError, Registry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.lab")
    parser.add_argument("--root", default=".", help="registry root directory")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="import an exact ZIP artifact")
    ingest.add_argument("--zip", required=True, dest="zip_path")
    ingest.add_argument("--name", required=True)

    source = commands.add_parser("import-source", help="import source bytes without an archive")
    source.add_argument("--source", required=True, dest="source_path")
    source.add_argument("--name", required=True)

    record = commands.add_parser("record", help="register raw evaluation feedback")
    record.add_argument("--artifact", required=True, dest="artifact_id")
    record.add_argument("--result", required=True, dest="result_path")
    record.add_argument("--public-score", dest="public_score")
    record.add_argument("--rounded-public", dest="rounded_public")
    record.add_argument("--submission-id", dest="submission_id")
    record.add_argument("--supersedes", dest="supersedes")

    commands.add_parser("render", help="regenerate progress and current views")
    commands.add_parser("validate", help="validate registry closure and generated views")

    export = commands.add_parser("export-context", help="create a deterministic offline context ZIP")
    export.add_argument("--output", required=True)
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    registry = Registry(args.root)
    try:
        if args.command == "ingest":
            result = registry.ingest(args.zip_path, args.name)
        elif args.command == "import-source":
            result = registry.import_source(args.source_path, args.name)
        elif args.command == "record":
            result = registry.record(
                args.artifact_id,
                args.result_path,
                public_score=args.public_score,
                rounded_public=args.rounded_public,
                submission_id=args.submission_id,
                supersedes=args.supersedes,
            )
        elif args.command == "render":
            result = registry.render()
        elif args.command == "validate":
            result = registry.validate()
            _emit(result)
            return 0 if result.get("valid") else 1
        elif args.command == "export-context":
            result = registry.export_context(args.output)
        else:  # pragma: no cover - argparse enforces command choices
            parser.error(f"unknown command: {args.command}")
            return 2
        _emit(result)
        return 0
    except (LabError, OSError, ValueError) as exc:
        _emit({"error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
