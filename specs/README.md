# SageKit specification programme

SageKit is a portable, read-write engineering knowledge and decision platform. The specifications are implemented in dependency order, with independent tests and review gates. Source requirements, CALM/LikeC4 architecture, ADRs, incidents and verified pipeline outcomes contribute to an evidence-grounded corpus. Agents and ForgeKit may query the corpus at configured verification gates.

## Ordered specifications

| ID | Specification | Exit gate |
|---|---|---|
| 000 | Foundation and governance | Installable Python CLI, reproducible CI and test fixtures |
| 001 | Canonical knowledge and provenance | Versioned identifiers, source relationships, ACLs and supersession |
| 002 | Local and external repositories | Git + SQLite local writer, PostgreSQL service adapter, idempotent event log |
| 003 | Embedding profiles and vectors | FAISS local index plus Qdrant/pgvector; incompatible profiles rejected |
| 004 | Knowledge ingestion | Requirements, CALM, LikeC4, ADR and operational incident ingestion |
| 005 | Grounded retrieval | Exact + semantic retrieval with source revisions and permission filters |
| 006 | Typed decisions and policy | Choice/Score/Noul, deterministic checks, abstention and audit envelopes |
| 007 | Jev providers | Hosted Jev and replaceable, local OSS Jev-compatible backend |
| 008 | Venn and routing | Profile-pinned Venn history route; Jev on absent/insufficient evidence |
| 009 | Outcome ledger | Separate approved choice, successful verification and observed utility; no self-training from unverified advice |
| 010 | Publishing and hosting | GitHub Pages for public read-only artefacts; full read-write via local CLI or separate API |
| 011 | Service APIs and MCP | Authenticated read-write REST and MCP surfaces; same application use cases as CLI |
| 012 | ForgeKit APM/APMX | Versioned integration packages and independently verified end-to-end lifecycle |
| 013 | Release and migration | Backup/restore, profile migrations, benchmark and security gates |
| 014 | Contextual gates and post-success promotion | Optional per-stage checks, pinned snapshots and idempotent promotion only after completed successful pipeline |

## Lifecycle contract

1. At pipeline start pin a corpus revision and approved product/architecture inputs.
2. At each stage optionally invoke SageKit in **off**, **advisory**, or **required** mode, with an explicit contextual question and evidence requirements.
3. Resolve exact, numerical, identity, supersession and authorization constraints deterministically.
4. For established comparable outcomes, attempt Venn using compatible pinned embeddings. If the corpus lacks adequate support, fall back to a Jev-compatible provider or abstain/human review.
5. No generated answer is automatically authoritative. The pipeline's trusted verifier determines success independently of advisory model output.
6. After a successful, approved pipeline, publish an idempotent knowledge contribution containing the accepted requirements, architecture, implementation decision and verified evidence.
7. Record actual operational outcomes later through an authenticated incident/outcome path. Only observed utilities belong in Venn outcome learning; do not treat successful builds as evidence of optimal architecture.
8. Knowledge publication failure is independently observable and retryable; it must not counterfeit pipeline success or mutate the run's pinned knowledge snapshot.

## Deployment contract

- Local CLI: Git-tracked canonical knowledge and event records, SQLite transactional projection, rebuildable FAISS vectors, offline read-write.
- Git-backed CI: checkout immutable corpus snapshot, execute local CLI, then publish a reviewed commit or PR after successful verification.
- Remote API: hosted SageKit service (e.g. Azure Container Apps) with authenticated read-write and PostgreSQL/Qdrant or pgvector.
- GitHub Pages is **not** a read-write host; optionally publish static public documentation and corpus snapshots there.
- The CLI must expose the same core commands under local and remote transports. Adapter implementations must pass shared contract tests.

## Implementation discipline

No placeholder features. A specification is complete only with source, docs, unit/contract/integration tests, negative tests, and verified CI evidence. Develop increments in ordered PRs, preserve upstream model and licence constraints, and do not bypass protected ForgeKit verification gates.

## Implementation and verification map

| ID | Delivered behavior | Verification |
| --- | --- | --- |
| 000 | Installable wheel and CLI, Windows/Linux CI, example fixtures | Installed-wheel matrix |
| 001 | Content IDs, versioned sources, relationship visibility, supersession | Foundation and edge-case tests |
| 002 | Git-trackable hash chain, rebuildable SQLite projection, PostgreSQL events | Foundation, concurrency and PostgreSQL integration tests |
| 003 | Immutable profile identities, FAISS, Qdrant and pgvector adapters | Shared vector contract against each backend |
| 004 | Requirements, CALM, LikeC4, ADR and incident import | Ingestion and malformed-input tests |
| 005 | Exact and vector evidence retrieval with ACLs and revision citations | Retrieval and vector filtering tests |
| 006 | Choice, Score, Noul, deterministic constraints, audit envelopes and abstention | Decision and provider tests |
| 007 | Hosted TypeSafe and local System One compatible transport | HTTP and response-shape tests |
| 008 | Upstream Venn outcome route with support, similarity and profile checks | Upstream Venn integration and routing tests |
| 009 | Separate approval, independent verification and operational utility | Outcome eligibility and promotion tests |
| 010 | Public HTML/JSON export and manual Pages workflow | Static export and ACL tests |
| 011 | Scoped REST, remote CLI transport and authenticated stdio MCP | HTTP ACL and MCP integration tests |
| 012 | Versioned ForgeKit APM/APMX package and independent acceptance replay | Pinned ForgeKit fixture and contextual check replay |
| 013 | Backup/restore, side-by-side profile reindexing, benchmark command, security regressions | Recovery and profile tests |
| 014 | Optional gates, input and corpus pinning, signed post-success promotion | Gate, replay, tamper and full fixture lifecycle tests |

The [operator guide](../docs/operation.md) covers service and model deployment.
The [ForgeKit guide](../docs/forgekit.md) covers the protected publisher and
its attestation requirements. Hosted Jev inference, a production ForgeKit
run, and publication to a configured Pages environment require deployment
credentials and infrastructure.
