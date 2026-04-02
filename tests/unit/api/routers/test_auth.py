"""
Tests for the auth API router (Gmail OAuth2 flow).

Covers:
  - GET /auth/login/{label} validates account labels
  - GET /auth/login/{label} rejects invalid user IDs
  - GET /auth/status requires valid user
  - GET /auth/callback handles invalid state tokens
  - POST /auth/revoke/{id} validates account ownership
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User


def _make_mock_db(user=None, accounts=None):
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.options.return_value = query_mock
    query_mock.first.return_value = user
    query_mock.all.return_value = accounts or []
    query_mock.scalar.return_value = 0
    query_mock.count.return_value = 0
    db.query.return_value = query_mock
    return db


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = uuid.UUID("d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31")
    user.email = "test@example.com"
    user.name = "Test User"
    return user


@pytest.fixture
def client_with_user(mock_user):
    db = _make_mock_db(user=mock_user)

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, headers={"X-API-Key": settings.secret_key})
    yield client, db
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_user():
    db = _make_mock_db(user=None)

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, headers={"X-API-Key": settings.secret_key})
    yield client
    app.dependency_overrides.clear()


class TestInitiateOAuth:
    """GET /auth/login/{account_label} endpoint."""

    def test_invalid_label_returns_400(self, client_with_user):
        client, db = client_with_user
        user_id = "d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31"
        response = client.get(f"/auth/login/invalid-label?user_id={user_id}")
        assert response.status_code == 400
        assert "Invalid account label" in response.json()["detail"]

    def test_user_not_found_returns_404(self, client_no_user):
        user_id = str(uuid.uuid4())
        response = client_no_user.get(f"/auth/login/procore-main?user_id={user_id}")
        assert response.status_code == 404

    def test_valid_labels_accepted(self, client_with_user):
        """All three valid account labels should be accepted (if user exists)."""
        client, db = client_with_user
        user_id = "d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31"
        for label in ["procore-main", "procore-private", "personal"]:
            response = client.get(f"/auth/login/{label}?user_id={user_id}")
            # Should get 200 or 500 (if Google OAuth fails), not 400
            assert response.status_code != 400


class TestAuthStatus:
    """GET /auth/status endpoint."""

    def test_status_user_not_found_returns_404(self, client_no_user):
        response = client_no_user.get(f"/auth/status?user_id={uuid.uuid4()}")
        assert response.status_code == 404

    def test_status_valid_user_returns_accounts(self, client_with_user):
        client, db = client_with_user
        user_id = "d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31"
        response = client.get(f"/auth/status?user_id={user_id}")
        assert response.status_code == 200
        data = response.json()
        assert "authenticated_accounts" in data
        assert data["user_id"] == user_id


class TestOAuthCallback:
    """GET /auth/callback endpoint."""

    def test_callback_invalid_state_returns_400(self, client_with_user):
        """Invalid state token format returns 400."""
        client, db = client_with_user
        response = client.get("/auth/callback?code=test-code&state=invalid")
        assert response.status_code == 400


class TestRevokeAccount:
    """POST /auth/revoke/{account_id} endpoint."""

    def test_revoke_nonexistent_returns_404(self, client_with_user):
        client, db = client_with_user
        user_id = "d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31"
        # Override .first() to return None so the GmailAccount lookup fails with 404
        db.query.return_value.filter.return_value.first.return_value = None
        response = client.post(
            f"/auth/revoke/{uuid.uuid4()}?user_id={user_id}"
        )
        assert response.status_code == 404
