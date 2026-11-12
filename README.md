# SageKit

SageKit wraps Venn's vector decision engine with a read-write engineering
knowledge corpus. `sagekit add` writes a record and its embedding. Venn reads
observed outcomes from that same vector store. Jev or a compatible OSS model
provides typed inference when there is insufficient precedent. Git and SQLite
retain the local records, access rules and history. The vector store handles
similarity search. ForgeKit can consult SageKit at verification gates and
publish verified changes after the pipeline succeeds.

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

- [Venn, Jev, and the vector write path](docs/decision-engine.md)
- [Corpus, search, providers, and hosting](docs/operation.md)
- [ForgeKit contextual gates and promotion](docs/forgekit.md)
- [Ordered specifications and verification coverage](specs/README.md)
