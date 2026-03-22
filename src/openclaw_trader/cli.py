from __future__ import annotations

import json

import httpx
import typer
import uvicorn
from rich import print

from .config.loader import load_system_settings
from .service import app as service_app


app = typer.Typer(no_args_is_help=True, help="openclaw-trader v2 control/query client")


def _base_url() -> str:
    settings = load_system_settings()
    return f"http://{settings.app.bind_host}:{settings.app.bind_port}"


@app.command("serve")
def serve() -> None:
    settings = load_system_settings()
    uvicorn.run(service_app, host=settings.app.bind_host, port=settings.app.bind_port, log_level="info")


@app.command("command")
def command(
    command_type: str,
    command_id: str | None = None,
    initiator: str = "cli",
) -> None:
    payload = {
        "command_id": command_id or f"cmd-{command_type}",
        "command_type": command_type,
        "initiator": initiator,
        "scope": {},
        "params": {},
    }
    response = httpx.post(f"{_base_url()}/api/control/commands", json=payload, timeout=30.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("workflow")
def workflow(trace_id: str) -> None:
    response = httpx.get(f"{_base_url()}/api/query/workflows/{trace_id}", timeout=30.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("strategy")
def strategy() -> None:
    response = httpx.get(f"{_base_url()}/api/query/strategy/current", timeout=30.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("portfolio")
def portfolio() -> None:
    response = httpx.get(f"{_base_url()}/api/query/portfolio/current", timeout=30.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("events")
def events(trace_id: str | None = None, module: str | None = None, limit: int = 50) -> None:
    response = httpx.get(
        f"{_base_url()}/api/query/events",
        params={"trace_id": trace_id, "module": module, "limit": limit},
        timeout=30.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("replay")
def replay(trace_id: str | None = None, module: str | None = None) -> None:
    response = httpx.get(
        f"{_base_url()}/api/query/replay",
        params={"trace_id": trace_id, "module": module},
        timeout=30.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


@app.command("parameters")
def parameters() -> None:
    response = httpx.get(f"{_base_url()}/api/query/parameters", timeout=30.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
