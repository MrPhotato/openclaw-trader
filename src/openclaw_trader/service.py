from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .coinbase import CoinbaseAdvancedClient
from .config import load_coinbase_credentials, load_runtime_config
from .engine import EngineContext, TraderEngine
from .news.monitor import sync_news
from .perps import build_perp_engine
from .state import StateStore


class BuyRequest(BaseModel):
    product_id: str | None = None
    quote_size: str = "1.00"


class ExitRequest(BaseModel):
    product_id: str | None = None


class PerpOpenRequest(BaseModel):
    coin: str | None = None
    side: str = "long"
    notional_usd: str = "10"
    leverage: str = "2"


def _normalize_perp_side(side: str) -> str:
    normalized = str(side).strip().lower()
    if normalized not in {"long", "short"}:
        raise HTTPException(status_code=422, detail="side must be long or short")
    return normalized


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


def build_perp_supervisor():
    runtime = load_runtime_config()
    state = StateStore()
    engine = build_perp_engine(runtime, state)
    from .perps.runtime import PerpSupervisor

    return PerpSupervisor(runtime=runtime, state=state, engine=engine)


app = FastAPI(title="openclaw-trader", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/balances")
def balances():
    engine = build_engine()
    return [b.model_dump(mode="json") for b in engine.balances()]


@app.get("/snapshot")
def snapshot(product_id: str | None = None):
    engine = build_engine()
    snap = engine.market_snapshot(product_id)
    return snap.model_dump(mode="json")


@app.get("/signal")
def signal(product_id: str | None = None):
    engine = build_engine()
    signal_obj, risk = engine.evaluate_signal(product_id)
    return {
        "signal": signal_obj.model_dump(mode="json"),
        "risk": risk.model_dump(mode="json"),
    }


@app.get("/news")
def news():
    runtime = load_runtime_config()
    state = StateStore()
    sync_news(runtime.news, state)
    return [item.model_dump(mode="json") for item in state.list_recent_news(limit=20)]


@app.get("/perps/snapshot")
def perps_snapshot(coin: str | None = None):
    engine = build_perp_runtime_engine()
    return engine.snapshot(coin).model_dump(mode="json")


@app.get("/perps/account")
def perps_account(coin: str | None = None):
    engine = build_perp_runtime_engine()
    return engine.account(coin).model_dump(mode="json")


@app.post("/perps/open-paper")
def perps_open_paper(req: PerpOpenRequest):
    engine = build_perp_runtime_engine()
    result = engine.open_paper(
        side=_normalize_perp_side(req.side),
        notional_usd=Decimal(req.notional_usd),
        leverage=Decimal(req.leverage),
        coin=req.coin,
    )
    return result.model_dump(mode="json")


@app.post("/perps/close-paper")
def perps_close_paper(req: ExitRequest):
    engine = build_perp_runtime_engine()
    return engine.close_paper(req.product_id).model_dump(mode="json")


@app.post("/perps/open-live")
def perps_open_live(req: PerpOpenRequest):
    engine = build_perp_runtime_engine()
    result = engine.open_live(
        side=_normalize_perp_side(req.side),
        notional_usd=Decimal(req.notional_usd),
        leverage=Decimal(req.leverage),
        coin=req.coin,
    )
    return result.model_dump(mode="json")


@app.get("/perps/panic-lock")
def perps_panic_lock():
    supervisor = build_perp_supervisor()
    return supervisor.panic_protection_status()


@app.post("/perps/panic-resume")
def perps_panic_resume():
    supervisor = build_perp_supervisor()
    return supervisor.clear_panic_protection()


@app.get("/workflow")
def workflow():
    runtime = load_runtime_config()
    return runtime.workflow.model_dump(mode="json")


@app.get("/autopilot-check")
def autopilot_check(product_id: str | None = None):
    engine = build_engine()
    return engine.autopilot_check(product_id).model_dump(mode="json")


@app.get("/autopilot-message")
def autopilot_message(product_id: str | None = None):
    engine = build_engine()
    return engine.autopilot_message(product_id)


@app.get("/daily-report")
def daily_report(product_id: str | None = None):
    engine = build_engine()
    return engine.daily_report(product_id)


@app.get("/panic-check")
def panic_check(product_id: str | None = None):
    engine = build_engine()
    return engine.evaluate_emergency_exit(product_id).model_dump(mode="json")


@app.get("/pending-entry")
def pending_entry(product_id: str | None = None):
    engine = build_engine()
    product_id = product_id or engine.ctx.runtime.app.primary_product
    return engine.ctx.state.get_pending_entry(product_id)


@app.post("/preview-buy")
def preview_buy(req: BuyRequest):
    engine = build_engine()
    result, _ = engine.preview_buy(Decimal(req.quote_size), req.product_id)
    return result


@app.post("/buy-live")
def buy_live(req: BuyRequest):
    runtime = load_runtime_config()
    if not runtime.app.allow_live_orders:
        raise HTTPException(status_code=403, detail="Live orders are disabled in config.")
    engine = build_engine()
    result = engine.buy_live(Decimal(req.quote_size), req.product_id)
    return result.model_dump(mode="json")


@app.post("/confirm-entry")
def confirm_entry(req: ExitRequest):
    runtime = load_runtime_config()
    if not runtime.app.allow_live_orders:
        raise HTTPException(status_code=403, detail="Live orders are disabled in config.")
    engine = build_engine()
    return engine.confirm_pending_entry(req.product_id)


@app.post("/cancel-entry")
def cancel_entry(req: ExitRequest):
    engine = build_engine()
    return engine.cancel_pending_entry(req.product_id)


@app.post("/preview-exit")
def preview_exit(req: ExitRequest):
    engine = build_engine()
    return engine.preview_exit_all(req.product_id)


@app.post("/panic-exit")
def panic_exit(req: ExitRequest):
    runtime = load_runtime_config()
    if not runtime.app.allow_live_exits:
        raise HTTPException(status_code=403, detail="Live exits are disabled in config.")
    engine = build_engine()
    return engine.panic_exit_live(req.product_id)
