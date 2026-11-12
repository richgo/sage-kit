# SageKit

SageKit is a read-write engineering knowledge corpus for requirements, architecture,
decisions, incidents, and independently verified changes. It runs offline with
Git and SQLite or as a token-authenticated service with PostgreSQL. ForgeKit can
consult it at individual verification gates and publish verified changes after
the pipeline succeeds.

## Quick start

Requires Python 3.11 or newer.

```sh
python -m pip install .
sagekit --root corpus add examples/adr.json
sagekit --root corpus query "idempotent checkout"
sagekit --root corpus snapshot
sagekit --root corpus list
python -m unittest discover -s tests -v
```

Track `corpus/knowledge.jsonl` in Git. SQLite rebuilds from the journal.
Restricted records require a private corpus checkout and appropriate filesystem
permissions. Use `--group GROUP` before a local command to access a restricted
record. The remote service assigns groups and scopes from the configured token.

## Guides

- [Corpus, search, providers, and hosting](docs/operation.md)
- [ForgeKit contextual gates and promotion](docs/forgekit.md)
- [Ordered specifications and verification coverage](specs/README.md)
