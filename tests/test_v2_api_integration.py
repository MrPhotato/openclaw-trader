from __future__ import annotations

import time
import unittest

from fastapi.testclient import TestClient

from openclaw_trader.app.factory import create_app

from .helpers_v2 import build_test_harness


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
                        "change_summary": "query test summary",
                        "targets": [],
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
                            "change_summary": "bridge summary",
                            "targets": [],
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
                submit_execution = client.post(
                    "/api/agent/submit/execution",
                    json={
                        "input_id": rt_payload["input_id"],
                        "payload": {
                            "decision_id": "decision-bridge-1",
                            "strategy_id": client.get("/api/query/strategy/current").json()["strategy_id"],
                            "generated_at_utc": "2026-03-21T00:00:00Z",
                            "trigger_type": "cadence",
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

                chief_pack = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack.status_code, 200)
                submit_retro = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack.json()["input_id"],
                        "owner_summary": "Chief retro submitted from API integration test.",
                        "round_count": 2,
                        "learning_completed": True,
                    },
                )
                self.assertEqual(submit_retro.status_code, 200)
                self.assertEqual(
                    submit_retro.json()["owner_summary"],
                    "Chief retro submitted from API integration test.",
                )
                self.assertEqual(submit_retro.json()["round_count"], 2)

                chief_pack_missing_summary = client.post("/api/agent/pull/chief-retro", json={"trigger_type": "daily_retro"})
                self.assertEqual(chief_pack_missing_summary.status_code, 200)
                retro_missing_owner_summary = client.post(
                    "/api/agent/submit/retro",
                    json={
                        "input_id": chief_pack_missing_summary.json()["input_id"],
                    },
                )
                self.assertEqual(retro_missing_owner_summary.status_code, 422)
                self.assertEqual(
                    retro_missing_owner_summary.json()["detail"]["reason"],
                    "retro_submit_owner_summary_required",
                )
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
                        "change_summary": "flat bridge summary",
                        "targets": [],
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
                self.assertEqual(unspecified.json()["trigger_type"], "pm_unspecified")
                self.assertEqual(
                    unspecified.json()["payload"]["latest_pm_trigger_event"]["trigger_category"],
                    "unknown",
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
