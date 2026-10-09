"""Bearer-token gate for every endpoint (OpenAPI and /mcp alike). When
API_BEARER_TOKEN is unset the server is open (LAN/Tailscale only) and says so
at startup."""
from __future__ import annotations

import hmac
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from era_mcp import config

_OPEN_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc", "/graph")


async def bearer_middleware(request: Request, call_next):
    token = config.api_bearer_token()
    if not token or request.url.path.startswith(_OPEN_PREFIXES) or request.method == "OPTIONS":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if not supplied or not hmac.compare_digest(supplied, token):
        return JSONResponse({"error": "unauthorized", "hint": "send Authorization: Bearer <API_BEARER_TOKEN>"},
                            status_code=401)
    return await call_next(request)


def warn_if_open() -> None:
    if not config.api_bearer_token():
        logging.getLogger(__name__).warning(
            "API_BEARER_TOKEN is unset: every endpoint (including /mcp) is open to anyone who can reach this port.")
