#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import request


def build_submission_scaffold(pack: dict) -> dict:
    payload = dict(pack.get("payload") or {})
    retro_pack = dict(payload.get("retro_pack") or {})
    retro_cycle_state = dict(payload.get("retro_cycle_state") or {})
    retro_case = dict(payload.get("retro_case") or {})
    retro_briefs = list(payload.get("retro_briefs") or [])
    pending_retro_brief_roles = list(payload.get("pending_retro_brief_roles") or [])
    return {
        "owner_summary": "",
        "case_id": str(retro_case.get("case_id") or "") or None,
        "root_cause_ranking": [],
        "role_judgements": {},
        "learning_directives": [],
        "_operator_hint": (
            "先在这个文件中补全 `owner_summary`、`root_cause_ranking`、`role_judgements` 和 `learning_directives`，再用 submit_chief_retro.py 提交。"
            " `input_id` 保持在 payload 文件外层，不要写进来。"
        ),
        "_retro_pack_snapshot": {
            "cycle_id": str(retro_cycle_state.get("cycle_id") or retro_case.get("cycle_id") or ""),
            "case_id": str(retro_case.get("case_id") or ""),
            "retro_brief_count": len(retro_briefs),
            "pending_retro_brief_roles": pending_retro_brief_roles,
            "retro_briefs_ready": bool(payload.get("retro_briefs_ready") or payload.get("retro_ready_for_synthesis")),
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
    retro_cycle_state = dict(payload.get("retro_cycle_state") or {})
    retro_case = dict(payload.get("retro_case") or {})
    retro_briefs = list(payload.get("retro_briefs") or [])
    pending_retro_brief_roles = list(payload.get("pending_retro_brief_roles") or [])
    return {
        "output_path": str(output_path),
        "submission_scaffold_path": str(submission_scaffold_path),
        "input_id": pack.get("input_id"),
        "trace_id": pack.get("trace_id"),
        "trigger_type": pack.get("trigger_type"),
        "runtime_bridge_state": payload.get("runtime_bridge_state"),
        "trigger_context": payload.get("trigger_context"),
        "retro_case": {
            "case_id": retro_case.get("case_id"),
            "target_return_pct": retro_case.get("target_return_pct"),
        }
        if retro_case
        else None,
        "retro_cycle_state": {
            "cycle_id": retro_cycle_state.get("cycle_id"),
            "state": retro_cycle_state.get("state"),
            "missing_brief_roles": retro_cycle_state.get("missing_brief_roles") or [],
            "chief_dispatch_status": retro_cycle_state.get("chief_dispatch_status"),
        }
        if retro_cycle_state
        else None,
        "retro_pack_summary": {
            "retro_brief_count": len(retro_briefs),
            "pending_retro_brief_roles": pending_retro_brief_roles,
            "retro_briefs_ready": bool(payload.get("retro_briefs_ready") or payload.get("retro_ready_for_synthesis")),
            "news_event_count": len(retro_pack.get("news_events") or []),
            "execution_context_count": len(retro_pack.get("execution_contexts") or []),
            "macro_memory_count": len(retro_pack.get("macro_memory") or []),
            "recent_execution_result_count": len(retro_pack.get("recent_execution_results") or []),
            "recent_news_submission_count": len(retro_pack.get("recent_news_submissions") or []),
            "learning_target_count": len(retro_pack.get("learning_targets") or payload.get("learning_targets") or []),
            "strategy_id": dict(retro_pack.get("strategy") or {}).get("strategy_id"),
        },
        "operator_hint": "优先编辑脚手架文件，不要在命令行里手写长 JSON 请求体。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取 Chief retro 运行时包，并生成可直接编辑的提交脚手架。")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/pull/chief-retro")
    parser.add_argument("--trigger-type", default="daily_retro")
    parser.add_argument("--output", default="/tmp/chief_retro_pack.json")
    parser.add_argument("--submission-scaffold-output", default="/tmp/chief_retro_submission.json")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    req = request.Request(
        args.url,
        data=json.dumps({"trigger_type": args.trigger_type}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=int(args.timeout_seconds)) as response:
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
