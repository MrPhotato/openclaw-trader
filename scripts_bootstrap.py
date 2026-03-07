from openclaw_trader.bootstrap import ensure_runtime_layout
from openclaw_trader.state import StateStore

ensure_runtime_layout()
StateStore()
print('bootstrapped')
