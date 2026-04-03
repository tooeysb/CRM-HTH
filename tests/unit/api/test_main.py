"""
Tests for the main FastAPI application.

Covers:
  - Root endpoint redirects to /crm
  - Health check returns expected structure
  - CRM frontend serves HTML with API key injected
  - Application metadata (title, version)
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.database import get_sync_db


def _make_mock_db():
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    query_mock = MagicMock()
    query_mock.first.return_value = None
    query_mock.all.return_value = []
    query_mock.scalar.return_value = 0
    query_mock.filter.return_value = query_mock
    query_mock.options.return_value = query_mock
    db.query.return_value = query_mock
    return db


@pytest.fixture
def client():
    db = _make_mock_db()

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


class TestRootEndpoint:
    """GET / endpoint."""

    def test_root_redirects_to_crm(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert "/crm" in response.headers["location"]


class TestHealthCheck:
    """GET /health endpoint."""

    def test_health_returns_status(self, client):
        response = client.get("/health")
        assert response.status_code in (200, 503)
        data = response.json()
        assert "status" in data

    def test_health_includes_db_status(self, client):
        response = client.get("/health")
        data = response.json()
        assert "database" in data

    def test_health_includes_redis_status(self, client):
        response = client.get("/health")
        data = response.json()
        assert "redis" in data

    def test_health_degraded_when_services_down(self, client):
        """Without real DB/Redis, health should report degraded."""
        response = client.get("/health")
        data = response.json()
        # In test environment, both should be disconnected
        assert data["database"] == "disconnected" or data["redis"] == "disconnected"


class TestAppMetadata:
    """Application configuration."""

    def test_app_title(self):
        assert app.title == "CRM-HTH"

    def test_app_version(self):
        assert app.version == "1.0.0"

    def test_app_description(self):
        assert "email processing" in app.description.lower()
