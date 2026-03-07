from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openclaw_trader.state import StateStore


class StateStorePendingEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / 'state.db'
        self.store = StateStore(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_pending_entry_roundtrip(self) -> None:
        self.store.upsert_pending_entry(
            product_id='BTC-USDC',
            quote_size_usd='5.00',
            side='BUY',
            reason='test',
            stop_loss_pct=0.012,
            take_profit_pct=0.025,
            confidence=0.8,
            source='unit-test',
            preview_id='preview-1',
            payload={'hello': 'world'},
        )
        row = self.store.get_pending_entry('BTC-USDC')
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row['product_id'], 'BTC-USDC')
        self.assertEqual(row['quote_size_usd'], '5.00')
        self.assertEqual(row['preview_id'], 'preview-1')
        self.assertTrue(row['active'])

    def test_clear_pending_entry(self) -> None:
        self.store.upsert_pending_entry(
            product_id='BTC-USDC',
            quote_size_usd='1.00',
            side='BUY',
            reason='test',
            stop_loss_pct=None,
            take_profit_pct=None,
            confidence=None,
            source='unit-test',
            preview_id=None,
            payload={},
        )
        self.store.clear_pending_entry('BTC-USDC')
        self.assertIsNone(self.store.get_pending_entry('BTC-USDC'))

    def test_list_perp_fills_filters_and_extracts_fill_metadata(self) -> None:
        self.store.record_perp_paper_fill(
            exchange='coinbase_intx',
            coin='ETH',
            action='open_live',
            side='long',
            notional_usd='134.62',
            leverage='1.0',
            price='1985.6',
            realized_pnl_usd=None,
            payload={
                'fills': [
                    {
                        'order_id': 'order-eth-1',
                        'trade_time': '2026-03-04T01:00:24+08:00',
                        'product_id': 'ETH-PERP-INTX',
                        'size': '0.0200',
                        'size_in_quote': False,
                        'commission': '0.0010',
                        'fillSource': 'MATCH',
                    },
                    {
                        'order_id': 'order-eth-1',
                        'trade_time': '2026-03-04T01:00:24+08:00',
                        'product_id': 'ETH-PERP-INTX',
                        'size': '0.0478',
                        'size_in_quote': False,
                        'commission': '0.0035',
                        'fillSource': 'MATCH',
                    }
                ]
            },
        )
        self.store.record_perp_paper_fill(
            exchange='hyperliquid',
            coin='BTC',
            action='open',
            side='short',
            notional_usd='10',
            leverage='2',
            price='70000',
            realized_pnl_usd=None,
            payload={},
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE perp_paper_fills SET created_at = ? WHERE id = 1",
                ('2026-03-03T17:00:24+00:00',),
            )
            conn.execute(
                "UPDATE perp_paper_fills SET created_at = ? WHERE id = 2",
                ('2026-03-03T16:00:00+00:00',),
            )
            conn.commit()

        rows = self.store.list_perp_fills(
            exchange='coinbase_intx',
            since=datetime(2026, 3, 3, 16, 59, tzinfo=UTC),
            limit=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['coin'], 'ETH')
        self.assertEqual(rows[0]['order_id'], 'order-eth-1')
        self.assertEqual(rows[0]['executed_at'], '2026-03-04T01:00:24+08:00')
        self.assertEqual(rows[0]['product_id'], 'ETH-PERP-INTX')
        self.assertEqual(rows[0]['size'], '0.0678')
        self.assertFalse(rows[0]['size_in_quote'])
        self.assertEqual(rows[0]['commission_usd'], '0.0045')
        self.assertIsNone(rows[0]['realized_pnl_usd'])

    def test_acquire_timed_lock_blocks_until_ttl_expires(self) -> None:
        key = "dispatch:test-lock"
        now = datetime(2026, 3, 5, 3, 0, tzinfo=UTC)
        self.assertTrue(self.store.acquire_timed_lock(key, ttl_seconds=300, now=now))
        self.assertFalse(self.store.acquire_timed_lock(key, ttl_seconds=300, now=now + timedelta(seconds=60)))
        self.assertTrue(self.store.acquire_timed_lock(key, ttl_seconds=300, now=now + timedelta(seconds=301)))


if __name__ == '__main__':
    unittest.main()
