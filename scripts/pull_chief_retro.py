#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import request


def build_submission_scaffold(pack: dict) -> dict:
    payload = dict(pack.get("payload") or {})
    retro_pack = dict(payload.get("retro_pack") or {})
    return {
        "owner_summary": "",
        "reset_command": "/new",
        "learning_completed": False,
        "learning_results": [],
        "transcript": [],
        "round_count": None,
        "meeting_id": None,
        "_operator_hint": (
            "Fill owner_summary and any optional fields in this file, then submit it with submit_chief_retro.py. "
            "Keep input_id outside the payload file."
        ),
        "_retro_pack_snapshot": {
            "news_event_count": len(retro_pack.get("news_events") or []),
            "execution_context_count": len(retro_pack.get("execution_contexts") or []),
            "recent_execution_result_count": len(retro_pack.get("recent_execution_results") or []),
            "recent_news_submission_count": len(retro_pack.get("recent_news_submissions") or []),
            "learning_target_count": len(retro_pack.get("learning_targets") or payload.get("learning_targets") or []),
        },
    }


def summarize_pack(pack: dict, output_path: Path, submission_scaffold_path: Path) -> dict:
    payload = dict(pack.get("payload") or {})
    retro_pack = dict(payload.get("retro_pack") or {})
    return {
        "output_path": str(output_path),
        "submission_scaffold_path": str(submission_scaffold_path),
        "input_id": pack.get("input_id"),
        "trace_id": pack.get("trace_id"),
        "trigger_type": pack.get("trigger_type"),
        "runtime_bridge_state": payload.get("runtime_bridge_state"),
        "trigger_context": payload.get("trigger_context"),
        "retro_pack_summary": {
            "news_event_count": len(retro_pack.get("news_events") or []),
            "execution_context_count": len(retro_pack.get("execution_contexts") or []),
            "macro_memory_count": len(retro_pack.get("macro_memory") or []),
            "recent_execution_result_count": len(retro_pack.get("recent_execution_results") or []),
            "recent_news_submission_count": len(retro_pack.get("recent_news_submissions") or []),
            "learning_target_count": len(retro_pack.get("learning_targets") or payload.get("learning_targets") or []),
            "strategy_id": dict(retro_pack.get("strategy") or {}).get("strategy_id"),
        },
        "operator_hint": "Edit the scaffold file instead of hand-writing a long POST body on the command line.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull Chief retro runtime pack and prepare a submit scaffold.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/pull/chief-retro")
    parser.add_argument("--trigger-type", default="daily_retro")
    parser.add_argument("--output", default="/tmp/chief_retro_pack.json")
    parser.add_argument("--submission-scaffold-output", default="/tmp/chief_retro_submission.json")
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

    submission_scaffold = build_submission_scaffold(pack)
    submission_scaffold_path = Path(args.submission_scaffold_output)
    submission_scaffold_path.write_text(
        json.dumps(submission_scaffold, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summarize_pack(pack, output_path, submission_scaffold_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
