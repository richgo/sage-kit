# SageKit

SageKit is a read-write engineering knowledge corpus with versioned provenance.

Install with Python 3.11 or newer.

```sh
python -m pip install .
sagekit --root corpus add examples/adr.json
sagekit --root corpus snapshot
sagekit --root corpus list
python -m unittest discover -s tests -v
```

Track `corpus/knowledge.jsonl` in Git. The local SQLite projection rebuilds from that journal. Use a private repository for restricted records, and serialize publication through reviewed branches. The CLI trusts the local operator and filesystem permissions.

See the [ordered specifications](specs/README.md).
