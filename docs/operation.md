# Operating SageKit

## Corpus

`add FILE` accepts a canonical JSON record. Set `kind`, `title`, `body`,
and `source.uri` and `source.revision`. Use an immutable source revision or
content digest. Set `source.locator` for a subsection, `links` for related
record IDs, and `supersedes` for a replacement of the same kind and ACL.
An empty ACL is public. A record with an ACL is visible to a principal with
any of the listed groups. A link can point only to an equally or more widely
visible record.

```sh
sagekit --root corpus ingest adr checkout.md --revision COMMIT --uri repo:docs/adr/checkout.md
sagekit --root corpus --group sre ingest incident incident.json --revision COMMIT --acl sre
sagekit --root corpus --group sre list --history
sagekit --root corpus query "checkout" --revision CORPUS_REVISION
```

Ingestion accepts Markdown or JSON requirements and ADRs, CALM JSON with
`nodes` and `relationships`, LikeC4 model text, and incident JSON with
`id`, `title`, and `impact`. Ingestion retains the original source text.
Run the source project's schema and language validators before import when
source conformance is a release requirement.

A corpus snapshot is a content hash of an ordered event chain. Re-adding
identical content returns the original event revision. Local writers are
serialized by SQLite. To publish a local journal, stage only
`corpus/knowledge.jsonl`, review the diff, then commit and open a PR. If
the base advances, restart from the new journal and replay the intended
commands. The hash chain detects text merges that combine divergent histories.

## Search and vectors

Exact matches use the record ID, title, source URI, or external ID. The
vector search receives only visible records active at the chosen revision.
The default offline embedder uses hashed lexical terms. Set
`SAGEKIT_EMBEDDING_MODEL`, `SAGEKIT_EMBEDDING_REVISION` (40-character model
commit), and `SAGEKIT_EMBEDDING_DIMENSIONS` for a semantic model with the
`semantic` extra. Test the model against representative queries before
selecting it.

| Backend | Installation | Configuration |
| --- | --- | --- |
| Local persistent exact search | Core | Default with the core install, or `SAGEKIT_VECTORS=local` |
| Local FAISS | `pip install '.[faiss]'` | Default when Venn is installed, or `SAGEKIT_VECTORS=faiss` |
| Qdrant | `pip install '.[qdrant]'` | `SAGEKIT_VECTORS=qdrant`, `SAGEKIT_QDRANT_URL`, optional `SAGEKIT_QDRANT_API_KEY` |
| pgvector | `pip install '.[postgres]'` | `SAGEKIT_VECTORS=pgvector`, `SAGEKIT_POSTGRES_DSN` |

All durable backends store vectors during writes. Local vectors live under
`corpus/.sagekit/vectors` by default. Set `SAGEKIT_VECTOR_ROOT` to change
that path. FAISS searches an eligible index built from those stored vectors.
Qdrant and pgvector persist vectors by profile and record ID. Keep vector
stores private and restrict access to the SageKit service. Profiles include
model, revision, representation, dimension, and ordered fields. A new
profile gets a distinct namespace.

## Decision providers

See the [Venn and Jev architecture](decision-engine.md) for the shared write and decision path.

`decide REQUEST.json` returns an audit envelope with the pinned snapshot,
request hash, embedding profile, evidence references, route attempts, and
the typed answer or abstention. Store the returned envelope in the calling
pipeline's evidence artifacts if retention is required.

- Set `SAGEKIT_JEV_URL=https://api.typesafe.ai/v1/systemone`,
  `TYPESAFE_API_KEY`, and `SAGEKIT_JEV_MODEL` to enable hosted Jev. Configure
  a fixed model version for reproducible review. Caller-supplied decision state
  is sent to the configured endpoint. Restricted corpus records are omitted.
- Start a local System One compatible provider such as JevForge and set
  `SAGEKIT_JEV_URL=http://127.0.0.1:8123/v1/systemone`. The same adapter
  validates Choice, Score, and Noul responses. Both transports omit restricted
  records by default. Set `SAGEKIT_JEV_RESTRICTED_EVIDENCE=1` only for a trusted
  loopback server whose retention and logs are approved for restricted data.
- Installing upstream Venn enables its outcome service automatically. Set
  `SAGEKIT_VENN=0` to disable it or `SAGEKIT_VENN=1` to enable it explicitly. Use Python
  3.12 for the pinned upstream package and install it with the command below.
  The outcome path uses tagged vectors and requires no downloaded Venn model
  weights. Venn compares a Choice only when each alternative has sufficient
  similar measured cases for the same family and utility metric. Utility ties
  and insufficient history fall back to Jev, or abstain if it is unavailable.
  Requests with a positive probability confidence threshold go directly to
  Jev because Venn reports observed utility.

```sh
python -m pip install 'venn-vdm @ git+https://github.com/markrussinovich/venn-vdm.git@ad97513f1cc1fc5abc886f195d17e6145776e091'
sagekit --root corpus decide examples/decision.json
```

[Upstream Venn outcome API](https://markrussinovich.github.io/venn-vdm/outcome-api.html),
[TypeSafe System One reference](https://docs.typesafe.ai/introduction/quickstart),
[JevForge serving and model documentation](https://github.com/zwliJay/jev-forge).

## REST, remote CLI, MCP, and Pages

Set `SAGEKIT_POSTGRES_DSN` to run the PostgreSQL repository. Provision the
`vector` extension for pgvector and give the service role access to its tables.
For local serving, omit the DSN and point `--root` at a persistent volume.

Set `SAGEKIT_SERVICE_TOKENS` to a JSON object mapping high-entropy tokens to
groups and scopes, for example
`{"<reader-token>":{"groups":["sre"]},"<writer-token>":{"scopes":["write","decide"]}}`.
The optional scopes are `write`, `decide`, `approve`, `observe`, and
`promote`. Start `sagekit serve` behind a TLS reverse proxy for remote
deployment. Set `SAGEKIT_TOKEN` and `SAGEKIT_REMOTE_URL` on the client and
use the same corpus, decision and ledger commands. REST accepts JSON POSTs
to `/v1/<command>`, with an Authorization Bearer token and a
`{"result": ...}` response. The request fields are the matching application
arguments, such as `{"query":"checkout","limit":5}` for `/v1/query`.

Install `.[mcp]` for `sagekit mcp`. The server uses stdio and binds its
identity to `SAGEKIT_TOKEN` at startup. Run it with the same local credential
configuration or as a client of the authenticated REST service. It exposes
snapshot, list, add, search, typed decisions, gate checks, and the scoped
approval, observation, and promotion tools.

`sagekit --root corpus export-public site` emits an escaped HTML view and JSON
for public records. The manually triggered Pages workflow publishes those
files after GitHub Pages is configured to use GitHub Actions.

## Release and recovery

- Run `sagekit backup backup.jsonl` and store the copy with the same access
  controls as the corpus. Restore into an empty directory with
  `sagekit --root recovered restore backup.jsonl`. Compare the restored
  snapshot with the original. Use database-native backups and point-in-time
  recovery for PostgreSQL.
- For an embedding migration, retain the canonical journal and old profile
  configuration. Set the candidate profile and vector backend in a separate
  process, run `reindex --revision CORPUS_REVISION`, and compare evidence
  results and timings with the old profile. `benchmark QUERIES.json` accepts
  an array of representative queries and reports timings at a single corpus
  revision. Deploy the candidate configuration after evaluation. Roll back by
  restoring the prior profile configuration.
- Run the installed-wheel CI matrix and the integration suite before
  release. The integration job exercises profile mismatch and ACL filtering
  on the actual vector stores, invalid credentials, signed promotion replay,
  and the pinned ForgeKit verifier. Smoke-test any configured hosted model or
  semantic embedding service using the deployment's own credentials.
