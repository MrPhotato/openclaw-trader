from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.briefs import write_dispatch_brief, write_perp_dispatch_brief
from openclaw_trader.config import AppConfig, DispatchConfig, NewsConfig, PerpConfig, RiskConfig, RuntimeConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.engine import EngineContext, TraderEngine
from openclaw_trader.models import AutopilotDecision, AutopilotPhase, Balance, EntryWorkflowMode, PerpPaperPortfolio, ProductSnapshot, RiskProfile, SignalDecision, SignalSide
from openclaw_trader.state import StateStore


class _FakeClient:
    def list_accounts(self):
        return [
            Balance(currency="USDC", available=Decimal("100"), hold=Decimal("0")),
            Balance(currency="BTC", available=Decimal("0.01"), hold=Decimal("0")),
        ]

    def get_product(self, product_id: str):
        return ProductSnapshot(
            product_id=product_id,
            price=Decimal("70000"),
            base_increment=Decimal("0.00000001"),
            quote_increment=Decimal("0.01"),
            quote_min_size=Decimal("1"),
        )


class BriefWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.runtime = RuntimeConfig(
            app=AppConfig(),
            risk=RiskConfig(),
            news=NewsConfig(),
            perps=PerpConfig(),
            dispatch=DispatchConfig(),
            strategy=StrategyConfig(),
            workflow=WorkflowConfig(),
        )
        self.engine = TraderEngine(
            EngineContext(runtime=self.runtime, client=_FakeClient(), state=self.store)
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_write_dispatch_brief_creates_json_and_markdown(self) -> None:
        json_path = Path(self.tmpdir.name) / "dispatch-brief.json"
        md_path = Path(self.tmpdir.name) / "dispatch-brief.md"
        news_path = Path(self.tmpdir.name) / "news-brief.json"
        news_path.write_text(json.dumps({"summary": "过去24小时新闻风向：macro:1"}))
        decision = AutopilotDecision(
            phase=AutopilotPhase.observe,
            notify_user=True,
            reason="unit_test",
            product_id="BTC-USDC",
            flow_mode=EntryWorkflowMode.confirm,
        )
        with patch("openclaw_trader.briefs.DISPATCH_BRIEF_JSON", json_path), \
             patch("openclaw_trader.briefs.DISPATCH_BRIEF_MD", md_path), \
             patch("openclaw_trader.briefs.NEWS_BRIEF_JSON", news_path):
            payload = write_dispatch_brief(self.engine, decision, "BTC-USDC")
        self.assertEqual(payload["product_id"], "BTC-USDC")
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        self.assertIn("过去24小时新闻风向：macro:1", md_path.read_text())

    def test_write_perp_dispatch_brief_uses_margin_and_leverage_text(self) -> None:
        json_path = Path(self.tmpdir.name) / "dispatch-brief.json"
        md_path = Path(self.tmpdir.name) / "dispatch-brief.md"
        news_path = Path(self.tmpdir.name) / "news-brief-perps.json"
        news_path.write_text(json.dumps({"summary": "过去24小时永续相关新闻风向：macro:1"}), encoding="utf-8")
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="SOL-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="SOL-PERP",
                side=SignalSide.short,
                confidence=0.76,
                reason="unit test",
                risk_profile=RiskProfile.normal,
            ),
            preview={
                "plan": {
                    "action": "open",
                    "side": "short",
                    "notional_usd": "12",
                    "margin_usd": "6",
                    "execution_leverage": "2",
                    "coin": "SOL",
                }
            },
        )
        system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        supervisor = type(
            "FakeSupervisor",
            (),
            {
                "portfolio": lambda self: PerpPaperPortfolio(
                    exchange="coinbase_intx",
                    starting_equity_usd="207.21",
                    realized_pnl_usd="0",
                    unrealized_pnl_usd="0",
                    total_equity_usd="207.21",
                    available_equity_usd="201.21",
                    total_exposure_usd="12",
                    positions=[],
                )
            },
        )()
        review = {
            "decision": "approve",
            "reason": "ok",
            "orders": [
                {
                    "product_id": "SOL-PERP",
                    "decision": "approve",
                    "size_scale": 1.0,
                    "reason": "test",
                    "stop_loss_price": "91",
                    "take_profit_price": "84",
                    "exit_plan": "失效就撤",
                }
            ],
        }
        execution_result = {
            "mode": "batch",
            "count": 1,
            "items": [
                {
                    "product_id": "SOL-PERP",
                    "success": True,
                    "approved_plan": {
                        "action": "open",
                        "side": "short",
                        "notional_usd": "12",
                        "margin_usd": "6",
                        "execution_leverage": "2",
                    },
                    "review": review["orders"][0],
                    "error": None,
                }
            ],
        }
        with patch("openclaw_trader.briefs.DISPATCH_BRIEF_JSON", json_path), \
             patch("openclaw_trader.briefs.DISPATCH_BRIEF_MD", md_path), \
             patch("openclaw_trader.briefs.PERP_NEWS_BRIEF_JSON", news_path):
            write_perp_dispatch_brief(supervisor, system_state, trade_review=review, execution_result=execution_result)
        body = md_path.read_text(encoding="utf-8")
        self.assertIn("原始金额=6 USD, 杠杆=2x", body)
        self.assertIn("止损价=91 | 止盈价=84 | 退出计划=失效就撤", body)

    def test_write_perp_dispatch_brief_includes_transition_context(self) -> None:
        json_path = Path(self.tmpdir.name) / "dispatch-brief.json"
        md_path = Path(self.tmpdir.name) / "dispatch-brief.md"
        news_path = Path(self.tmpdir.name) / "news-brief-perps.json"
        news_path.write_text(json.dumps({"summary": "过去24小时永续相关新闻风向：macro:1"}), encoding="utf-8")
        primary = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.short,
                confidence=0.82,
                reason="unit test",
                risk_profile=RiskProfile.normal,
            ),
            preview={"plan": {"action": "open", "side": "short", "notional_usd": "10", "coin": "BTC"}},
        )
        system_state = type(
            "FakePerpState",
            (),
            {
                "primary": primary,
                "decisions": [primary],
                "latest_news": [],
            },
        )()
        supervisor = type(
            "FakeSupervisor",
            (),
            {
                "portfolio": lambda self: PerpPaperPortfolio(
                    exchange="coinbase_intx",
                    starting_equity_usd="207.21",
                    realized_pnl_usd="0",
                    unrealized_pnl_usd="0",
                    total_equity_usd="207.21",
                    available_equity_usd="201.21",
                    total_exposure_usd="12",
                    positions=[],
                )
            },
        )()
        transition_context = {
            "previous_phase": "observe",
            "previous_reason": "fresh_relevant_news_requires_observation",
            "previous_product_id": "BTC-PERP",
            "current_phase": "trade",
            "current_reason": "paper_trade_candidate_ready",
            "current_product_id": "BTC-PERP",
            "transition": "observe->trade",
            "why_now_unblocked": "上一轮因 fresh_relevant_news_requires_observation 暂不执行；当前转为 paper_trade_candidate_ready，已满足本轮处理条件。",
        }
        with patch("openclaw_trader.briefs.DISPATCH_BRIEF_JSON", json_path), \
             patch("openclaw_trader.briefs.DISPATCH_BRIEF_MD", md_path), \
             patch("openclaw_trader.briefs.PERP_NEWS_BRIEF_JSON", news_path):
            payload = write_perp_dispatch_brief(
                supervisor,
                system_state,
                transition_context=transition_context,
            )
        body = md_path.read_text(encoding="utf-8")
        self.assertEqual(payload["transition_context"], transition_context)
        self.assertIn("状态迁移：", body)
        self.assertIn("previous=observe / fresh_relevant_news_requires_observation / BTC-PERP", body)
        self.assertIn("current=trade / paper_trade_candidate_ready / BTC-PERP", body)
        self.assertIn("transition=observe->trade", body)
        self.assertIn(
            "why_now_unblocked=上一轮因 fresh_relevant_news_requires_observation 暂不执行；当前转为 paper_trade_candidate_ready，已满足本轮处理条件。",
            body,
        )


if __name__ == "__main__":
    unittest.main()
