import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sagekit.application import Application, Principal
from sagekit.gates import pin, signed
from sagekit.repository import LocalRepository
from test_foundation import record


@unittest.skipUnless(os.getenv("SAGEKIT_TEST_FORGEKIT"), "requires a pinned ForgeKit checkout")
class ForgeKitLifecycle(unittest.TestCase):
    def test_verified_forgekit_run_and_failed_replay(self):
        forge = Path(os.environ["SAGEKIT_TEST_FORGEKIT"]).resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "build"
            repo = LocalRepository(root / "corpus")
            precedent = record()
            repo.append(precedent)
            inputs = {name: hashlib.sha256((forge / name).read_bytes()).hexdigest()
                      for name in ("examples/requirements.json", "architecture/slice.json")}
            pinned = pin(repo.snapshot(), inputs)
            key = b"fixture-protected-signer-key-at-least-32"
            app = Application(repo, receipt_key=key)
            principal = Principal(scopes=frozenset({"promote"}))
            policy = {"mode": "required", "stage": "architecture", "query": precedent.id,
                      "exact_ids": [precedent.id], "inputs": inputs}
            self.assertTrue(app.gate_check(principal, policy, pinned)["allowed"])

            check = Path(__file__).resolve().parents[1] / "integrations/forgekit/checks/contextual_gate.py"
            (root / "sagekit-pin.json").write_text(json.dumps(pinned), encoding="utf-8")
            (root / "sagekit-policy.json").write_text(json.dumps(policy), encoding="utf-8")
            runner = [sys.executable, str(check)]
            subprocess.run(runner, cwd=root, check=True, capture_output=True)
            subprocess.run(runner + ["--check"], cwd=root, check=True, capture_output=True)
            report = root / "sagekit-context.json"
            forged = json.loads(report.read_text(encoding="utf-8"))
            forged["snapshot"] = "0" * 64
            report.write_text(json.dumps(forged), encoding="utf-8")
            rejected = subprocess.run(runner + ["--check"], cwd=root, capture_output=True)
            self.assertNotEqual(0, rejected.returncode)

            command = ["node", str(forge / "factory/cli.mjs")]
            subprocess.run(command + ["run", str(output)], cwd=forge, check=True, capture_output=True)
            subprocess.run(command + ["verify", str(output)], cwd=forge, check=True, capture_output=True)
            evidence = output / "receipt.json"
            payload = {
                "schema": 1, "pipeline": "forgekit-fixture", "run": "42", "pin": pinned,
                "status": "success", "approved": True, "independently_verified": True,
                "verification": {"uri": "forge:receipt.json",
                                 "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()},
                "change": {"kind": "architecture", "title": "Verified checkout",
                           "summary": "Independent ForgeKit verifier accepted the build",
                           "links": [precedent.id]},
            }
            receipt = signed(payload, key)
            self.assertEqual(app.promote(principal, receipt), app.promote(principal, receipt))
            self.assertEqual(1, len(repo.records(pinned["revision"])))
            (output / "deployed.mjs").write_text("throw new Error('tampered');")
            failed = subprocess.run(command + ["verify", str(output)], cwd=forge, capture_output=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertEqual(2, len(repo.records()))
