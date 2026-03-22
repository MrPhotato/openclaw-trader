from __future__ import annotations

import os
import unittest

from openclaw_trader.shared.infra import RabbitMQEventBus
from openclaw_trader.shared.protocols import EventFactory


@unittest.skipUnless(os.getenv("OPENCLAW_TEST_RABBITMQ_URL"), "requires OPENCLAW_TEST_RABBITMQ_URL")
class RabbitMqIntegrationTests(unittest.TestCase):
    def test_publish_event_to_real_broker(self) -> None:
        bus = RabbitMQEventBus(url=os.environ["OPENCLAW_TEST_RABBITMQ_URL"], exchange_name="openclaw.test")
        try:
            bus.publish(
                EventFactory.build(
                    trace_id="trace-test",
                    event_type="test.integration.rabbitmq",
                    source_module="test_suite",
                    entity_type="integration_event",
                    payload={"ok": True},
                )
            )
        finally:
            bus.close()


if __name__ == "__main__":
    unittest.main()
