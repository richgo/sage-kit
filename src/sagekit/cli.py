import argparse
import json
import os
from pathlib import Path
import sqlite3
from urllib.error import HTTPError

from .application import Principal
from .config import create_application
from .gates import gate_unavailable, pin, signed, skipped_gate
from .ingest import ingest
from .maintenance import backup, benchmark, reindex, restore
from .service import Remote, SCOPES, service


def parser():
    command = argparse.ArgumentParser(prog="sagekit")
    command.add_argument("--root", type=Path, default=Path("corpus"))
    command.add_argument("--group", action="append", default=[])
    command.add_argument("--remote", default=os.getenv("SAGEKIT_REMOTE_URL"))
    sub = command.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    listing = sub.add_parser("list")
    listing.add_argument("--revision")
    listing.add_argument("--history", action="store_true")
    query = sub.add_parser("query")
    query.add_argument("query")
    query.add_argument("--revision")
    query.add_argument("--limit", type=int, default=10)
    for name in ("add", "decide", "approve", "observe", "promote", "sign-receipt",
                 "backup", "restore", "export-public", "benchmark", "pin"):
        action = sub.add_parser(name)
        action.add_argument("file", type=Path)
        if name in ("decide", "export-public", "pin"):
            action.add_argument("--revision")
    gate = sub.add_parser("gate-check")
    gate.add_argument("file", type=Path)
    gate.add_argument("--pin", type=Path)
    loader = sub.add_parser("ingest")
    loader.add_argument("kind")
    loader.add_argument("file", type=Path)
    loader.add_argument("--revision", required=True)
    loader.add_argument("--uri")
    loader.add_argument("--acl", action="append", default=[])
    loader.add_argument("--supersedes")
    sub.add_parser("reindex").add_argument("--revision")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("mcp")
    return command


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(args):
    name = args.command
    if name == "gate-check":
        policy = load(args.file)
        if isinstance(policy, dict) and policy.get("mode", "off") == "off":
            return skipped_gate(policy.get("stage"))
    if name == "sign-receipt":
        return signed(load(args.file), os.environ["SAGEKIT_RECEIPT_KEY"].encode())
    if args.remote and args.group:
        raise ValueError("remote groups are assigned by the service credential")
    app = None if args.remote else create_application(args.root)
    groups = frozenset(args.group)
    principal = Principal(groups, SCOPES)
    token = os.getenv("SAGEKIT_TOKEN", "")
    if args.remote:
        dispatch = Remote(args.remote, token).dispatch
    else:
        def dispatch(operation, params):
            return app.dispatch(operation, params, principal)

    if name == "serve":
        if not app:
            raise ValueError("serve requires local configuration")
        with service(app, json.loads(os.environ["SAGEKIT_SERVICE_TOKENS"]), args.host, args.port) as server:
            server.serve_forever()
        return None
    if name == "mcp":
        from .mcp_server import create_mcp

        credentials = None if args.remote else json.loads(os.environ["SAGEKIT_SERVICE_TOKENS"])
        create_mcp(app, credentials, token, args.remote).run()
        return None
    if name == "snapshot":
        return dispatch(name, {})
    if name == "pin":
        current = dispatch("snapshot", {})
        return pin(args.revision or current["revision"], load(args.file), current["embedding_profile"])
    if name == "list":
        return dispatch(name, {"revision": args.revision, "history": args.history})
    if name == "query":
        return dispatch(name, {"query": args.query, "revision": args.revision, "limit": args.limit})
    if name == "ingest":
        record = ingest(args.file, args.kind, args.revision, uri=args.uri,
                        acl=tuple(args.acl), supersedes=args.supersedes)
        return dispatch("add", {"record": record.as_dict()})
    if name == "gate-check":
        params = {"policy": policy, "pin": load(args.pin) if args.pin else None}
        try:
            return dispatch(name, params)
        except HTTPError as exc:
            if exc.code < 500:
                raise
            return gate_unavailable(policy, "knowledge service unavailable")
        except (OSError, sqlite3.Error):
            return gate_unavailable(policy, "knowledge service unavailable")
    if name == "decide":
        return dispatch(name, {"request": load(args.file), "revision": args.revision})
    if name == "add":
        return dispatch(name, {"record": load(args.file)})
    if name in ("approve", "observe"):
        return dispatch(name, load(args.file))
    if name == "promote":
        return dispatch(name, {"receipt": load(args.file)})
    if not app:
        raise ValueError(f"{name} requires local configuration")
    if name == "backup":
        return backup(app.repo, args.file)
    if name == "restore":
        return restore(app.repo, args.file)
    if name == "reindex":
        return reindex(app, groups, args.revision)
    if name == "benchmark":
        return benchmark(app, groups, load(args.file))
    app.export_public(args.file, args.revision)
    return {"output": str(args.file)}


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    try:
        result = run(args)
        if result is not None:
            print(json.dumps(result, allow_nan=False))
        return 2 if args.command == "gate-check" and not result["allowed"] else 0
    except (ValueError, TypeError, AttributeError, KeyError, OSError, ImportError, sqlite3.Error) as exc:
        command.exit(1, f"sagekit: {exc}\n")
    except KeyboardInterrupt:
        return 130
