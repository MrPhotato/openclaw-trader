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
    "payload",
}


def preflight_payload(payload: dict) -> tuple[bool, dict]:
    forbidden_top = sorted(key for key in FORBIDDEN_TOP_LEVEL_KEYS if key in payload)
    owner_summary = str(payload.get("owner_summary") or "").strip()
    if forbidden_top:
        return False, {
            "ok": False,
            "reason": "payload_wrapper_fields_present",
            "forbidden_top_level_keys": forbidden_top,
            "hint": "payload-file must contain only the root RetroSubmission object. Keep input_id outside the file; submit_chief_retro.py wraps it for you.",
        }
    if not owner_summary:
        return False, {
            "ok": False,
            "reason": "owner_summary_required",
            "hint": "owner_summary must be a non-empty string before submit.",
        }
    return True, {}


def summarize_result(result: dict) -> dict:
    return {
        "ok": True,
        "trace_id": result.get("trace_id"),
        "input_id": result.get("input_id"),
        "retro_id": result.get("retro_id"),
        "meeting_id": result.get("meeting_id"),
        "round_count": result.get("round_count"),
        "learning_completed": result.get("learning_completed"),
        "owner_summary": result.get("owner_summary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit Chief retro outcome.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/submit/retro")
    parser.add_argument("--input-id", required=True)
    parser.add_argument("--payload-file", required=True)
    args = parser.parse_args()

    payload_path = Path(args.payload_file)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    ok, detail = preflight_payload(payload)
    if not ok:
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 2

    submit_body = {
        "input_id": args.input_id,
        "payload": payload,
    }
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

    print(json.dumps(summarize_result(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
