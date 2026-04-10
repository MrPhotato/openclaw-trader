#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib import request


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decision_id() -> str:
    return f"decision_rt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def _seed_coin_map(payload: dict, coin: str) -> dict:
    thoughts = payload.get("recent_execution_thoughts") or []
    thought = next((item for item in thoughts if (item.get("symbol") or "").upper() == coin.upper()), {})
    focus = next(
        (item for item in ((payload.get("rt_decision_digest") or {}).get("focus_symbols") or []) if (item.get("coin") or "").upper() == coin.upper()),
        {},
    )
    target_state = (focus.get("target_state") or "watch").lower()
    current_side = (focus.get("current_side") or "flat").lower()
    working_posture = {
        "active": "按当前 PM mandate 执行，但避免在无 edge 的延伸段追价。",
        "reduce": "优先控制风险，只在结构重新确认后再谈重新扩大。",
        "disabled": "默认观望，除非 PM 明确重新启用。",
    }.get(target_state, "先观察，只有结构与 risk/reward 明显改善时才出手。")
    if current_side in {"long", "short"} and target_state == "active":
        base_case = "先维护现有仓位质量，围绕更优的位置做小步调整，而不是为了凑目标带硬追。"
        preferred_add_condition = "只有结构延续并出现更优切入位置时再小步加，不在延伸段追价。"
        preferred_reduce_condition = "一旦承接失败、关键回踩位失守或 headline risk 扩张，就先减回观察仓。"
    else:
        base_case = "当前默认不主动出手，等待更高质量的结构、事件或 PM 变化。"
        preferred_add_condition = "只有 PM 重新启用且结构与 risk/reward 同时改善时再考虑建立仓位。"
        preferred_reduce_condition = "若只是观察仓或已禁用，优先继续空仓/轻仓，不为凑目标带硬动作。"
    return {
        "coin": coin,
        "working_posture": working_posture,
        "base_case": base_case,
        "preferred_add_condition": preferred_add_condition,
        "preferred_reduce_condition": preferred_reduce_condition,
        "reference_take_profit_condition": thought.get("reference_take_profit_condition") or "",
        "reference_stop_loss_condition": thought.get("reference_stop_loss_condition") or "",
        "no_trade_zone": "方向不清、波动收缩且没有明确 edge 的区间里不强行动作。",
        "force_pm_recheck_condition": "如果 PM mandate 与盘面结构、headline risk 或风险锁明显不兼容，就联系 PM 重评。",
        "next_focus": focus.get("shape_summary") or "",
    }


def _seed_portfolio_map(payload: dict, trigger_delta: dict) -> dict:
    digest = payload.get("rt_decision_digest") or {}
    strategy = digest.get("strategy_summary") or {}
    focus_symbols = digest.get("focus_symbols") or []
    active = [item.get("coin") for item in focus_symbols if item.get("target_state") == "active" and item.get("coin")]
    posture = {
        "defensive": "防守优先，先保住已有风险预算，再等待更清晰 edge。",
        "normal": "平衡推进，只在更优价格与结构确认时扩大风险。",
        "aggressive": "进攻优先，但仍避免无 edge 的追价。",
    }.get((strategy.get("portfolio_mode") or "").lower(), "围绕当前 PM mandate 做小步、可撤回的战术调整。")
    desk_focus = (
        f"当前重点盯住 {', '.join(active)} 的结构延续与风险事件偏离。"
        if active
        else "当前没有主动进攻腿，优先观察结构、风险锁与 PM mandate 是否重新产生边。"
    )
    risk_bias = (
        "若触发 headline risk、风险锁或关键结构失守，先减风险再谈重新扩张。"
        if strategy.get("portfolio_mode")
        else "默认保守处理，把脑力留给真正改变打法的触发。"
    )
    review_hint = (
        f"下次优先复核 trigger_reason={trigger_delta.get('trigger_reason') or 'unknown'} 对当前战术地图是否仍有效。"
    )
    return {
        "portfolio_posture": posture,
        "desk_focus": desk_focus,
        "risk_bias": risk_bias,
        "next_review_hint": review_hint,
    }


def _build_submission_scaffold(pack: dict) -> dict:
    payload = dict(pack.get("payload") or {})
    defaults = dict(payload.get("execution_submit_defaults") or {})
    trigger_delta = dict(payload.get("trigger_delta") or {})
    standing_map = payload.get("standing_tactical_map")
    focus_symbols = ((payload.get("rt_decision_digest") or {}).get("focus_symbols") or [])
    scaffold = {
        "decision_id": _decision_id(),
        "generated_at_utc": _iso_now(),
        "trigger_type": defaults.get("trigger_type") or pack.get("trigger_type") or "condition_trigger",
        "decisions": [],
    }
    if trigger_delta.get("requires_tactical_map_refresh"):
        if standing_map:
            tactical_map = {
                "map_refresh_reason": trigger_delta.get("tactical_map_refresh_reason") or "manual_refresh",
                "portfolio_posture": standing_map.get("portfolio_posture") or "",
                "desk_focus": standing_map.get("desk_focus") or "",
                "risk_bias": standing_map.get("risk_bias") or "",
                "next_review_hint": standing_map.get("next_review_hint") or "",
                "coins": list(standing_map.get("coins") or []),
            }
        else:
            seeded = _seed_portfolio_map(payload, trigger_delta)
            tactical_map = {
                "map_refresh_reason": trigger_delta.get("tactical_map_refresh_reason") or "initial_map",
                "portfolio_posture": seeded["portfolio_posture"],
                "desk_focus": seeded["desk_focus"],
                "risk_bias": seeded["risk_bias"],
                "next_review_hint": seeded["next_review_hint"],
                "coins": [_seed_coin_map(payload, item.get("coin") or "") for item in focus_symbols if item.get("coin")],
            }
        scaffold["tactical_map_update"] = tactical_map
    return scaffold


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull RT runtime pack and print a compact summary.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/agent/pull/rt")
    parser.add_argument("--trigger-type", default="condition_trigger")
    parser.add_argument("--output", default="/tmp/rt_runtime_pack.json")
    parser.add_argument("--submission-scaffold-output", default="/tmp/rt_execution_submission.json")
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
    scaffold_path = Path(args.submission_scaffold_output)
    scaffold = _build_submission_scaffold(pack)
    scaffold_path.write_text(json.dumps(scaffold, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = dict(pack.get("payload") or {})
    trigger_delta = payload.get("trigger_delta") or {}
    summary = {
        "output_path": str(output_path),
        "submission_scaffold_path": str(scaffold_path),
        "input_id": pack.get("input_id"),
        "trace_id": pack.get("trace_id"),
        "trigger_type": pack.get("trigger_type"),
        "runtime_bridge_state": payload.get("runtime_bridge_state"),
        "trigger_delta": trigger_delta,
        "standing_tactical_map": payload.get("standing_tactical_map"),
        "rt_decision_digest": payload.get("rt_decision_digest"),
        "execution_submit_defaults": payload.get("execution_submit_defaults"),
        "submission_scaffold_includes_tactical_map_update": "tactical_map_update" in scaffold,
        "operator_hint": (
            "Edit /tmp/rt_execution_submission.json instead of composing a fresh JSON batch from scratch."
            if trigger_delta.get("requires_tactical_map_refresh")
            else "Edit /tmp/rt_execution_submission.json; keep tactical_map_update absent unless this round materially refreshes the tactical map."
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
