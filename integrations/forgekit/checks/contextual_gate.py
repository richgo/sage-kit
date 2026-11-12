"""APMX actor and verifier entry point. Policy and pin belong to the trusted caller."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = subprocess.run(
        [sys.executable, "-m", "sagekit", "gate-check", "sagekit-policy.json",
         "--pin", "sagekit-pin.json"], capture_output=True, text=True,
    )
    if result.returncode:
        print(result.stdout + result.stderr, file=sys.stderr)
        return result.returncode
    fresh = json.loads(result.stdout)
    output = Path("sagekit-context.json")
    if args.check:
        reported = json.loads(output.read_text(encoding="utf-8"))
        # Providers can vary. Verify the pinned context and deterministic evidence.
        fields = ("schema", "stage", "mode", "snapshot", "policy_id", "evidence")
        if any(fresh.get(key) != reported.get(key) for key in fields):
            print("SageKit contextual evidence differs from the independently computed result",
                  file=sys.stderr)
            return 1
    else:
        output.write_text(result.stdout, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
