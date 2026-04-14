from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from openclaw_trader.app.factory import create_app

from .helpers_v2 import build_test_harness
from .test_v2_agent_gateway import _seed_pending_retro_case, _seed_runtime_bridge_state, _valid_strategy_targets
from .test_v2_workflow_orchestrator import _build_retro_prep_monitor


class ApiIntegrationTests(unittest.TestCase):
    def test_control_endpoint_rejects_legacy_market_commands(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                for index, command_type in enumerate(("dispatch_once", "run_pm", "run_rt", "run_mea"), start=1):
                    response = client.post(
                        "/api/control/commands",
                        json={
                            "command_id": f"cmd-legacy-{index}",
                            "command_type": command_type,
                            "initiator": "risk_trader",
                            "params": {"trigger_type": "cron"},
                        },
                    )
                    self.assertEqual(response.status_code, 409)
                    self.assertFalse(response.json()["detail"]["accepted"])
                    self.assertEqual(response.json()["detail"]["reason"], "legacy_market_workflow_disabled_use_agent_cron")
        finally:
            harness.cleanup()

    def test_all_agent_pull_endpoints_use_cached_runtime_bridge_state_when_available(self) -> None:
        harness = build_test_harness()
        try:
            _seed_runtime_bridge_state(harness)
            app = create_app(harness.container)
            with (
                patch.object(harness.container.market_data, "get_market_overview", side_effect=AssertionError("market_data should not be called")),
                patch.object(harness.container.news_events, "get_latest_news_batch", side_effect=AssertionError("news_events should not be called")),
                patch.object(harness.container.quant_intelligence, "get_latest_forecasts", side_effect=AssertionError("quant should not be called")),
                patch.object(harness.container.memory_assets, "get_latest_strategy", side_effect=AssertionError("strategy should not be called")),
                patch.object(harness.container.memory_assets, "get_asset", side_effect=AssertionError("get_asset should not be called")),
                patch.object(harness.container.memory_assets, "get_macro_memory", side_effect=AssertionError("macro memory should not be called")),
            ):
                with TestClient(app) as client:
                    pm_pack = client.post("/api/agent/pull/pm", json={"trigger_type": "pm_main_cron"})
                    rt_pack = client.post("/api/agent/pull/rt", json={"trigger_type": "cadence"})
                    mea_pack = client.post("/api/agent/pull/mea", json={"trigger_type": "cadence"})
                    chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})

            self.assertEqual(pm_pack.status_code, 200)
            self.assertEqual(rt_pack.status_code, 200)
            self.assertEqual(mea_pack.status_code, 200)
            self.assertEqual(chief_pack.status_code, 200)
            self.assertEqual(pm_pack.json()["payload"]["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(rt_pack.json()["payload"]["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(mea_pack.json()["payload"]["runtime_bridge_state"]["source"], "cache")
            self.assertEqual(chief_pack.json()["payload"]["runtime_bridge_state"]["source"], "cache")
        finally:
            harness.cleanup()

    def test_control_and_query_endpoints(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                pm_pack = client.post(
                    "/api/agent/pull/pm",
                    json={"trigger_type": "pm_main_cron", "params": {"cadence_source": "openclaw_cron"}},
                )
                self.assertEqual(pm_pack.status_code, 200)
                self.assertEqual(pm_pack.json()["trigger_type"], "pm_main_cron")
                response = client.post(
                    "/api/agent/submit/strategy",
                    json={
                        "input_id": pm_pack.json()["input_id"],
                        "portfolio_mode": "normal",
                        "target_gross_exposure_band_pct": [0.0, 5.0],
                        "portfolio_thesis": "query test strategy",
                        "portfolio_invalidation": "query test invalidation",
                        "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                        "change_summary": "query test summary",
                        "targets": _valid_strategy_targets(),
                        "scheduled_rechecks": [],
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["follow_up"]["accepted"])
                self.assertEqual(response.json()["follow_up"]["reason"], "rt_follow_up_disabled_use_agent_cron")
                self.assertTrue(client.get("/api/query/strategy/current").json())
                self.assertTrue(client.get("/api/query/portfolio/current").json())
                self.assertTrue(client.get("/api/query/overview").json()["system"])
                self.assertIn("macro_events", client.get("/api/query/news/current").json())
                self.assertIn("results", client.get("/api/query/executions/recent").json())
                self.assertIn("recent_assets", client.get("/api/query/agents/pm/latest").json())
                self.assertTrue(client.get("/api/query/events").json())
                self.assertTrue(client.get("/api/query/replay").json()["render_hints"])
                self.assertTrue(client.get("/api/query/parameters").json())
                with client.websocket_connect("/api/stream/events") as websocket:
                    message = websocket.receive_json()
                    self.assertIn("overview", message)
                    self.assertIn("events", message)
        finally:
            harness.cleanup()

    def test_agent_pull_and_submit_endpoints(self) -> None:
        harness = build_test_harness(news_severity="high")
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                pm_pack = client.post(
                    "/api/agent/pull/pm",
                    json={"trigger_type": "pm_main_cron", "params": {"cadence_source": "openclaw_cron"}},
                )
                self.assertEqual(pm_pack.status_code, 200)
                self.assertEqual(pm_pack.json()["trigger_type"], "pm_main_cron")
                pm_input_id = pm_pack.json()["input_id"]
                submit_strategy = client.post(
                    "/api/agent/submit/strategy",
                    json={
                        "input_id": pm_input_id,
                        "payload": {
                            "portfolio_mode": "normal",
                            "target_gross_exposure_band_pct": [0.0, 5.0],
                            "portfolio_thesis": "bridge strategy",
                            "portfolio_invalidation": "bridge invalidation",
                            "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                            "change_summary": "bridge summary",
                            "targets": _valid_strategy_targets(),
                            "scheduled_rechecks": [],
                        },
                    },
                )
                self.assertEqual(submit_strategy.status_code, 200)
                self.assertEqual(submit_strategy.json()["strategy"]["trigger_type"], "pm_main_cron")
                self.assertFalse(submit_strategy.json()["follow_up"]["accepted"])
                self.assertEqual(
                    submit_strategy.json()["follow_up"]["reason"],
                    "rt_follow_up_disabled_use_agent_cron",
                )

                rt_pack = client.post("/api/agent/pull/rt", json={"trigger_type": "cadence"})
                self.assertEqual(rt_pack.status_code, 200)
                rt_payload = rt_pack.json()
                self.assertIn("trigger_delta", rt_payload["payload"])
                self.assertIn("standing_tactical_map", rt_payload["payload"])
                self.assertIn("execution_submit_defaults", rt_payload["payload"])
                submit_execution = client.post(
                    "/api/agent/submit/execution",
                    json={
                        "input_id": rt_payload["input_id"],
                        "payload": {
                            "decision_id": "decision-bridge-1",
                            "strategy_id": client.get("/api/query/strategy/current").json()["strategy_id"],
                            "generated_at_utc": "2026-03-21T00:00:00Z",
                            "trigger_type": "cadence",
                            "tactical_map_update": {
                                "map_refresh_reason": "pm_strategy_revision",
                                "portfolio_posture": "先按当前策略初始化战术图。",
                                "desk_focus": "BTC 先按最小动作初始化跟踪。",
                                "risk_bias": "先建立地图，再决定后续节奏。",
                                "coins": [
                                    {
                                        "coin": "BTC",
                                        "working_posture": "初始化观察",
                                        "base_case": "先维持观察，再等待更明确结构。",
                                        "first_entry_plan": "如果当前仍无仓且 BTC 继续 active，就先打 1% 试探仓，不再无限等待。",
                                        "preferred_add_condition": "结构确认后再加。",
                                        "preferred_reduce_condition": "若结构转弱则先减。",
                                        "reference_take_profit_condition": "冲高衰减时部分止盈。",
                                        "reference_stop_loss_condition": "跌破关键位时减仓。",
                                        "no_trade_zone": "噪音区间不追单。",
                                        "force_pm_recheck_condition": "若主逻辑快速失效则要求 PM 重评。",
                                        "next_focus": "先完成地图初始化。",
                                    }
                                ],
                            },
                            "decisions": [
                                {
                                    "symbol": "BTC",
                                    "action": "wait",
                                    "direction": "long",
                                    "reason": "bridge_wait",
                                    "size_pct_of_exposure_budget": 0.0,
                                    "priority": 1,
                                    "urgency": "low",
                                    "valid_for_minutes": 10,
                                }
                            ],
                        },
                    },
                )
                self.assertEqual(submit_execution.status_code, 200)
                self.assertEqual(submit_execution.json()["decision_id"], "decision-bridge-1")

                mea_pack = client.post("/api/agent/pull/mea", json={"trigger_type": "news_batch_ready"})
                self.assertEqual(mea_pack.status_code, 200)
                submit_news = client.post(
                    "/api/agent/submit/news",
                    json={
                        "input_id": mea_pack.json()["input_id"],
                        "payload": {
                            "events": [
                                {
                                    "event_id": "evt-bridge-1",
                                    "category": "macro",
                                    "summary": "Bridge macro shock",
                                    "impact_level": "high",
                                }
                            ]
                        },
                    },
                )
                self.assertEqual(submit_news.status_code, 200)
                self.assertEqual(submit_news.json()["high_impact_count"], 1)

                harness.container.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                    trace_id="trace-chief-prep",
                    trigger_type="daily_retro",
                    force_new_case=True,
                )
                chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack.status_code, 200)
                chief_payload = chief_pack.json()["payload"]
                self.assertTrue(chief_payload["retro_case"])
                self.assertEqual(len(chief_payload["retro_briefs"]), 3)
                self.assertEqual(chief_payload["pending_retro_brief_roles"], [])
                self.assertTrue(chief_payload["retro_ready_for_synthesis"])
                self.assertTrue(chief_payload["learning_targets"])
                self.assertEqual(chief_payload["learning_targets"][0]["session_key"], "agent:pm:main")
                self.assertTrue(chief_payload["retro_pack"]["learning_targets"])
                self.assertEqual(chief_payload["retro_pack"]["learning_targets"][0]["session_key"], "agent:pm:main")
                submit_retro = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack.json()["input_id"],
                        "payload": {
                            "case_id": chief_payload["retro_case"]["case_id"],
                            "owner_summary": "Chief retro submitted from API integration test.",
                            "root_cause_ranking": ["PM 过度保守"],
                            "learning_directives": [
                                {
                                    "agent_role": "pm",
                                    "directive": "把翻向条件写清楚。",
                                    "rationale": "让 RT 有明确翻向边界。",
                                }
                            ],
                        },
                    },
                )
                self.assertEqual(submit_retro.status_code, 200)
                self.assertEqual(
                    submit_retro.json()["owner_summary"],
                    "Chief retro submitted from API integration test.",
                )
                self.assertEqual(submit_retro.json()["case_id"], chief_payload["retro_case"]["case_id"])

                chief_pack_missing_summary = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack_missing_summary.status_code, 200)
                retro_missing_owner_summary = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack_missing_summary.json()["input_id"],
                        "payload": {
                            "case_id": chief_pack_missing_summary.json()["payload"]["retro_case"]["case_id"],
                        },
                    },
                )
                self.assertEqual(retro_missing_owner_summary.status_code, 422)
                self.assertEqual(
                    retro_missing_owner_summary.json()["detail"]["reason"],
                    "retro_submit_owner_summary_required",
                )
        finally:
            harness.cleanup()

    def test_submit_retro_brief_endpoint_accepts_role_runtime_pack(self) -> None:
        harness = build_test_harness()
        try:
            _seed_pending_retro_case(harness)
            app = create_app(harness.container)
            with TestClient(app) as client:
                pm_pack = client.post("/api/agent/pull/pm", json={"trigger_type": "pm_main_cron"})
                self.assertEqual(pm_pack.status_code, 200)
                payload = pm_pack.json()["payload"]
                self.assertTrue(payload["pending_retro_case"])
                self.assertEqual(payload["retro_brief_status"]["state"], "pending")

                submit = client.post(
                    "/api/agent/submit/retro-brief",
                    json={
                        "input_id": pm_pack.json()["input_id"],
                        "payload": {
                            "case_id": payload["pending_retro_case"]["case_id"],
                            "root_cause": "PM 过度保守。",
                            "cross_role_challenge": "RT 需要更主动，但 PM 先要给清晰边界。",
                            "self_critique": "翻向条件写得不够可交易。",
                            "tomorrow_change": "明天把 flip triggers 写成明确动作。",
                        },
                    },
                )
                self.assertEqual(submit.status_code, 200)
                self.assertEqual(submit.json()["agent_role"], "pm")
                self.assertEqual(submit.json()["case_id"], payload["pending_retro_case"]["case_id"])
        finally:
            harness.cleanup()

    def test_submit_retro_brief_endpoint_rejects_wrong_case_id(self) -> None:
        harness = build_test_harness()
        try:
            _seed_pending_retro_case(harness)
            app = create_app(harness.container)
            with TestClient(app) as client:
                rt_pack = client.post("/api/agent/pull/rt", json={"trigger_type": "cadence"})
                self.assertEqual(rt_pack.status_code, 200)
                submit = client.post(
                    "/api/agent/submit/retro-brief",
                    json={
                        "input_id": rt_pack.json()["input_id"],
                        "payload": {
                            "case_id": "retro_case_wrong",
                            "root_cause": "RT 过度等待。",
                            "cross_role_challenge": "PM 需要给更清晰边界。",
                            "self_critique": "没有在高把握窗口主动推进。",
                            "tomorrow_change": "明天在高把握窗口更主动 add/reduce。",
                        },
                    },
                )
                self.assertEqual(submit.status_code, 422)
                self.assertEqual(submit.json()["detail"]["reason"], "retro_brief_case_mismatch")
        finally:
            harness.cleanup()

    def test_query_chief_latest_returns_retro_cycle_and_learning_completion(self) -> None:
        harness = build_test_harness()
        try:
            cycle_state, retro_case = _seed_pending_retro_case(harness)
            harness.container.memory_assets.save_asset(
                asset_type="chief_retro",
                asset_id="chief-retro-query",
                trace_id="trace-chief-retro-query",
                actor_role="crypto_chief",
                payload={
                    "retro_id": "chief-retro-query",
                    "case_id": retro_case["case_id"],
                    "cycle_id": cycle_state["cycle_id"],
                    "owner_summary": "Chief retro completed.",
                    "learning_directives": [],
                    "learning_directive_ids": [],
                },
            )
            harness.container.memory_assets.materialize_learning_directive(
                trace_id="trace-learning-query",
                case_id=retro_case["case_id"],
                cycle_id=cycle_state["cycle_id"],
                agent_role="pm",
                session_key="agent:pm:main",
                learning_path="/tmp/pm-learning-query.md",
                actor_role="system",
                authored_payload={
                    "directive": "把翻向条件写清楚。",
                    "rationale": "让 RT 有明确边界。",
                    "completion_state": "completed",
                    "completed_at_utc": "2026-04-12T23:00:00+00:00",
                },
            )
            app = create_app(harness.container)
            with TestClient(app) as client:
                response = client.get("/api/query/agents/crypto_chief/latest")
                self.assertEqual(response.status_code, 200)
                retro_chain = response.json()["retro_chain"]
                self.assertEqual(retro_chain["retro_cycle_state"]["cycle_id"], cycle_state["cycle_id"])
                self.assertEqual(retro_chain["chief_retro"]["payload"]["case_id"], retro_case["case_id"])
                self.assertEqual(retro_chain["learning_directives"][0]["completion_state"], "completed")
        finally:
            harness.cleanup()

    def test_submit_retro_endpoint_rejects_legacy_fields(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                harness.container.agent_gateway.prepare_retro_cycle_from_runtime_bridge(
                    trace_id="trace-chief-prep-legacy-fields",
                    trigger_type="daily_retro",
                    force_new_case=True,
                )
                chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack.status_code, 200)
                submit = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack.json()["input_id"],
                        "payload": {
                            "case_id": chief_pack.json()["payload"]["retro_case"]["case_id"],
                            "owner_summary": "legacy field test",
                            "round_count": 1,
                        },
                    },
                )
                self.assertEqual(submit.status_code, 422)
                self.assertEqual(submit.json()["detail"]["reason"], "retro_submit_legacy_fields_forbidden")
        finally:
            harness.cleanup()

    def test_full_retro_happy_path_end_to_end(self) -> None:
        harness = build_test_harness()
        try:
            monitor, runner = _build_retro_prep_monitor(harness)
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            app = create_app(harness.container)
            with TestClient(app) as client:
                prep = monitor.scan_once(now=now)
                self.assertEqual(prep["status"], "ready")
                self.assertTrue(prep["chief_dispatched"])
                self.assertEqual(runner.runs, ["chief-job"])

                chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack.status_code, 200)
                case_id = chief_pack.json()["payload"]["retro_case"]["case_id"]
                cycle_id = chief_pack.json()["payload"]["retro_cycle_state"]["cycle_id"]

                submit = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack.json()["input_id"],
                        "payload": {
                            "case_id": case_id,
                            "owner_summary": "Chief retro completed.",
                            "root_cause_ranking": ["PM 过度保守", "RT 过度等待", "MEA 提醒过密"],
                            "role_judgements": {
                                "pm": "方向判断基本正确，但 band 过窄。",
                                "risk_trader": "执行纪律稳定，但主动性不足。",
                                "macro_event_analyst": "提醒质量尚可，但去重不够。",
                            },
                            "learning_directives": [
                                {"agent_role": "pm", "directive": "把翻向条件写清楚。", "rationale": "让 RT 有明确边界。"},
                                {"agent_role": "risk_trader", "directive": "高把握窗口更主动 add/reduce。", "rationale": "提高窗口利用率。"},
                                {"agent_role": "macro_event_analyst", "directive": "只在状态变化时升级提醒。", "rationale": "降低重复打断。"},
                                {"agent_role": "crypto_chief", "directive": "继续维护异步 artifact 链。", "rationale": "避免回退到同步会。"},
                            ],
                        },
                    },
                )
                self.assertEqual(submit.status_code, 200)

                post_retro = monitor.scan_once(now=now + timedelta(minutes=2))
                self.assertEqual(post_retro["status"], "completed")
                directives = harness.container.memory_assets.get_learning_directives(case_id=case_id, cycle_id=cycle_id)
                self.assertEqual(len(directives), 4)
                self.assertTrue(all(item["completion_state"] == "pending" for item in directives))

                pm_pack = client.post("/api/agent/pull/pm", json={"trigger_type": "pm_main_cron"})
                self.assertEqual(pm_pack.status_code, 200)
                self.assertEqual(len(pm_pack.json()["payload"]["pending_learning_directives"]), 1)

                for learning_path in harness.container.agent_gateway.learning_path_by_role.values():
                    path = Path(learning_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("updated from self-improving-agent\n", encoding="utf-8")

                monitor.scan_once(now=now + timedelta(minutes=3), force=True)
                directives = harness.container.memory_assets.get_learning_directives(case_id=case_id, cycle_id=cycle_id)
                self.assertTrue(all(item["completion_state"] == "completed" for item in directives))

                chief_state = client.get("/api/query/agents/crypto_chief/latest")
                self.assertEqual(chief_state.status_code, 200)
                retro_chain = chief_state.json()["retro_chain"]
                self.assertEqual(retro_chain["retro_cycle_state"]["cycle_id"], cycle_id)
                self.assertEqual(len(retro_chain["briefs"]), 3)
                self.assertEqual(len(retro_chain["learning_directives"]), 4)
                self.assertTrue(all(item["completion_state"] == "completed" for item in retro_chain["learning_directives"]))
        finally:
            harness.cleanup()

    def test_full_retro_degraded_path_end_to_end(self) -> None:
        harness = build_test_harness()
        try:
            now = datetime(2026, 4, 12, 22, 45, tzinfo=UTC)
            cycle_state, retro_case = _seed_pending_retro_case(harness, trade_day_utc=now.date().isoformat())
            harness.container.memory_assets.materialize_retro_brief(
                trace_id="trace-retro-pm-only",
                case_id=retro_case["case_id"],
                cycle_id=cycle_state["cycle_id"],
                agent_role="pm",
                authored_payload={
                    "root_cause": "PM 过度保守。",
                    "cross_role_challenge": "RT 需要更主动。",
                    "self_critique": "band 不够锋利。",
                    "tomorrow_change": "明天把边界写清楚。",
                },
            )
            harness.container.memory_assets.save_retro_cycle_state(
                trace_id="trace-retro-degraded",
                cycle_id=cycle_state["cycle_id"],
                payload={
                    **cycle_state,
                    "retro_case_id": retro_case["case_id"],
                    "brief_deadline_utc": (now - timedelta(minutes=1)).isoformat(),
                    "ready_brief_roles": ["pm"],
                    "missing_brief_roles": ["risk_trader", "macro_event_analyst"],
                },
            )
            monitor, runner = _build_retro_prep_monitor(harness)
            app = create_app(harness.container)
            with TestClient(app) as client:
                prep = monitor.scan_once(now=now)
                self.assertEqual(prep["status"], "degraded")
                self.assertTrue(prep["chief_dispatched"])
                self.assertEqual(runner.runs, ["chief-job"])

                chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack.status_code, 200)
                self.assertEqual(
                    sorted(chief_pack.json()["payload"]["pending_retro_brief_roles"]),
                    ["macro_event_analyst", "risk_trader"],
                )

                submit = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack.json()["input_id"],
                        "payload": {
                            "case_id": retro_case["case_id"],
                            "owner_summary": "Chief degraded retro completed.",
                            "learning_directives": [
                                {"agent_role": "pm", "directive": "pm directive", "rationale": "pm rationale"},
                                {"agent_role": "risk_trader", "directive": "rt directive", "rationale": "rt rationale"},
                                {"agent_role": "macro_event_analyst", "directive": "mea directive", "rationale": "mea rationale"},
                                {"agent_role": "crypto_chief", "directive": "chief directive", "rationale": "chief rationale"},
                            ],
                        },
                    },
                )
                self.assertEqual(submit.status_code, 200)
                final_scan = monitor.scan_once(now=now + timedelta(minutes=2))
                self.assertEqual(final_scan["status"], "degraded")
                final_cycle = harness.container.memory_assets.latest_retro_cycle_state(trade_day_utc=now.date().isoformat())
                self.assertEqual(final_cycle["state"], "degraded")
                self.assertEqual(final_cycle["degraded_reason"], "missing_briefs")
        finally:
            harness.cleanup()

    def test_pull_rt_refreshes_portfolio_query_view(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/query/portfolio/current").json(), {})
                rt_pack = client.post("/api/agent/pull/rt", json={"trigger_type": "manual"})
                self.assertEqual(rt_pack.status_code, 200)
                portfolio = client.get("/api/query/portfolio/current")
                self.assertEqual(portfolio.status_code, 200)
                payload = portfolio.json()
                self.assertEqual(payload["total_equity_usd"], "1000")
                self.assertEqual(payload["positions"][0]["coin"], "BTC")
        finally:
            harness.cleanup()

    def test_agent_submit_endpoints_accept_flat_payload_shape(self) -> None:
        harness = build_test_harness(news_severity="high")
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                pm_pack = client.post("/api/agent/pull/pm", json={"trigger_type": "pm_main_cron"})
                self.assertEqual(pm_pack.status_code, 200)
                self.assertEqual(pm_pack.json()["trigger_type"], "pm_main_cron")
                pm_input_id = pm_pack.json()["input_id"]
                submit_strategy = client.post(
                    "/api/agent/submit/strategy",
                    json={
                        "input_id": pm_input_id,
                        "portfolio_mode": "normal",
                        "target_gross_exposure_band_pct": [0.0, 5.0],
                        "portfolio_thesis": "flat bridge strategy",
                        "portfolio_invalidation": "flat bridge invalidation",
                        "flip_triggers": "flip when multi-horizon structure and macro regime both reverse",
                        "change_summary": "flat bridge summary",
                        "targets": _valid_strategy_targets(),
                        "scheduled_rechecks": [],
                    },
                )
                self.assertEqual(submit_strategy.status_code, 200)
                self.assertEqual(submit_strategy.json()["strategy"]["trigger_type"], "pm_main_cron")
                self.assertFalse(submit_strategy.json()["follow_up"]["accepted"])
                self.assertEqual(
                    submit_strategy.json()["follow_up"]["reason"],
                    "rt_follow_up_disabled_use_agent_cron",
                )

                mea_pack = client.post("/api/agent/pull/mea", json={"trigger_type": "news_batch_ready"})
                self.assertEqual(mea_pack.status_code, 200)
                submit_news = client.post(
                    "/api/agent/submit/news",
                    json={
                        "input_id": mea_pack.json()["input_id"],
                        "events": [
                            {
                                "event_id": "evt-flat-1",
                                "category": "macro",
                                "summary": "Flat bridge macro shock",
                                "impact_level": "high",
                            }
                        ],
                    },
                )
                self.assertEqual(submit_news.status_code, 200)
                self.assertEqual(submit_news.json()["high_impact_count"], 1)
        finally:
            harness.cleanup()

    def test_pull_pm_endpoint_audits_direct_message_and_unspecified_wakeups(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                agent_message = client.post(
                    "/api/agent/pull/pm",
                    json={
                        "trigger_type": "agent_message",
                        "params": {
                            "wake_source": "sessions_send",
                            "source_role": "risk_trader",
                            "reason": "target band stale after breakout failure",
                            "severity": "high",
                        },
                    },
                )
                self.assertEqual(agent_message.status_code, 200)
                self.assertEqual(agent_message.json()["trigger_type"], "agent_message")
                self.assertEqual(
                    agent_message.json()["payload"]["latest_pm_trigger_event"]["trigger_category"],
                    "message",
                )
                self.assertEqual(
                    agent_message.json()["payload"]["latest_pm_trigger_event"]["wake_source"],
                    "sessions_send",
                )

                unspecified = client.post("/api/agent/pull/pm", json={})
                self.assertEqual(unspecified.status_code, 200)
                self.assertEqual(unspecified.json()["trigger_type"], "agent_message")
                self.assertEqual(
                    unspecified.json()["payload"]["latest_pm_trigger_event"]["trigger_category"],
                    "message",
                )
                self.assertEqual(
                    unspecified.json()["payload"]["latest_pm_trigger_event"]["audit_origin"],
                    "agent_gateway_pull_fallback_recent_message",
                )
        finally:
            harness.cleanup()

    def test_agent_submit_endpoints_reject_invalid_json_with_400(self) -> None:
        harness = build_test_harness()
        try:
            app = create_app(harness.container)
            with TestClient(app) as client:
                response = client.post(
                    "/api/agent/submit/retro",
                    data='{"input_id":"oops\\qad"}',
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["reason"], "invalid_json")
        finally:
            harness.cleanup()

    @staticmethod
    def _wait_for_workflow(client: TestClient, trace_id: str, *, timeout_seconds: float = 5.0):
        deadline = time.monotonic() + timeout_seconds
        response = client.get(f"/api/query/workflows/{trace_id}")
        while time.monotonic() < deadline:
            if response.status_code == 200 and response.json()["state"] in {"completed", "degraded", "failed"}:
                return response
            time.sleep(0.05)
            response = client.get(f"/api/query/workflows/{trace_id}")
        return response


if __name__ == "__main__":
    unittest.main()
