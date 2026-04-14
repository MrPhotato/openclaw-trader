from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_module:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PULL_CHIEF_RETRO = _load_module(
    "pull_chief_retro",
    "/Users/chenzian/openclaw-trader/scripts/pull_chief_retro.py",
)
SUBMIT_CHIEF_RETRO = _load_module(
    "submit_chief_retro",
    "/Users/chenzian/openclaw-trader/scripts/submit_chief_retro.py",
)


class ChiefRetroScriptTests(unittest.TestCase):
    def test_pull_chief_retro_builds_submission_scaffold(self) -> None:
        pack = {
            "input_id": "input-chief-1",
            "trace_id": "trace-chief-1",
            "trigger_type": "daily_retro",
            "payload": {
                "retro_cycle_state": {"cycle_id": "cycle-1", "state": "chief_pending"},
                "retro_case": {"case_id": "case-1"},
                "retro_briefs": [{"agent_role": "pm"}],
                "retro_pack": {
                    "news_events": [{"event_id": "evt-1"}],
                    "execution_contexts": [{"symbol": "BTC"}],
                    "recent_execution_results": [{"result_id": "res-1"}],
                    "recent_news_submissions": [{"submission_id": "news-1"}],
                }
            },
        }
        scaffold = PULL_CHIEF_RETRO.build_submission_scaffold(pack)
        self.assertEqual(scaffold["owner_summary"], "")
        self.assertEqual(scaffold["case_id"], "case-1")
        self.assertEqual(scaffold["root_cause_ranking"], [])
        self.assertEqual(scaffold["role_judgements"], {})
        self.assertEqual(scaffold["learning_directives"], [])
        self.assertNotIn("transcript", scaffold)
        self.assertNotIn("round_count", scaffold)
        self.assertNotIn("meeting_id", scaffold)
        self.assertEqual(scaffold["_retro_pack_snapshot"]["cycle_id"], "cycle-1")
        self.assertEqual(scaffold["_retro_pack_snapshot"]["case_id"], "case-1")
        self.assertEqual(scaffold["_retro_pack_snapshot"]["retro_brief_count"], 1)
        self.assertEqual(scaffold["_retro_pack_snapshot"]["pending_retro_brief_roles"], [])
        self.assertFalse(scaffold["_retro_pack_snapshot"]["retro_briefs_ready"])
        self.assertEqual(scaffold["_retro_pack_snapshot"]["news_event_count"], 1)
        self.assertEqual(scaffold["_retro_pack_snapshot"]["execution_context_count"], 1)
        self.assertEqual(scaffold["_retro_pack_snapshot"]["learning_target_count"], 0)
        self.assertIn("先在这个文件中补全", scaffold["_operator_hint"])
        self.assertNotIn("Fill owner_summary", scaffold["_operator_hint"])

    def test_pull_chief_retro_summary_reports_counts(self) -> None:
        pack = {
            "input_id": "input-chief-2",
            "trace_id": "trace-chief-2",
            "trigger_type": "daily_retro",
            "payload": {
                "runtime_bridge_state": {"source": "cache"},
                "trigger_context": {"trigger_type": "daily_retro"},
                "retro_cycle_state": {
                    "cycle_id": "cycle-2",
                    "state": "chief_pending",
                    "missing_brief_roles": [],
                    "chief_dispatch_status": "dispatched",
                },
                "retro_case": {"case_id": "case-2", "target_return_pct": 1.0},
                "retro_briefs": [{"agent_role": "pm"}, {"agent_role": "risk_trader"}, {"agent_role": "macro_event_analyst"}],
                "pending_retro_brief_roles": [],
                "retro_briefs_ready": True,
                "retro_pack": {
                    "news_events": [{"event_id": "evt-1"}, {"event_id": "evt-2"}],
                    "execution_contexts": [{"symbol": "BTC"}],
                    "macro_memory": [{"headline": "memo"}],
                    "recent_execution_results": [{"result_id": "res-1"}],
                    "recent_news_submissions": [{"submission_id": "news-1"}, {"submission_id": "news-2"}],
                    "learning_targets": [{"agent_role": "pm", "session_key": "agent:pm:main"}],
                    "strategy": {"strategy_id": "strategy-1"},
                },
            },
        }
        summary = PULL_CHIEF_RETRO.summarize_pack(
            pack,
            Path("/tmp/chief_retro_pack.json"),
            Path("/tmp/chief_retro_submission.json"),
        )
        self.assertEqual(summary["runtime_bridge_state"]["source"], "cache")
        self.assertEqual(summary["retro_case"]["case_id"], "case-2")
        self.assertEqual(summary["retro_cycle_state"]["cycle_id"], "cycle-2")
        self.assertEqual(summary["retro_pack_summary"]["retro_brief_count"], 3)
        self.assertEqual(summary["retro_pack_summary"]["pending_retro_brief_roles"], [])
        self.assertTrue(summary["retro_pack_summary"]["retro_briefs_ready"])
        self.assertEqual(summary["retro_pack_summary"]["news_event_count"], 2)
        self.assertEqual(summary["retro_pack_summary"]["macro_memory_count"], 1)
        self.assertEqual(summary["retro_pack_summary"]["learning_target_count"], 1)
        self.assertEqual(summary["retro_pack_summary"]["strategy_id"], "strategy-1")
        self.assertIn("优先编辑脚手架文件", summary["operator_hint"])
        self.assertNotIn("Edit the scaffold file", summary["operator_hint"])

    def test_submit_chief_retro_preflight_rejects_wrapper_fields(self) -> None:
        ok, detail = SUBMIT_CHIEF_RETRO.preflight_payload(
            {
                "input_id": "input-should-not-be-here",
                "owner_summary": "retro ok",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(detail["reason"], "payload_wrapper_fields_present")
        self.assertIn("input_id", detail["forbidden_top_level_keys"])
        self.assertIn("只能放根级 RetroSubmission 对象", detail["hint"])
        self.assertNotIn("payload-file must contain only", detail["hint"])

    def test_submit_chief_retro_preflight_requires_owner_summary(self) -> None:
        ok, detail = SUBMIT_CHIEF_RETRO.preflight_payload(
            {
                "owner_summary": "   ",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(detail["reason"], "owner_summary_required")
        self.assertIn("必须是非空字符串", detail["hint"])
        self.assertNotIn("must be a non-empty string", detail["hint"])

    def test_submit_chief_retro_preflight_accepts_valid_payload(self) -> None:
        ok, detail = SUBMIT_CHIEF_RETRO.preflight_payload(
            {
                "owner_summary": "Chief retro landed successfully.",
                "root_cause_ranking": ["PM 过度保守"],
                "role_judgements": {"pm": "方向正确但边界太保守。"},
                "learning_directives": [
                    {
                        "agent_role": "pm",
                        "directive": "把翻向条件写清楚。",
                        "rationale": "让 RT 有明确边界。",
                    }
                ],
            }
        )
        self.assertTrue(ok)
        self.assertEqual(detail, {})


if __name__ == "__main__":
    unittest.main()
