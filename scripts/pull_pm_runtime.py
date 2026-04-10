#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import request


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull PM runtime pack and print a compact audit-aware summary.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/pull/pm")
    parser.add_argument("--trigger-type", default="pm_unspecified")
    parser.add_argument("--wake-source", default=None)
    parser.add_argument("--source-role", default=None)
    parser.add_argument("--source-session-key", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--severity", default=None)
    parser.add_argument("--source-message-excerpt", default=None)
    parser.add_argument("--output", default="/tmp/pm_runtime_pack.json")
    args = parser.parse_args()

    params: dict[str, str] = {}
    if args.wake_source:
        params["wake_source"] = args.wake_source
    if args.source_role:
        params["source_role"] = args.source_role
    if args.source_session_key:
        params["source_session_key"] = args.source_session_key
    if args.reason:
        params["reason"] = args.reason
    if args.severity:
        params["severity"] = args.severity
    if args.source_message_excerpt:
        params["source_message_excerpt"] = args.source_message_excerpt

    req = request.Request(
        args.url,
        data=json.dumps({"trigger_type": args.trigger_type, "params": params}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        pack = json.load(response)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = dict(pack.get("payload") or {})
    latest_pm_trigger_event = dict(payload.get("latest_pm_trigger_event") or {})
    summary = {
        "output_path": str(output_path),
        "input_id": pack.get("input_id"),
        "trace_id": pack.get("trace_id"),
        "trigger_type": pack.get("trigger_type"),
        "latest_pm_trigger_event": latest_pm_trigger_event,
        "runtime_bridge_state": payload.get("runtime_bridge_state"),
        "strategy_summary": {
            "previous_strategy": dict(payload.get("previous_strategy") or {}),
            "latest_risk_brake_event": dict(payload.get("latest_risk_brake_event") or {}),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
