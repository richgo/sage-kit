"""Deterministic Copilot protocol fixture for the APMX package test."""

import json
import subprocess
import sys


def main():
    if sys.argv[1:] == ["--version"]:
        print("copilot sagekit-fixture 1.0")
        return 0
    if sys.argv[-3:] == ["mcp", "list", "--json"]:
        print(json.dumps({"mcpServers": {}}))
        return 0
    if "-p" not in sys.argv:
        raise ValueError("unexpected APMX actor invocation")
    result = subprocess.run([sys.executable, "checks/contextual_gate.py"], check=False)
    print(json.dumps({"type": "result", "exitCode": result.returncode,
                      "sessionId": "sagekit-fixture", "usage": {}}), flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
