from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from ..modules.agent_gateway.service import RuntimeInputLeaseError, SubmissionValidationError
from ..modules.workflow_orchestrator.models import CommandType, ManualTriggerCommand


class WorkflowCommandRequest(BaseModel):
    command_id: str
    command_type: CommandType
    initiator: str
    scope: dict = {}
    params: dict = {}
    requested_at: str | None = None


class AgentPullRequest(BaseModel):
    trigger_type: str | None = None
    params: dict = {}


class AgentSubmitRequest(BaseModel):
    input_id: str
    payload: dict = {}
    live: bool = False
    max_notional_usd: float | None = None


def _normalize_agent_submit_body(raw: dict) -> AgentSubmitRequest:
    payload = raw.get("payload")
    if payload is None:
        payload = {
            key: value
            for key, value in raw.items()
            if key not in {"input_id", "live", "max_notional_usd"}
        }
    request = {
        "input_id": raw.get("input_id"),
        "payload": payload,
        "live": raw.get("live", False),
        "max_notional_usd": raw.get("max_notional_usd"),
    }
    return AgentSubmitRequest.model_validate(request)


async def _parse_agent_submit_request(request: Request) -> AgentSubmitRequest:
    try:
        raw = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "invalid_json",
                "message": "Request body must be valid JSON.",
                "error": str(exc),
            },
        ) from exc
    try:
        return _normalize_agent_submit_body(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "invalid_submit_request",
                "message": "Submit body must include a valid input_id.",
                "errors": exc.errors(),
            },
        ) from exc


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/api/control/commands", status_code=202)
    def submit_command(req: WorkflowCommandRequest, request: Request):
        container = request.app.state.container
        payload = req.model_dump(exclude_none=True)
        command = ManualTriggerCommand.model_validate(payload)
        receipt = container.workflow_orchestrator.submit_command(command)
        if not receipt.accepted:
            raise HTTPException(status_code=409, detail=receipt.model_dump(mode="json"))
        return receipt.model_dump(mode="json")

    @router.post("/api/agent/pull/pm")
    def pull_pm_runtime_input(req: AgentPullRequest, request: Request):
        container = request.app.state.container
        payload = container.agent_gateway.pull_pm_runtime_input(
            trigger_type=req.trigger_type or "pm_unspecified",
            params=req.params,
        )
        return payload.model_dump(mode="json")

    @router.post("/api/agent/pull/rt")
    def pull_rt_runtime_input(req: AgentPullRequest, request: Request):
        container = request.app.state.container
        payload = container.agent_gateway.pull_rt_runtime_input(
            trigger_type=req.trigger_type or "cadence",
            params=req.params,
        )
        return payload.model_dump(mode="json")

    @router.post("/api/agent/pull/mea")
    def pull_mea_runtime_input(req: AgentPullRequest, request: Request):
        container = request.app.state.container
        payload = container.agent_gateway.pull_mea_runtime_input(
            trigger_type=req.trigger_type or "cadence",
            params=req.params,
        )
        return payload.model_dump(mode="json")

    @router.post("/api/agent/pull/chief-retro")
    def pull_chief_retro_pack(req: AgentPullRequest, request: Request):
        container = request.app.state.container
        payload = container.agent_gateway.pull_chief_retro_pack(
            trigger_type=req.trigger_type or "daily_retro",
            params=req.params,
        )
        return payload.model_dump(mode="json")

    @router.post("/api/agent/submit/strategy")
    async def submit_strategy(request: Request):
        container = request.app.state.container
        req = await _parse_agent_submit_request(request)
        try:
            result = container.agent_gateway.submit_strategy(input_id=req.input_id, payload=req.payload)
        except RuntimeInputLeaseError as exc:
            raise HTTPException(status_code=409, detail={"reason": exc.reason, "input_id": exc.input_id}) from exc
        except SubmissionValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": "submission_validation_failed",
                    "schema_ref": exc.schema_ref,
                    "prompt_ref": exc.prompt_ref,
                    "errors": exc.errors,
                },
            ) from exc
        return {
            **result,
            "follow_up": {
                "accepted": False,
                "reason": "rt_follow_up_disabled_use_agent_cron",
            },
        }

    @router.post("/api/agent/submit/execution")
    async def submit_execution(request: Request):
        container = request.app.state.container
        req = await _parse_agent_submit_request(request)
        try:
            result = container.agent_gateway.submit_execution(
                input_id=req.input_id,
                payload=req.payload,
                live=req.live,
                max_notional_usd=req.max_notional_usd,
            )
        except RuntimeInputLeaseError as exc:
            raise HTTPException(status_code=409, detail={"reason": exc.reason, "input_id": exc.input_id}) from exc
        except SubmissionValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": "submission_validation_failed",
                    "schema_ref": exc.schema_ref,
                    "prompt_ref": exc.prompt_ref,
                    "errors": exc.errors,
                },
            ) from exc
        return result

    @router.post("/api/agent/submit/news")
    async def submit_news(request: Request):
        container = request.app.state.container
        req = await _parse_agent_submit_request(request)
        try:
            result = container.agent_gateway.submit_news(input_id=req.input_id, payload=req.payload)
        except RuntimeInputLeaseError as exc:
            raise HTTPException(status_code=409, detail={"reason": exc.reason, "input_id": exc.input_id}) from exc
        except SubmissionValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": "submission_validation_failed",
                    "schema_ref": exc.schema_ref,
                    "prompt_ref": exc.prompt_ref,
                    "errors": exc.errors,
                },
            ) from exc
        return result

    @router.post("/api/agent/submit/retro")
    async def submit_retro(request: Request):
        container = request.app.state.container
        req = await _parse_agent_submit_request(request)
        try:
            result = container.agent_gateway.submit_retro(input_id=req.input_id, payload=req.payload)
        except RuntimeInputLeaseError as exc:
            raise HTTPException(status_code=409, detail={"reason": exc.reason, "input_id": exc.input_id}) from exc
        except SubmissionValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": exc.error_kind,
                    "schema_ref": exc.schema_ref,
                    "prompt_ref": exc.prompt_ref,
                    "errors": exc.errors,
                },
            ) from exc
        return result

    @router.get("/api/query/workflows/{trace_id}")
    def query_workflow(trace_id: str, request: Request):
        container = request.app.state.container
        workflow = container.workflow_orchestrator.get_workflow(trace_id)
        if workflow is None:
            raise HTTPException(status_code=404, detail="workflow_not_found")
        return workflow.model_dump(mode="json")

    @router.get("/api/query/strategy/current")
    def query_strategy(request: Request):
        container = request.app.state.container
        latest_strategy = container.state_memory.latest_asset(asset_type="strategy")
        if latest_strategy:
            return latest_strategy["payload"]
        stored_strategy = container.state_memory.latest_strategy()
        return stored_strategy["payload"] if stored_strategy else {}

    @router.get("/api/query/portfolio/current")
    def query_portfolio(request: Request):
        container = request.app.state.container
        latest_portfolio = container.state_memory.latest_asset(asset_type="portfolio_snapshot")
        if latest_portfolio:
            return latest_portfolio["payload"]
        return container.state_memory.latest_portfolio() or {}

    @router.get("/api/query/overview")
    def query_overview(request: Request):
        container = request.app.state.container
        return container.replay_frontend.overview()

    @router.get("/api/query/news/current")
    def query_news(request: Request):
        container = request.app.state.container
        return container.replay_frontend.current_news()

    @router.get("/api/query/executions/recent")
    def query_recent_executions(request: Request):
        container = request.app.state.container
        return container.replay_frontend.recent_executions()

    @router.get("/api/query/market/context")
    def query_market_context(request: Request):
        container = request.app.state.container
        return {
            "market_context": {
                coin: context.model_dump(mode="json")
                for coin, context in container.market_data.collect_market_context().items()
            }
        }

    @router.get("/api/query/agents/{agent_role}/latest")
    def query_agent_state(agent_role: str, request: Request):
        container = request.app.state.container
        return container.replay_frontend.latest_agent_state(agent_role)

    @router.get("/api/query/replay")
    def query_replay(request: Request, trace_id: str | None = None, module: str | None = None):
        container = request.app.state.container
        return container.replay_frontend.query(trace_id=trace_id, module=module).model_dump(mode="json")

    @router.get("/api/query/events")
    def query_events(request: Request, trace_id: str | None = None, module: str | None = None, limit: int = 200):
        container = request.app.state.container
        return container.state_memory.query_events(trace_id=trace_id, module=module, limit=limit)

    @router.get("/api/query/parameters")
    def query_parameters(request: Request):
        container = request.app.state.container
        return container.state_memory.list_parameters()

    @router.websocket("/api/stream/events")
    async def stream_events(websocket: WebSocket):
        await websocket.accept()
        container = websocket.app.state.container
        initialized = False
        last_event_id: str | None = None
        try:
            while True:
                events = container.state_memory.query_events(limit=50)
                current_event_id = events[0]["event_id"] if events else None
                if not initialized or current_event_id != last_event_id:
                    await websocket.send_json(
                        {
                            "overview": container.replay_frontend.overview(),
                            "events": list(reversed(events)),
                        }
                    )
                    initialized = True
                    last_event_id = current_event_id
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return None

    return router
