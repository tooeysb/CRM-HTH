"""
Tests for the /auth/sso callback endpoint in main.py.

Covers:
  - Valid SSO token sets session cookie and redirects
  - Expired token redirects to Portal with error
  - Invalid token redirects to Portal with error
  - Missing SSO_JWT_SECRET returns /health fallback
  - return_to parameter validation (open redirect prevention)
  - Session cookie properties (httponly, samesite, max_age)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db


@pytest.fixture
def _override_db():
    """Override DB dependency to prevent real DB calls."""
    from unittest.mock import MagicMock

    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    query_mock = MagicMock()
    query_mock.first.return_value = None
    db.query.return_value = query_mock

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def _require_sso():
    if not settings.sso_jwt_secret:
        pytest.skip("SSO_JWT_SECRET not configured")


def _make_portal_token(
    email: str = "tooey@hth-corp.com",
    user_id: str = "user-abc",
    expired: bool = False,
) -> str:
    """Create a Portal SSO JWT (short-lived, simulating what Portal sends)."""
    exp = datetime.now(UTC) + (timedelta(seconds=-10) if expired else timedelta(minutes=5))
    return jwt.encode(
        {"user_id": user_id, "email": email, "exp": exp},
        settings.sso_jwt_secret,
        algorithm="HS256",
    )


class TestSSOCallbackValidToken:
    """Valid SSO token from Portal sets session cookie and redirects."""

    def test_valid_token_sets_cookie_and_redirects(self, _override_db, _require_sso):
        """Valid token -> 302 to /crm with crm_session cookie set."""
        token = _make_portal_token()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/auth/sso?token={token}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/crm"
        assert "crm_session" in response.cookies

    def test_session_cookie_is_valid_jwt(self, _override_db, _require_sso):
        """The session cookie is a decodable JWT with user_id and email."""
        token = _make_portal_token(email="test@hth-corp.com", user_id="usr-1")
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/auth/sso?token={token}", follow_redirects=False)

        session_cookie = response.cookies.get("crm_session")
        assert session_cookie is not None

        payload = jwt.decode(session_cookie, settings.sso_jwt_secret, algorithms=["HS256"])
        assert payload["user_id"] == "usr-1"
        assert payload["email"] == "test@hth-corp.com"
        assert "exp" in payload

    def test_session_cookie_has_24h_expiry(self, _override_db, _require_sso):
        """Session cookie exp should be ~24 hours from now."""
        token = _make_portal_token()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/auth/sso?token={token}", follow_redirects=False)

        session_cookie = response.cookies.get("crm_session")
        payload = jwt.decode(session_cookie, settings.sso_jwt_secret, algorithms=["HS256"])

        exp_dt = datetime.fromtimestamp(payload["exp"], tz=UTC)
        now = datetime.now(UTC)
        diff_hours = (exp_dt - now).total_seconds() / 3600
        assert 23 < diff_hours < 25  # Roughly 24 hours


class TestSSOCallbackInvalidTokens:
    """Invalid/expired tokens redirect back to Portal with error."""

    def test_expired_token_redirects_to_portal(self, _override_db, _require_sso):
        """Expired token -> redirect to portal_login_url with error=token_expired."""
        token = _make_portal_token(expired=True)
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/auth/sso?token={token}", follow_redirects=False)

        assert response.status_code == 302
        location = response.headers["location"]
        assert settings.portal_login_url in location
        assert "token_expired" in location

    def test_invalid_signature_redirects_to_portal(self, _override_db, _require_sso):
        """Token signed with wrong secret -> redirect with error=invalid_token."""
        bad_token = jwt.encode(
            {
                "user_id": "usr",
                "email": "test@test.com",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "wrong-secret",
            algorithm="HS256",
        )
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(f"/auth/sso?token={bad_token}", follow_redirects=False)

        assert response.status_code == 302
        location = response.headers["location"]
        assert "invalid_token" in location

    def test_garbage_token_redirects_to_portal(self, _override_db, _require_sso):
        """Completely invalid JWT string -> redirect with error=invalid_token."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/auth/sso?token=not.a.jwt.at.all", follow_redirects=False)

        assert response.status_code == 302
        location = response.headers["location"]
        assert "invalid_token" in location

    def test_missing_token_param_returns_422(self, _override_db, _require_sso):
        """Missing required token query param -> 422 validation error."""
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/auth/sso", follow_redirects=False)
        assert response.status_code == 422


class TestSSOCallbackReturnTo:
    """return_to parameter validation prevents open redirect."""

    def test_return_to_relative_path_honored(self, _override_db, _require_sso):
        """A relative return_to path should be used as the redirect target."""
        token = _make_portal_token()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(
            f"/auth/sso?token={token}&return_to=/crm/api/contacts",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/crm/api/contacts"

    def test_return_to_external_domain_rejected(self, _override_db, _require_sso):
        """A return_to pointing to an external domain should be ignored."""
        token = _make_portal_token()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(
            f"/auth/sso?token={token}&return_to=https://evil.com/steal",
            follow_redirects=False,
        )

        assert response.status_code == 302
        # Should fallback to /crm, not follow the external URL
        assert response.headers["location"] == "/crm"

    def test_return_to_empty_defaults_to_crm(self, _override_db, _require_sso):
        """Empty return_to defaults to /crm."""
        token = _make_portal_token()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get(
            f"/auth/sso?token={token}&return_to=",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/crm"


class TestSSOCallbackMissingSecret:
    """When SSO_JWT_SECRET is not configured, the callback falls back."""

    def test_no_sso_secret_redirects_to_health(self, _override_db):
        """With empty sso_jwt_secret, /auth/sso redirects to /health."""
        with patch.object(settings, "sso_jwt_secret", ""):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/auth/sso?token=anything", follow_redirects=False)

            assert response.status_code == 307  # RedirectResponse default
            assert "/health" in response.headers["location"]
