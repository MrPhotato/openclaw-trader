from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request, Response


UPSTREAM = os.getenv("OTRADER_READONLY_UPSTREAM", "http://127.0.0.1:8788").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("OTRADER_READONLY_TIMEOUT_SECONDS", "30"))

app = FastAPI(title="otrader-readonly-proxy")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/query/{path:path}")
async def proxy_query(path: str, request: Request) -> Response:
    upstream_url = f"{UPSTREAM}/api/query/{path}"
    headers = {}
    accept = request.headers.get("accept")
    if accept:
        headers["accept"] = accept
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        upstream = await client.get(upstream_url, params=request.query_params, headers=headers)
    response_headers: dict[str, str] = {}
    content_type = upstream.headers.get("content-type")
    if content_type:
        response_headers["content-type"] = content_type
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def deny(path: str) -> Response:
    raise HTTPException(status_code=404, detail="readonly_proxy_only_exposes_query_endpoints")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("OTRADER_READONLY_HOST", "127.0.0.1"),
        port=int(os.getenv("OTRADER_READONLY_PORT", "18790")),
    )
