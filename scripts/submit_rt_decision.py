#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import error, request


FORBIDDEN_TOP_LEVEL_KEYS = {
    "input_id",
    "trace_id",
    "agent_role",
    "task_kind",
    "pm_recheck_request",
    "rt_commentary",
}
FORBIDDEN_DECISION_KEYS = {"execution_params"}


def _preflight_payload(payload: dict) -> tuple[bool, dict]:
    forbidden_top = sorted(key for key in FORBIDDEN_TOP_LEVEL_KEYS if key in payload)
    forbidden_decision = []
    for index, decision in enumerate(payload.get("decisions") or []):
        for key in FORBIDDEN_DECISION_KEYS:
            if key in decision:
                forbidden_decision.append({"decision_index": index, "key": key})
    if forbidden_top or forbidden_decision:
        return False, {
            "ok": False,
            "reason": "payload_wrapper_fields_present",
            "forbidden_top_level_keys": forbidden_top,
            "forbidden_decision_keys": forbidden_decision,
            "hint": "payload-file must contain only the root ExecutionSubmission object. Keep input_id/live outside the file; submit_rt_decision.py wraps them for you.",
        }
    return True, {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit RT execution decision batch.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/submit/execution")
    parser.add_argument("--input-id", required=True)
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--max-notional-usd", type=float, default=None)
    args = parser.parse_args()

    payload_path = Path(args.payload_file)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    ok, detail = _preflight_payload(payload)
    if not ok:
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 2
    submit_body = {
        "input_id": args.input_id,
        "live": bool(args.live),
        "payload": payload,
    }
    if args.max_notional_usd is not None:
        submit_body["max_notional_usd"] = args.max_notional_usd

    req = request.Request(
        args.url,
        data=json.dumps(submit_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": exc.code,
                    "reason": "http_error",
                    "detail": detail,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    summary = {
        "ok": True,
        "decision_id": result.get("decision_id"),
        "strategy_id": result.get("strategy_id"),
        "accepted_count": result.get("accepted_count"),
        "plan_count": result.get("plan_count"),
        "live": result.get("live"),
        "execution_results": result.get("execution_results"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
