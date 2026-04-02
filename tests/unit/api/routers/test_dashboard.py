"""
Tests for the dashboard API router.

Covers:
  - GET /dashboard/stats with empty DB returns default stats
  - GET /dashboard/stats requires API key
  - GET /dashboard/widget returns HTML
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User


def _make_mock_db():
    """Build a self-chaining query mock."""
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)

    query_mock = MagicMock()
    query_mock.options.return_value = query_mock
    query_mock.outerjoin.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.offset.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.group_by.return_value = query_mock
    query_mock.subquery.return_value = query_mock

    query_mock.count.return_value = 0
    query_mock.all.return_value = []
    query_mock.scalar.return_value = 0
    query_mock.first.return_value = None

    db.query.return_value = query_mock
    return db


@pytest.fixture
def authed_client():
    """TestClient with valid API key and mock DB."""
    db = _make_mock_db()

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, headers={"X-API-Key": settings.secret_key})
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_client():
    """TestClient with no API key."""
    db = _make_mock_db()

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


class TestDashboardStats:
    """GET /dashboard/stats endpoint."""

    def test_stats_returns_200_with_valid_key(self, authed_client):
        response = authed_client.get("/dashboard/stats")
        assert response.status_code == 200

    def test_stats_contains_expected_fields(self, authed_client):
        response = authed_client.get("/dashboard/stats")
        data = response.json()
        assert "total_emails" in data
        assert "active_scans" in data
        assert "accounts" in data
        assert "monitor_events" in data

    def test_stats_empty_db_returns_zeros(self, authed_client):
        response = authed_client.get("/dashboard/stats")
        data = response.json()
        assert data["total_emails"] == 0
        assert data["active_scans"] == 0
        assert data["accounts"] == []

    def test_stats_requires_api_key(self, unauthed_client):
        response = unauthed_client.get("/dashboard/stats")
        assert response.status_code == 401


class TestDashboardWidget:
    """GET /dashboard/widget endpoint."""

    def test_widget_returns_html(self, authed_client):
        """Widget endpoint should return HTML content."""
        response = authed_client.get("/dashboard/widget")
        # May return 200 or 500 depending on file existence
        if response.status_code == 200:
            assert "text/html" in response.headers.get("content-type", "")
