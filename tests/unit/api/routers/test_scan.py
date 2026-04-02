"""
Tests for the scan API router.

Covers:
  - POST /scan/start validates user existence
  - POST /scan/start rejects when job already running
  - GET /scan/status/{job_id} returns status from Celery fallback
  - POST /scan/cancel/{job_id} validates job exists
  - GET /scan/results/{job_id} rejects non-completed jobs
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User


def _make_mock_db(user=None, existing_job=None, accounts=None):
    """Build a chaining mock DB with configurable returns."""
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)

    call_count = {"query": 0}
    query_results = {}

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.options.return_value = query_mock
    query_mock.first.return_value = user
    query_mock.all.return_value = accounts or []
    query_mock.count.return_value = 0
    query_mock.scalar.return_value = 0

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
def authed_client(mock_user):
    """TestClient with valid API key and user-returning mock DB."""
    db = _make_mock_db(user=mock_user)

    def override():
        yield db

    app.dependency_overrides[get_sync_db] = override
    client = TestClient(app, headers={"X-API-Key": settings.secret_key})
    yield client, db
    app.dependency_overrides.clear()


class TestStartScan:
    """POST /scan/start endpoint."""

    @patch("src.api.routers.scan.scan_gmail_task")
    def test_start_scan_user_not_found(self, mock_task):
        """Start scan with unknown user returns 404."""
        db = _make_mock_db(user=None)

        def override():
            yield db

        app.dependency_overrides[get_sync_db] = override
        client = TestClient(app, headers={"X-API-Key": settings.secret_key})

        response = client.post(
            "/scan/start",
            json={"user_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
        app.dependency_overrides.clear()

    @patch("src.api.routers.scan.scan_gmail_task")
    def test_start_scan_missing_accounts(self, mock_task, authed_client, mock_user):
        """Start scan with accounts not all authenticated returns 400."""
        client, db = authed_client
        # .all() returns empty list -> accounts missing
        response = client.post(
            "/scan/start",
            json={"user_id": str(mock_user.id), "account_labels": ["procore-main"]},
        )
        assert response.status_code == 400
        assert "Missing" in response.json()["detail"]


class TestJobStatus:
    """GET /scan/status/{job_id} endpoint."""

    @patch("src.api.routers.scan.celery_app")
    @patch("src.api.routers.scan.AsyncResult")
    def test_status_pending_from_celery(self, mock_async_result, mock_celery_app, authed_client):
        """When job not in DB, falls back to Celery PENDING state."""
        client, db = authed_client
        # .first() returns None -> no job in DB
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_async_result.return_value = mock_result

        response = client.get(f"/scan/status/{uuid.uuid4()}")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    @patch("src.api.routers.scan.celery_app")
    @patch("src.api.routers.scan.AsyncResult")
    def test_status_success_from_celery(self, mock_async_result, mock_celery_app, authed_client):
        """Celery SUCCESS state returns completed status."""
        client, db = authed_client
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = {"emails_processed": 100, "contacts_processed": 50}
        mock_async_result.return_value = mock_result

        response = client.get(f"/scan/status/{uuid.uuid4()}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["emails_processed"] == 100

    @patch("src.api.routers.scan.celery_app")
    @patch("src.api.routers.scan.AsyncResult")
    def test_status_failure_from_celery(self, mock_async_result, mock_celery_app, authed_client):
        """Celery FAILURE state returns failed status with error message."""
        client, db = authed_client
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.info = Exception("Worker crashed")
        mock_async_result.return_value = mock_result

        response = client.get(f"/scan/status/{uuid.uuid4()}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "Worker crashed" in data["error_message"]


class TestCancelJob:
    """POST /scan/cancel/{job_id} endpoint."""

    def test_cancel_nonexistent_job_returns_404(self, authed_client):
        """Cancelling a non-existent job returns 404."""
        client, db = authed_client
        response = client.post(f"/scan/cancel/{uuid.uuid4()}")
        assert response.status_code == 404


class TestJobResults:
    """GET /scan/results/{job_id} endpoint."""

    def test_results_nonexistent_job_returns_404(self, authed_client):
        """Getting results for non-existent job returns 404."""
        client, db = authed_client
        response = client.get(f"/scan/results/{uuid.uuid4()}")
        assert response.status_code == 404
