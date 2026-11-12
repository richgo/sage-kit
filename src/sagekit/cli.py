import argparse
import json
from pathlib import Path

from .model import Record
from .repository import LocalRepository


def parser():
    command = argparse.ArgumentParser(prog="sagekit")
    command.add_argument("--root", type=Path, default=Path("corpus"))
    command.add_argument("--group", action="append", default=[])
    sub = command.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    add = sub.add_parser("add")
    add.add_argument("file", type=Path)
    listing = sub.add_parser("list")
    listing.add_argument("--revision")
    listing.add_argument("--history", action="store_true")
    return command


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    try:
        repo = LocalRepository(args.root)
        if args.command == "add":
            record = Record.from_dict(json.loads(args.file.read_text(encoding="utf-8")))
            result = {"id": record.id, "revision": repo.append(record)}
        elif args.command == "snapshot":
            result = {"revision": repo.snapshot()}
        else:
            result = [item.as_dict() for item in repo.records(
                args.revision, set(args.group), history=args.history)]
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        command.exit(1, f"sagekit: {exc}\n")
    return 0
