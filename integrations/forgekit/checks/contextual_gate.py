"""APMX actor and verifier entry point. Policy and pin belong to the trusted caller."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from sagekit.gates import validate_pin


def verify_inputs(pinned, workspace: Path):
    validate_pin(pinned)
    for name, expected in pinned["inputs"].items():
        relative = Path(name)
        path = (workspace / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(workspace) or not path.is_file():
            raise ValueError("pinned input must be a file inside the verification workspace")
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("approved input bytes differ from the pin")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        policy = json.loads(Path("sagekit-policy.json").read_text(encoding="utf-8"))
        if policy.get("mode", "off") != "off":
            pinned = json.loads(Path("sagekit-pin.json").read_text(encoding="utf-8"))
            verify_inputs(pinned, Path.cwd().resolve())
        result = subprocess.run(
            [sys.executable, "-m", "sagekit", "gate-check", "sagekit-policy.json",
             "--pin", "sagekit-pin.json"], capture_output=True, text=True,
        )
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr)
            return result.returncode
        fresh = json.loads(result.stdout)
        decision = fresh.pop("decision", None)
        if decision is not None:
            # This artefact certifies evidence availability. Typed advice stays in
            # the provider's separate audit envelope and is never an APMX handoff.
            fresh["decision_status"] = decision["status"]
        if "judgments" in fresh:
            # Replay the policy dispositions and evidence, not the probability estimates.
            fresh["judgments"] = {
                key: {field: outcome[field] for field in ("request_id", "kind", "status", "provider")}
                for key, outcome in fresh["judgments"].items()
            }
            for record in fresh["evidence"]:
                record.get("knowledge", {}).pop("answer", None)
        output = Path("sagekit-context.json")
        if args.check:
            reported = json.loads(output.read_text(encoding="utf-8"))
            if reported != fresh:
                raise ValueError("SageKit output differs from independently checked evidence")
        else:
            output.write_text(json.dumps(fresh, sort_keys=True) + "\n", encoding="utf-8")
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        print(f"sagekit-context: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
