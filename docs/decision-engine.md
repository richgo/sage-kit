# Venn and Jev decision engine

SageKit wraps Venn's `OutcomeService` around the same vector store that
SageKit updates. Venn is the decision engine. SageKit owns the store, writes
its vectors, and supplies the adapter that Venn calls for nearest outcomes.
Jev provides typed inference when precedent is insufficient or the request
requires a probability. A local Jev-compatible server can use the same
interface.

```text
add / ingest / promote / observe
  -> validate and append canonical record
  -> embed under the pinned profile
  -> upsert into the configured vector store

decide
  -> enforce deterministic constraints
  -> Venn OutcomeService -> SageKit adapter -> same vector store
  -> if precedent is insufficient, retrieve source evidence and ask Jev
```

## What each store does

| Component | Responsibility |
| --- | --- |
| Git journal and SQLite projection | Versioned records, provenance, ACLs, supersession and pipeline snapshots for a local corpus |
| PostgreSQL journal | Remote equivalent of the canonical event log |
| Local vector files with FAISS or exact cosine search | Persist vectors across CLI processes and search the eligible subset |
| Qdrant or PostgreSQL with pgvector | Persist and search vectors in a database |
| Venn `OutcomeService` | Compare observed numerical utility for alternatives using neighbors returned by the store |
| Jev or a compatible OSS provider | Return Choice, Score or Noul inference when the Venn outcome route cannot answer |

Plain SQLite supplies the local record projection. It has no vector index in
SageKit. Upstream Venn's outcome service takes a tagged vector-store adapter.
SageKit's adapter uses its shared vector-store interface, so the same write
path serves Venn with local FAISS, Qdrant or pgvector. The local FAISS
configuration persists profile-tagged vectors on disk and builds the
eligible FAISS index when searching. [Venn store adapters](https://markrussinovich.github.io/venn-vdm/adapters.html)

## Write and decision lifecycle

`sagekit add`, `ingest`, and the equivalent REST and MCP operations return
success after the record's vector is present in the configured store. Approved
choices and promoted changes follow the same write path. The canonical event
commits first. If the vector write fails, the operation reports failure.
Retrying the same record repairs the vector using the same canonical event ID.
Existing corpora and restored journals can fill missing vectors with
`sagekit reindex`. Search also fills missing vectors for eligible records.

Ordinary knowledge becomes searchable evidence immediately. An operational
observation enters Venn's outcome route through `sagekit observe` with an
approved choice, an independently verified change, a metric and measured
utility. The vector represents the decision context. The canonical record
retains the action, measurement and source. Venn sees only eligible IDs for
the requested family, metric, pinned revision and caller ACLs. It requires
enough nearby observations for each alternative. The original source
references stay attached to the returned evidence.

Use Python 3.12 for the [pinned Venn runtime](operation.md#decision-providers).
With it installed, SageKit enables Venn automatically and defaults to local
FAISS search. Set `SAGEKIT_VECTORS=qdrant` or `SAGEKIT_VECTORS=pgvector` to
use a database backend. With the core install alone, the CLI uses persistent
local vectors and exact cosine search. Configure Jev using
`SAGEKIT_JEV_URL`, `SAGEKIT_JEV_MODEL`, and the hosted API key when needed.
[TypeSafe Jev reference](https://docs.typesafe.ai/introduction/quickstart)
