"""
Tests for SSO authentication middleware.

Covers:
  - Redirect to Portal when session cookie is missing
  - Pass-through when valid SSO cookie is present
  - Pass-through when valid API key is present
  - Public routes bypass SSO checks
  - Expired cookie triggers redirect
  - Invalid cookie triggers redirect
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db


@pytest.fixture
def _override_db():
    """Override DB dependency to avoid real DB calls."""
    from unittest.mock import MagicMock

    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    query_mock = MagicMock()
    query_mock.first.return_value = None
    query_mock.options.return_value = query_mock
    query_mock.filter.return_value = query_mock
    db.query.return_value = query_mock

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    yield db
    app.dependency_overrides.clear()


def _make_session_cookie(
    email: str = "test@example.com",
    user_id: str = "test-user-123",
    expired: bool = False,
    secret: str | None = None,
) -> str:
    """Create a crm_session JWT cookie."""
    exp = datetime.now(UTC) + (timedelta(hours=-1) if expired else timedelta(hours=24))
    payload = {"user_id": user_id, "email": email, "exp": exp}
    return jwt.encode(payload, secret or settings.sso_jwt_secret, algorithm="HS256")


@pytest.fixture
def _ensure_sso_enabled():
    """Ensure SSO_JWT_SECRET is set for these tests."""
    if not settings.sso_jwt_secret:
        pytest.skip("SSO_JWT_SECRET not configured; SSO middleware tests require it")


class TestSSOPublicRoutes:
    """Public routes must be accessible without any auth."""

    def test_health_no_cookie_no_key(self, _override_db):
        """GET /health is public and should not redirect."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")
        assert response.status_code in (200, 503)

    def test_auth_sso_callback_is_public(self, _override_db):
        """GET /auth/sso is a public route (it IS the SSO callback)."""
        client = TestClient(app, raise_server_exceptions=True)
        # Will fail validation (no token param) but should not redirect
        response = client.get("/auth/sso", follow_redirects=False)
        assert response.status_code == 422  # Missing required query param

    def test_docs_is_public(self, _override_db):
        """GET /docs is a public route."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/docs", follow_redirects=False)
        assert response.status_code == 200

    def test_openapi_json_is_public(self, _override_db):
        """GET /openapi.json is a public route."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/openapi.json", follow_redirects=False)
        assert response.status_code == 200


class TestSSOApiKeyBypass:
    """Requests with a valid API key should bypass SSO checks."""

    def test_api_key_bypasses_sso(self, _override_db, _ensure_sso_enabled):
        """Valid X-API-Key header bypasses SSO cookie requirement."""
        client = TestClient(app, headers={"X-API-Key": settings.secret_key})
        response = client.get("/dashboard/stats", follow_redirects=False)
        # Should reach the endpoint (200), not redirect (302)
        assert response.status_code == 200


class TestSSOCookieValidation:
    """SSO middleware validates the crm_session cookie."""

    def test_valid_cookie_passes_through(self, _override_db, _ensure_sso_enabled):
        """A valid, non-expired crm_session cookie passes SSO check."""
        token = _make_session_cookie()
        client = TestClient(app, cookies={"crm_session": token})
        # Access a protected page - should not redirect
        response = client.get("/crm/api/contacts", follow_redirects=False)
        # Will get 401 from API key check (no X-API-Key) but not a 302 redirect
        assert response.status_code != 302

    def test_missing_cookie_redirects(self, _override_db, _ensure_sso_enabled):
        """No cookie and no API key should redirect to Portal SSO."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/crm/api/contacts", follow_redirects=False)
        assert response.status_code == 302
        assert settings.portal_sso_silent_url in response.headers.get("location", "")

    def test_expired_cookie_redirects(self, _override_db, _ensure_sso_enabled):
        """An expired crm_session cookie should redirect to Portal SSO."""
        token = _make_session_cookie(expired=True)
        client = TestClient(app, cookies={"crm_session": token})
        response = client.get("/crm/api/contacts", follow_redirects=False)
        assert response.status_code == 302

    def test_invalid_cookie_redirects(self, _override_db, _ensure_sso_enabled):
        """A crm_session cookie signed with the wrong secret should redirect."""
        token = _make_session_cookie(secret="wrong-secret-key")
        client = TestClient(app, cookies={"crm_session": token})
        response = client.get("/crm/api/contacts", follow_redirects=False)
        assert response.status_code == 302

    def test_redirect_includes_return_to(self, _override_db, _ensure_sso_enabled):
        """Redirect URL should include return_to with the original URL."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/crm/api/contacts?page=2", follow_redirects=False)
        location = response.headers.get("location", "")
        assert "return_to=" in location
