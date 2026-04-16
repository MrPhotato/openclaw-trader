# Perps Convergence Inventory

Goal: document the current convergence state accurately. The active production path is OpenClaw/WeCom -> `crypto-chief` -> `openclaw-trader` -> Coinbase INTX live perpetuals. Spot-era code and secondary adapters still exist, but they are transitional or compatibility paths.

## Delete Later

These are legacy artifacts that should be physically removed only after the active perps/live path is fully stable and all callers have migrated.

- `src/openclaw_trader/engine.py`
- Spot-only HTTP endpoints in `src/openclaw_trader/service.py`
- Spot-only CLI commands in `src/openclaw_trader/cli.py`
- stale docs that still describe the system as Hyperliquid-first or paper-first

## Refactor Now

These are still part of the codebase, but the semantics are wrong or transitional.

- `PerpConfig.max_order_pct_of_equity`
- `PerpConfig.max_position_pct_of_equity`
- Strategy JSON/Markdown fields:
  - `max_order_pct`
  - `max_position_pct`
- `StrategyConfig.track_products` should become perps-native symbols/coins rather than reusing spot product naming.
- `DispatchConfig.market_mode` should become transitional only; active dispatch should be perps-first.
- `PerpConfig.coin` is redundant next to `coins`.
- `coinbase-trader` skill/docs keep a historical name, but should describe Coinbase INTX live as the default fact source.
- Hyperliquid adapter and paper-specific commands should be treated as compatibility/testing paths unless promoted back into production.

## Keep

These remain core even after convergence to live perps.

- `max_total_exposure_pct_of_equity`
- `max_leverage`
- `position_observe_drawdown_pct`
- `position_reduce_drawdown_pct`
- `position_exit_drawdown_pct`
- `emergency_exit_enabled`
- `emergency_exit_on_exchange_status`
- `entry_mode`
- `strategy-day` rewrite controls
- model configuration
- workflow news freshness / notification cooldowns
- Coinbase INTX live infrastructure
- perps engine abstraction for secondary adapters
- WeCom / OpenClaw integration

## Current Strategy Rewrite Controls (Live)

These are the active rewrite and notification semantics in production:

- scheduled rewrite slots at 09:00 and 21:00 (`daily_hours`)
- global rewrite cooldown: 30 minutes (`rewrite_cooldown_minutes`)
- regime-shift rewrite requires both:
  - 3 consecutive observations (`regime_shift_confirmation_rounds`)
  - at least 15 minutes persistence (`regime_shift_confirmation_minutes`)
- regime-shift rewrites have an extra 180-minute cooldown (`regime_shift_rewrite_cooldown_minutes`)
- `exchange-status` can rewrite strategy only for high severity or market-relevant status keywords
- strategy update notifications are sent only when the rewrite is material (regime/risk/invalidators/bias or configured size/leverage deltas)
- manual live strategy refresh without delivery remains blocked (`manual_refresh`, `manual_refresh_no_notify`) to avoid silent overwrite

## Migration Order

1. Add regression protection around dispatcher, strategy-day parsing, perps runtime, and config loading.
2. Keep docs aligned with the actual production path: Coinbase INTX live, BTC/ETH, strategy-day-driven exposure budgets.
3. Convert remaining tactical sizing and naming drift to exposure-budget semantics everywhere.
4. Decide explicitly whether Hyperliquid stays as a secondary adapter/test path or should be removed.
5. Only then physically delete unused spot-era code and stale compatibility layers.
