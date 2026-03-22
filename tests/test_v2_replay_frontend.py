from __future__ import annotations

import unittest

from openclaw_trader.modules.replay_frontend import ReplayFrontendService

from .helpers_v2 import build_test_harness


class ReplayFrontendServiceTests(unittest.TestCase):
    def test_query_returns_timeline(self) -> None:
        harness = build_test_harness()
        try:
            service = ReplayFrontendService(harness.container.state_memory)
            view = service.query()
            self.assertEqual(view.render_hints["mode"], "timeline")
        finally:
            harness.cleanup()


if __name__ == "__main__":
    unittest.main()
