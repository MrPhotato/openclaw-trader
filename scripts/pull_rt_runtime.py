#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import request


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull RT runtime pack and print a compact summary.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/pull/rt")
    parser.add_argument("--trigger-type", default="condition_trigger")
    parser.add_argument("--output", default="/tmp/rt_runtime_pack.json")
    args = parser.parse_args()

    req = request.Request(
        args.url,
        data=json.dumps({"trigger_type": args.trigger_type}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        pack = json.load(response)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = dict(pack.get("payload") or {})
    summary = {
        "output_path": str(output_path),
        "input_id": pack.get("input_id"),
        "trace_id": pack.get("trace_id"),
        "trigger_type": pack.get("trigger_type"),
        "runtime_bridge_state": payload.get("runtime_bridge_state"),
        "trigger_delta": payload.get("trigger_delta"),
        "standing_tactical_map": payload.get("standing_tactical_map"),
        "rt_decision_digest": payload.get("rt_decision_digest"),
        "execution_submit_defaults": payload.get("execution_submit_defaults"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
