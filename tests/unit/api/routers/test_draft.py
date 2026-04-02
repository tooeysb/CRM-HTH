"""
Tests for the draft API router.

Covers:
  - POST /draft/compose requires auth
  - POST /draft/compose with valid request calls service
  - POST /draft/compose with invalid data returns 400/422
  - Draft service failure returns 500
"""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User


def _make_mock_db(mock_user=None):
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    query_mock = MagicMock()
    query_mock.options.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = mock_user
    query_mock.all.return_value = []
    query_mock.scalar.return_value = 0
    query_mock.count.return_value = 0
    db.query.return_value = query_mock
    return db


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = UUID("d4475ca3-0ddc-4ea0-ac89-95ae7fed1e31")
    user.email = "test@example.com"
    user.name = "Test User"
    return user


@pytest.fixture
def authed_client(mock_user):
    db = _make_mock_db(mock_user=mock_user)

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, headers={"X-API-Key": settings.secret_key})
    yield client, db
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_client():
    db = _make_mock_db()

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


class TestDraftCompose:
    """POST /draft/compose endpoint."""

    def test_compose_requires_auth(self, unauthed_client):
        response = unauthed_client.post(
            "/draft/compose",
            json={
                "recipient_email": "bob@example.com",
                "context": "Following up on proposal",
            },
        )
        assert response.status_code == 401

    @patch("src.api.routers.draft.EmailDraftService")
    def test_compose_success(self, mock_service_cls, authed_client):
        client, db = authed_client

        mock_result = MagicMock()
        mock_result.subject = "Re: Proposal"
        mock_result.body = "Hi Bob, following up..."
        mock_result.similar_emails_used = 3
        mock_result.voice_profile_used = "default"
        mock_result.model = "claude-sonnet-4-5-20250929"

        mock_service = MagicMock()
        mock_service.draft_email.return_value = mock_result
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/draft/compose",
            json={
                "recipient_email": "bob@example.com",
                "context": "Following up on proposal",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == "Re: Proposal"
        assert data["similar_emails_used"] == 3
        assert data["model"] == "claude-sonnet-4-5-20250929"

    @patch("src.api.routers.draft.EmailDraftService")
    def test_compose_with_optional_fields(self, mock_service_cls, authed_client):
        client, db = authed_client

        mock_result = MagicMock()
        mock_result.subject = "Re: Quarterly Review"
        mock_result.body = "Dear Team..."
        mock_result.similar_emails_used = 5
        mock_result.voice_profile_used = "formal"
        mock_result.model = "claude-sonnet-4-5-20250929"

        mock_service = MagicMock()
        mock_service.draft_email.return_value = mock_result
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/draft/compose",
            json={
                "recipient_email": "team@acme.com",
                "context": "Quarterly review follow-up",
                "tone": "formal",
                "reply_to_subject": "Quarterly Review Notes",
            },
        )
        assert response.status_code == 200

        # Verify service was called with tone and reply_to_subject
        call_kwargs = mock_service.draft_email.call_args[1]
        assert call_kwargs["tone"] == "formal"
        assert call_kwargs["reply_to_subject"] == "Quarterly Review Notes"

    def test_compose_missing_required_fields(self, authed_client):
        client, db = authed_client
        response = client.post("/draft/compose", json={})
        assert response.status_code == 422

    @patch("src.api.routers.draft.EmailDraftService")
    def test_compose_value_error_returns_400(self, mock_service_cls, authed_client):
        client, db = authed_client

        mock_service = MagicMock()
        mock_service.draft_email.side_effect = ValueError("No voice profile found")
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/draft/compose",
            json={
                "recipient_email": "bob@example.com",
                "context": "Test",
            },
        )
        assert response.status_code == 400
        assert "voice profile" in response.json()["detail"]

    @patch("src.api.routers.draft.EmailDraftService")
    def test_compose_generic_error_returns_500(self, mock_service_cls, authed_client):
        client, db = authed_client

        mock_service = MagicMock()
        mock_service.draft_email.side_effect = RuntimeError("Unexpected error")
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/draft/compose",
            json={
                "recipient_email": "bob@example.com",
                "context": "Test",
            },
        )
        assert response.status_code == 500
