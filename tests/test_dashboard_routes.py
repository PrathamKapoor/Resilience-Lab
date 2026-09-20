"""Dashboard static-route contracts."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resiliencelab.api.app import LocalRuntime, create_app

api_app = importlib.import_module("resiliencelab.api.app")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(LocalRuntime()))


@pytest.fixture()
def built_dashboard_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a minimal Vite-shaped build without relying on generated files."""
    dist = tmp_path / "dashboard" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>Resilience dashboard</main>", encoding="utf-8")
    (assets / "index-abc123.js").write_text("console.log('dashboard')", encoding="utf-8")
    monkeypatch.setattr(api_app, "DASHBOARD_DIST", dist, raising=False)
    return TestClient(create_app(LocalRuntime()))


def test_dashboard_does_not_shadow_api(client: TestClient) -> None:
    """Removing API router precedence would break the health control-plane endpoint."""
    assert client.get("/api/v1/health").status_code == 200


def test_dashboard_serves_vite_entry_when_built(built_dashboard_client: TestClient) -> None:
    """Removing the explicit dashboard route would leave the built entry unreachable."""
    response = built_dashboard_client.get("/dashboard")

    assert response.status_code == 200
    assert response.text == "<main>Resilience dashboard</main>"
    assert response.headers["cache-control"] == "no-cache"


def test_dashboard_nested_client_path_serves_vite_entry_when_built(
    built_dashboard_client: TestClient,
) -> None:
    """Replacing the SPA fallback with a file-only route would break deep links."""
    response = built_dashboard_client.get("/dashboard/experiments/demo")

    assert response.status_code == 200
    assert response.text == "<main>Resilience dashboard</main>"
    assert response.headers["cache-control"] == "no-cache"


def test_dashboard_hashed_asset_is_immutable_cacheable(built_dashboard_client: TestClient) -> None:
    """Dropping asset caching would force clients to re-download versioned Vite bundles."""
    response = built_dashboard_client.get("/dashboard/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log('dashboard')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_dashboard_is_explicit_when_build_is_missing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returning a generic 404 would hide the required frontend build action."""
    monkeypatch.setattr(api_app, "DASHBOARD_DIST", tmp_path / "missing", raising=False)

    response = client.get("/dashboard")

    assert response.status_code == 503
    assert "npm --prefix dashboard run build" in response.text
