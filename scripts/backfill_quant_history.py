from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from openclaw_trader.config.models import (
    AgentSettings,
    BusSettings,
    ExecutionSettings,
    NotificationSettings,
    QuantSettings,
    StorageSettings,
    SystemSettings,
    WorkflowSettings,
)

from _quant_history_bundle import prepare_history_bundle


def build_settings(runtime_root: Path) -> SystemSettings:
    return SystemSettings(
        runtime_root=runtime_root,
        bus=BusSettings(rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/%2F", exchange_name="history.topic"),
        storage=StorageSettings(sqlite_path=runtime_root / "state" / "history.db"),
        quant=QuantSettings(bootstrap_snapshot_exchange="binance_usdm"),
        execution=ExecutionSettings(
            exchange="coinbase_intx",
            supported_coins=["BTC", "ETH", "SOL"],
            live_enabled=False,
            max_leverage=5.0,
            max_total_exposure_pct_of_exposure_budget=100.0,
            max_order_share_pct_of_exposure_budget=66.0,
            max_position_share_pct_of_exposure_budget=100.0,
        ),
        workflow=WorkflowSettings(owner_channel="history", owner_to="history", owner_account_id="history"),
        agents=AgentSettings(),
        notification=NotificationSettings(default_channel="history", default_recipient="history"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill QI long-history candles and hybrid snapshot features.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--end-at", type=str, default=None)
    args = parser.parse_args()

    output_root = args.output_root
    runtime_root = args.runtime_root or (output_root / "_runtime")
    settings = build_settings(runtime_root)
    if args.end_at:
        frozen_end = datetime.fromisoformat(args.end_at).astimezone(UTC)
    else:
        frozen_end = None
    manifest = prepare_history_bundle(output_root, settings=settings, end_at=frozen_end)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
