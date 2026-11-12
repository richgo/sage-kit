---
needs:
  - sagekit-pin.json
  - sagekit-policy.json
produces: sagekit-context.json
verify:
  contextual-evidence: python checks/contextual_gate.py --check
---

Use the immutable policy and input pin supplied by the pipeline. Run
`python checks/contextual_gate.py` to produce `sagekit-context.json`.
Treat contextual evidence as advice. Keep independent verification and
release requirements in the parent ForgeKit pipeline. This contract has no
publication authority.
