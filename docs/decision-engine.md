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

## Architecture decision examples

At the checkout architecture checkpoint, the team needs to choose between
publishing order events directly and using a transactional outbox. A broker
acknowledgement can be lost after it accepts an event, so the question is
which design has performed better when retries occur.

Run these requests against the configured providers.

```sh
sagekit --root corpus decide examples/architecture-choice.json
sagekit --root corpus decide examples/architecture-score.json
sagekit --root corpus decide examples/architecture-noul.json
```

### Choice with comparable precedent

The [Choice request](../examples/architecture-choice.json) sets the family
to `order-event-publication`, the metric to `duplicate-events-per-10000-orders`,
and the goal to `minimize`. With sufficient similar observed outcomes for
both options, Venn might return the following fields from the SageKit result.

```json
{
  "kind": "choice",
  "status": "answered",
  "provider": "venn",
  "value": "transactional-outbox",
  "confidence": null,
  "support": {
    "transactional-outbox": {"mean": 0.5, "count": 4, "supported": true},
    "direct-publish": {"mean": 3.0, "count": 4, "supported": true}
  }
}
```

Here `0.5` is the mean observed number of duplicate events per 10,000 orders
for four similar outbox cases. The full response includes evidence IDs and
source references so the reviewer can inspect those cases.

### The same Choice with insufficient history

If Venn has too few comparable observations, SageKit sends the same
question, options, and eligible evidence to the configured Jev Decision API
provider. A possible SageKit response excerpt is below. The numbers are
illustrative.

```json
{
  "kind": "choice",
  "status": "answered",
  "provider": "jev",
  "value": "transactional-outbox",
  "confidence": 0.56,
  "probabilities": {
    "transactional-outbox": 0.78,
    "direct-publish": 0.22
  },
  "attempts": [{"provider": "venn", "status": "insufficient"}]
}
```

A new corpus starts with no measured precedent. Use `sagekit observe` to
add operational measurements for approved, verified choices, or configure
Jev to exercise fallback immediately. If neither route supplies a usable
answer, SageKit returns `status: abstained`.

### Score and Noul

The [Score request](../examples/architecture-score.json) rates a rollback
plan on a three-level rubric. An illustrative `value` of `1.0` with a
probability distribution of `{"0": 0.1, "1": 0.8, "2": 0.1}` puts the most
weight on the middle level, actionable steps with missing verification.

The [Noul request](../examples/architecture-noul.json) asks whether every
retry preserves the same event ID. An illustrative `value` of `0.91`
means a 91% estimated probability that the statement holds for the
supplied design. These two requests go directly to Jev or the configured
OSS Decision API provider.
