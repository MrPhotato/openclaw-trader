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
        self.assertEqual(scaffold["reset_command"], "/new")
        self.assertFalse(scaffold["learning_completed"])
        self.assertEqual(scaffold["learning_results"], [])
        self.assertEqual(scaffold["transcript"], [])
        self.assertIsNone(scaffold["round_count"])
        self.assertIsNone(scaffold["meeting_id"])
        self.assertEqual(scaffold["_retro_pack_snapshot"]["news_event_count"], 1)
        self.assertEqual(scaffold["_retro_pack_snapshot"]["execution_context_count"], 1)

    def test_pull_chief_retro_summary_reports_counts(self) -> None:
        pack = {
            "input_id": "input-chief-2",
            "trace_id": "trace-chief-2",
            "trigger_type": "daily_retro",
            "payload": {
                "runtime_bridge_state": {"source": "cache"},
                "trigger_context": {"trigger_type": "daily_retro"},
                "retro_pack": {
                    "news_events": [{"event_id": "evt-1"}, {"event_id": "evt-2"}],
                    "execution_contexts": [{"symbol": "BTC"}],
                    "macro_memory": [{"headline": "memo"}],
                    "recent_execution_results": [{"result_id": "res-1"}],
                    "recent_news_submissions": [{"submission_id": "news-1"}, {"submission_id": "news-2"}],
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
        self.assertEqual(summary["retro_pack_summary"]["news_event_count"], 2)
        self.assertEqual(summary["retro_pack_summary"]["macro_memory_count"], 1)
        self.assertEqual(summary["retro_pack_summary"]["strategy_id"], "strategy-1")

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

    def test_submit_chief_retro_preflight_requires_owner_summary(self) -> None:
        ok, detail = SUBMIT_CHIEF_RETRO.preflight_payload(
            {
                "meeting_id": "retro-test-1",
                "owner_summary": "   ",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(detail["reason"], "owner_summary_required")

    def test_submit_chief_retro_preflight_accepts_valid_payload(self) -> None:
        ok, detail = SUBMIT_CHIEF_RETRO.preflight_payload(
            {
                "meeting_id": "retro-test-2",
                "owner_summary": "Chief retro landed successfully.",
                "round_count": 2,
                "learning_completed": True,
            }
        )
        self.assertTrue(ok)
        self.assertEqual(detail, {})


if __name__ == "__main__":
    unittest.main()
