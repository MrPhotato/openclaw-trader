from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import typer
import uvicorn
from rich import print

from .coinbase import CoinbaseAdvancedClient
from .config import CONFIG_DIR, LOG_DIR, RUN_DIR, load_coinbase_credentials, load_runtime_config, save_app_config, save_workflow_config
from .dispatch import build_dispatcher, run_strategy_refresh
from .engine import EngineContext, TraderEngine
from .maintenance import run_maintenance
from .models import EntryWorkflowMode
from .news.monitor import sync_news
from .perps import build_perp_engine
from .perps.runtime import PerpSupervisor
from .service import app as service_app
from .state import StateStore

app = typer.Typer(no_args_is_help=True)


def build_engine() -> TraderEngine:
    runtime = load_runtime_config()
    credentials = load_coinbase_credentials()
    client = CoinbaseAdvancedClient(credentials)
    state = StateStore()
    return TraderEngine(EngineContext(runtime=runtime, client=client, state=state))


def build_perp_runtime_engine():
    runtime = load_runtime_config()
    state = StateStore()
    return build_perp_engine(runtime, state)


def build_perp_supervisor() -> PerpSupervisor:
    runtime = load_runtime_config()
    state = StateStore()
    engine = build_perp_engine(runtime, state)
    return PerpSupervisor(runtime=runtime, state=state, engine=engine)


def _parse_iso_datetime(value: str, *, option_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise typer.BadParameter(f"{option_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(UTC)


def _parse_today_clock(value: str) -> datetime:
    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        raise typer.BadParameter("--since-today must be HH:MM or HH:MM:SS")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise typer.BadParameter("--since-today must contain numeric time fields") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise typer.BadParameter("--since-today must be a valid local time")
    now_local = datetime.now().astimezone()
    return now_local.replace(hour=hour, minute=minute, second=second, microsecond=0).astimezone(UTC)


def _normalize_perp_side(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in {"long", "short"}:
        raise typer.BadParameter("--side must be long or short")
    return normalized


@app.command()
def doctor() -> None:
    runtime = load_runtime_config()
    payload = {
        "config_dir": str(CONFIG_DIR),
        "dispatch_market_mode": runtime.dispatch.market_mode,
        "mode": runtime.app.mode.value,
        "allow_live_orders": runtime.app.allow_live_orders,
        "perps": runtime.perps.model_dump(mode="json"),
    }
    if runtime.dispatch.market_mode == "perps":
        engine = build_perp_runtime_engine()
        payload["paper_portfolio"] = engine.account().model_dump(mode="json")
    else:
        creds = load_coinbase_credentials()
        payload["spot"] = {
            "primary_product": runtime.app.primary_product,
            "api_base": creds.api_base,
            "api_key_id_suffix": creds.api_key_id[-8:],
        }
        engine = build_engine()
        payload["balances"] = [b.model_dump(mode="json") for b in engine.balances()]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def accounts() -> None:
    engine = build_engine()
    print(json.dumps([b.model_dump(mode="json") for b in engine.balances()], indent=2, ensure_ascii=False))


@app.command()
def snapshot(product_id: str | None = None) -> None:
    engine = build_engine()
    snap = engine.market_snapshot(product_id)
    print(json.dumps(snap.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command()
def signal(product_id: str | None = None) -> None:
    engine = build_engine()
    sig, risk = engine.evaluate_signal(product_id)
    print(json.dumps({"signal": sig.model_dump(mode="json"), "risk": risk.model_dump(mode="json")}, indent=2, ensure_ascii=False))


@app.command()
def workflow() -> None:
    runtime = load_runtime_config()
    print(json.dumps(runtime.workflow.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("set-entry-mode")
def set_entry_mode(mode: EntryWorkflowMode) -> None:
    runtime = load_runtime_config()
    runtime.workflow.entry_mode = mode
    save_workflow_config(runtime.workflow)
    print(json.dumps(runtime.workflow.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("set-live-orders")
def set_live_orders(value: Literal["on", "off"]) -> None:
    runtime = load_runtime_config()
    runtime.app.allow_live_orders = value == "on"
    save_app_config(runtime.app)
    print(json.dumps(runtime.app.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("autopilot-check")
def autopilot_check(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.autopilot_check(product_id).model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("autopilot-message")
def autopilot_message(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.autopilot_message(product_id), indent=2, ensure_ascii=False))


@app.command("daily-report")
def daily_report(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.daily_report(product_id), indent=2, ensure_ascii=False))


@app.command("preview-buy")
def preview_buy(quote_size: str = "1.00", product_id: str | None = None) -> None:
    engine = build_engine()
    payload, _ = engine.preview_buy(Decimal(quote_size), product_id)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command("pending-entry")
def pending_entry(product_id: str | None = None) -> None:
    engine = build_engine()
    product_id = product_id or engine.ctx.runtime.app.primary_product
    print(json.dumps(engine.ctx.state.get_pending_entry(product_id), indent=2, ensure_ascii=False))


@app.command("confirm-entry")
def confirm_entry(product_id: str | None = None, yes: bool = typer.Option(False, "--yes", help="Actually submit the confirmed live entry.")) -> None:
    runtime = load_runtime_config()
    if not runtime.app.allow_live_orders:
        raise typer.BadParameter("Live orders are disabled in config/app.yaml")
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm live order submission")
    engine = build_engine()
    print(json.dumps(engine.confirm_pending_entry(product_id), indent=2, ensure_ascii=False))


@app.command("cancel-entry")
def cancel_entry(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.cancel_pending_entry(product_id), indent=2, ensure_ascii=False))


@app.command("panic-check")
def panic_check(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.evaluate_emergency_exit(product_id).model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("preview-exit")
def preview_exit(product_id: str | None = None) -> None:
    engine = build_engine()
    print(json.dumps(engine.preview_exit_all(product_id), indent=2, ensure_ascii=False))


@app.command("buy-live")
def buy_live(quote_size: str = "1.00", product_id: str | None = None, yes: bool = typer.Option(False, "--yes", help="Actually submit the live order.")) -> None:
    runtime = load_runtime_config()
    if not runtime.app.allow_live_orders:
        raise typer.BadParameter("Live orders are disabled in config/app.yaml")
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm live order submission")
    engine = build_engine()
    result = engine.buy_live(Decimal(quote_size), product_id)
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("panic-exit")
def panic_exit(product_id: str | None = None, yes: bool = typer.Option(False, "--yes", help="Actually submit the emergency exit order.")) -> None:
    runtime = load_runtime_config()
    if not runtime.app.allow_live_exits:
        raise typer.BadParameter("Live exits are disabled in config/app.yaml")
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm emergency exit submission")
    engine = build_engine()
    print(json.dumps(engine.panic_exit_live(product_id), indent=2, ensure_ascii=False))


@app.command("run-server")
def run_server() -> None:
    runtime = load_runtime_config()
    uvicorn.run(service_app, host=runtime.app.bind_host, port=runtime.app.bind_port, log_level="info")


@app.command("poll-news")
def poll_news_command() -> None:
    runtime = load_runtime_config()
    state = StateStore()
    sync_news(runtime.news, state)
    items = state.list_recent_news(limit=20)
    print(json.dumps([item.model_dump(mode="json") for item in items], indent=2, ensure_ascii=False))


@app.command("dispatch-once")
def dispatch_once(product_id: str | None = None) -> None:
    dispatcher = build_dispatcher()
    print(json.dumps(dispatcher.dispatch_once(product_id=product_id), indent=2, ensure_ascii=False))


@app.command("strategy-refresh")
def strategy_refresh(
    reason: str = typer.Option("manual_refresh", "--reason", help="Reason label for strategy rewrite"),
    deliver: bool = typer.Option(False, "--deliver", help="Send only the strategy update summary (via main agent) to the configured reply channel; required for manual live refreshes that should replace the active strategy"),
) -> None:
    print(json.dumps(run_strategy_refresh(reason=reason, deliver=deliver), indent=2, ensure_ascii=False))


@app.command("maintenance")
def maintenance() -> None:
    print(json.dumps(run_maintenance(), indent=2, ensure_ascii=False))


@app.command("strategy-show")
def strategy_show() -> None:
    path = Path.home() / ".openclaw-trader" / "reports" / "strategy-day.json"
    if not path.exists():
        print("{}")
        return
    print(path.read_text())


@app.command("run-dispatcher")
def run_dispatcher() -> None:
    dispatcher = build_dispatcher()
    dispatcher.run_forever()


@app.command("perp-snapshot")
def perp_snapshot(coin: str | None = None) -> None:
    engine = build_perp_runtime_engine()
    print(json.dumps(engine.snapshot(coin).model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("perp-account")
def perp_account(coin: str | None = None) -> None:
    engine = build_perp_runtime_engine()
    print(json.dumps(engine.account(coin).model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("perp-signal")
def perp_signal(coin: str | None = typer.Option(None, "--coin", help="Perp coin, default config coin")) -> None:
    supervisor = build_perp_supervisor()
    target_coin = (coin or supervisor.runtime.perps.coin).upper()
    signal, risk = supervisor.evaluate_signal(target_coin)
    print(json.dumps({"signal": signal.model_dump(mode="json"), "risk": risk.model_dump(mode="json")}, indent=2, ensure_ascii=False))


@app.command("perp-order-history")
def perp_order_history(
    coin: str | None = typer.Option(None, "--coin", help="Perp coin filter, default all configured coins"),
    exchange: str | None = typer.Option(None, "--exchange", help="Exchange filter, default current runtime exchange"),
    since: str | None = typer.Option(None, "--since", help="ISO-8601 lower bound, e.g. 2026-03-04T01:00:00+08:00"),
    since_today: str | None = typer.Option(None, "--since-today", help="Local clock time today, e.g. 01:00"),
    until: str | None = typer.Option(None, "--until", help="ISO-8601 upper bound"),
    limit: int = typer.Option(20, "--limit", min=1, max=200, help="Maximum executions to return"),
) -> None:
    if since and since_today:
        raise typer.BadParameter("Use either --since or --since-today, not both")
    runtime = load_runtime_config()
    state = StateStore()
    since_dt = _parse_iso_datetime(since, option_name="--since") if since else None
    if since_today:
        since_dt = _parse_today_clock(since_today)
    until_dt = _parse_iso_datetime(until, option_name="--until") if until else None
    target_exchange = exchange or runtime.perps.exchange
    rows = state.list_perp_fills(
        exchange=target_exchange,
        coin=coin,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )
    print(
        json.dumps(
            {
                "exchange": target_exchange,
                "coin": coin.upper() if coin else None,
                "since": since_dt.isoformat() if since_dt else None,
                "until": until_dt.isoformat() if until_dt else None,
                "count": len(rows),
                "fills": rows,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@app.command("perp-model-status")
def perp_model_status(coin: str | None = typer.Option(None, "--coin", help="Perp coin, default config coin")) -> None:
    supervisor = build_perp_supervisor()
    target_coin = (coin or supervisor.runtime.perps.coin).upper()
    print(json.dumps(supervisor.model_status(target_coin), indent=2, ensure_ascii=False))


@app.command("perp-panic-lock-status")
def perp_panic_lock_status() -> None:
    supervisor = build_perp_supervisor()
    print(json.dumps(supervisor.panic_protection_status(), indent=2, ensure_ascii=False))


@app.command("perp-panic-resume")
def perp_panic_resume(
    yes: bool = typer.Option(False, "--yes", help="Clear active panic cooldowns / global breaker immediately."),
) -> None:
    if not yes:
        raise typer.BadParameter("Pass --yes to clear active panic cooldowns / global breaker")
    supervisor = build_perp_supervisor()
    print(json.dumps(supervisor.clear_panic_protection(), indent=2, ensure_ascii=False))


@app.command("perp-model-train")
def perp_model_train(coin: str | None = typer.Option(None, "--coin", help="Perp coin, default config coin")) -> None:
    supervisor = build_perp_supervisor()
    target_coin = (coin or supervisor.runtime.perps.coin).upper()
    payload = supervisor.model_service.train_models(target_coin)
    print(json.dumps(payload["meta"], indent=2, ensure_ascii=False))


@app.command("perp-open-paper")
def perp_open_paper(
    side: str = typer.Option(..., "--side", help="long or short"),
    notional_usd: str = typer.Option(..., "--notional-usd", help="USD notional"),
    leverage: str = typer.Option("2", "--leverage", help="Leverage"),
    coin: str | None = typer.Option(None, "--coin", help="Perp coin, default BTC"),
) -> None:
    engine = build_perp_runtime_engine()
    side_value = _normalize_perp_side(side)
    result = engine.open_paper(
        side=side_value,
        notional_usd=Decimal(notional_usd),
        leverage=Decimal(leverage),
        coin=coin,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("perp-close-paper")
def perp_close_paper(coin: str | None = typer.Option(None, "--coin", help="Perp coin, default BTC")) -> None:
    engine = build_perp_runtime_engine()
    result = engine.close_paper(coin)
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("perp-open-live")
def perp_open_live(
    side: str = typer.Option(..., "--side", help="long or short"),
    notional_usd: str = typer.Option(..., "--notional-usd", help="USD notional"),
    leverage: str = typer.Option("2", "--leverage", help="Leverage"),
    coin: str | None = typer.Option(None, "--coin", help="Perp coin, default BTC"),
) -> None:
    engine = build_perp_runtime_engine()
    side_value = _normalize_perp_side(side)
    result = engine.open_live(
        side=side_value,
        notional_usd=Decimal(notional_usd),
        leverage=Decimal(leverage),
        coin=coin,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
