# SageKit in ForgeKit

The versioned [APM package](../integrations/forgekit/apm.yml) exports an
[APMX contract](../integrations/forgekit/contracts/contextual-knowledge.contract.md)
and verifier. Reference `richgo/sage-kit/integrations/forgekit#COMMIT` using a
reviewed SageKit commit. Install SageKit in the runner. The caller owns the
immutable gate policies and input digests. Select a policy individually at
requirements, architecture, implementation, test, security, or release.
Use the pinned APMX runner's supported workspace staging. The ForgeKit fixture
replays the check and the independent verifier. A hosted agent run requires
the ForgeKit caller's configured native harness and approved credentials.
From a prepared APMX workspace, preview a reviewed package with
`apmx --from richgo/sage-kit/integrations/forgekit#COMMIT --plan`.
For a caller-specific contract, keep the exported verifier and add the
approved file paths to the contract's `needs`. A local gate also needs
`corpus/knowledge.jsonl` in its verification workspace. After the producer
runs, use `apmx check PRODUCER_RECEIPT` with the same factory definition to
run the independent checks before accepting a handoff.

At pipeline start, hash the exact approved input files with SHA-256 and write
a JSON object mapping workspace-relative input paths to their hashes. The pin
binds both the corpus revision and the embedding profile. Make the approved
files available in the check workspace and declare them as inputs in the
consuming APMX contract so the verifier can recompute every digest.

```sh
sagekit pin approved-input-digests.json > sagekit-pin.json
sagekit gate-check sagekit-policy.json --pin sagekit-pin.json > sagekit-context.json
```

| Mode | Gate result |
| --- | --- |
| `off` | Skips retrieval and provider calls |
| `advisory` | Reports available evidence, insufficiency, or an unavailable corpus and lets the stage continue |
| `required` | Exits 2 unless the pinned evidence requirements and any requested typed decision are available |

A policy takes a `stage`, contextual `query`, optional `minimum_evidence`
(default 1), `exact_ids`, expected input digest map in `inputs`, and optional
typed `decision` request. The caller computes the expected input digests from
the approved artifacts. Each stage's context points to immutable source
revisions. The parent pipeline's independent verification remains the
authority for release and completion. The APMX handoff includes evidence and
decision availability. The separate CLI or API audit envelope carries any
model advice.

## Promote verified changes

The trusted verifier produces a JSON promotion request after the pipeline has
completed successfully and an architecture or product change has been approved.
Use the following shape with the actual pin and evidence SHA-256.

```json
{
  "schema": 1,
  "pipeline": "owner/repository",
  "run": "123456789",
  "pin": {"schema": 1, "revision": "<corpus revision>", "inputs": {}, "embedding_profile": "<profile ID>", "id": "<pin ID>"},
  "status": "success",
  "approved": true,
  "independently_verified": true,
  "verification": {"uri": "<immutable evidence location>", "sha256": "<evidence hash>"},
  "change": {
    "kind": "architecture",
    "title": "Checkout retry safety",
    "summary": "The approved change passed independent acceptance.",
    "links": ["<approved choice or source record ID from the pinned corpus>"],
    "acl": []
  }
}
```

For GitHub Actions, have the protected verifier attest `promotion.json`
and upload it as `sagekit-verified-promotion` in the same run. Call the
[reusable promotion workflow](../.github/workflows/promote.yml) from a job
that depends on successful verification. Configure the `sagekit-promotion`
environment to require approval and restrict deployments to protected main.
Set its protected variables `SAGEKIT_REVISION`, `SAGEKIT_VERIFIER_WORKFLOW`,
`SAGEKIT_VERIFIER_DIGEST`, and `SAGEKIT_REMOTE_URL` to the reviewed commits,
the full signer workflow path, and the authorized HTTPS origin. Store
`SAGEKIT_RECEIPT_KEY` (at least 32 random bytes of text) and
`SAGEKIT_PROMOTION_TOKEN` as environment secrets. Configure the same receipt
key at the SageKit service. The publishing job verifies the artifact's
attestation against the source commit, signing workflow, and signing
workflow commit before using these credentials. Keep signing credentials
and the promotion token out of build and agent execution.

For Git-backed local publication, the trusted verifier can sign the same
payload with `sagekit sign-receipt` and an authorized publishing checkout
can run `sagekit promote` before opening a reviewed corpus PR. A replay of
the same receipt returns the original ID and event revision. Conflicting
content for an existing pipeline/run is rejected. Publication can be retried
independently using the original verified payload and pin.

## Record operational outcomes

Use `sagekit approve FILE` to record the chosen option before pinning the
pipeline. The JSON fields are `family`, `option`, `context`, `origin`
(`human`, `venn`, `jev`, or `jev-oss`), `source`, and optional `acl`.
Link the choice in the verified change. When an operational measurement exists,
`sagekit observe FILE` accepts `choice_id`, `verification_id`, `metric`,
numeric `utility`, `source`, and optional `acl`. Measure the same utility
consistently across alternatives in a family and specify the decision goal
as `maximize` or `minimize`. The Venn route uses this observed evidence.
A verified build by itself contributes no measured utility.
