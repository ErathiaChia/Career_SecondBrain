import os

os.environ.setdefault("ERA_VAULT_DB_PASSWORD", "test")

from fastapi.testclient import TestClient  # noqa: E402

from era_mcp import server  # noqa: E402


def test_public_surface_is_three_tools():
    spec = server.app.openapi()
    assert set(spec["paths"]) == {"/ask", "/search", "/pipeline/status"}
    ops = {op["operationId"] for p in spec["paths"].values() for op in p.values()}
    assert ops == {"ask_vault", "search_vault", "pipeline_status"}
    ask = spec["components"]["schemas"]["AskRequest"]["properties"]
    assert ask["mode"]["default"] == "auto" and "project" in ask


def _paths(app):
    """Route paths including routers that newer FastAPI keeps nested."""
    out, stack = set(), list(app.routes)
    while stack:
        r = stack.pop()
        if hasattr(r, "methods") and getattr(r, "path", None):
            out.add(r.path)
        stack.extend(getattr(r, "routes", None) or [])
    return out


def test_internal_routes_exist_but_hidden():
    paths = _paths(server.app)
    assert "/projects" in paths and "/facts/search" in paths and "/internal/tools" in paths
    assert "/health" in paths


def test_bearer_token_gate(monkeypatch):
    monkeypatch.setenv("API_BEARER_TOKEN", "s3cret")
    client = TestClient(server.app)
    assert client.get("/health").status_code == 200                       # open
    assert client.get("/openapi.json").status_code == 200                 # open (Open WebUI discovery)
    r = client.get("/internal/tools")
    assert r.status_code == 401
    r = client.get("/internal/tools", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["count"] >= 20
    monkeypatch.setenv("API_BEARER_TOKEN", "")
    assert client.get("/internal/tools").status_code == 200
