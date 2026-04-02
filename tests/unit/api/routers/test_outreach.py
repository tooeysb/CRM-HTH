"""
Tests for the outreach API router.

Covers:
  - GET /crm/api/outreach/dashboard returns stats
  - GET /crm/api/outreach/news pagination and filtering
  - GET /crm/api/outreach/suggestions pagination
  - PATCH /crm/api/outreach/suggestions/{id} status validation
  - Sort column injection prevention
  - _title_weight helper function
  - _compute_priority_score helper function
"""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routers.outreach import _compute_priority_score, _title_weight
from src.core.config import settings
from src.core.database import get_sync_db
from src.models.user import User


def _make_mock_db(mock_user=None):
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
    query_mock.distinct.return_value = query_mock

    query_mock.count.return_value = 0
    query_mock.all.return_value = []
    query_mock.scalar.return_value = 0
    query_mock.first.return_value = mock_user

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
    yield client
    app.dependency_overrides.clear()


class TestOutreachDashboard:
    """GET /crm/api/outreach/dashboard endpoint."""

    def test_dashboard_returns_200(self, authed_client):
        response = authed_client.get("/crm/api/outreach/dashboard")
        assert response.status_code == 200

    def test_dashboard_contains_expected_fields(self, authed_client):
        response = authed_client.get("/crm/api/outreach/dashboard")
        data = response.json()
        assert "pending_drafts" in data
        assert "news_today" in data
        assert "total_news" in data
        assert "drafts_sent" in data
        assert "review_drafts" in data

    def test_dashboard_empty_db_returns_zeros(self, authed_client):
        response = authed_client.get("/crm/api/outreach/dashboard")
        data = response.json()
        assert data["pending_drafts"] == 0
        assert data["news_today"] == 0
        assert data["drafts_sent"] == 0


class TestOutreachNews:
    """GET /crm/api/outreach/news endpoint."""

    def test_news_returns_paginated_response(self, authed_client):
        response = authed_client.get("/crm/api/outreach/news")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

    def test_news_invalid_sort_column_returns_400(self, authed_client):
        response = authed_client.get("/crm/api/outreach/news?sort_by=__dict__")
        assert response.status_code == 400

    def test_news_valid_sort_column_succeeds(self, authed_client):
        response = authed_client.get("/crm/api/outreach/news?sort_by=created_at")
        assert response.status_code == 200


class TestOutreachSuggestions:
    """GET /crm/api/outreach/suggestions endpoint."""

    def test_suggestions_returns_paginated_response(self, authed_client):
        response = authed_client.get("/crm/api/outreach/suggestions")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_suggestions_invalid_sort_column_returns_400(self, authed_client):
        response = authed_client.get("/crm/api/outreach/suggestions?sort_by=__dict__")
        assert response.status_code == 400

    def test_suggestions_valid_sort_column_succeeds(self, authed_client):
        response = authed_client.get("/crm/api/outreach/suggestions?sort_by=created_at")
        assert response.status_code == 200


class TestUpdateSuggestion:
    """PATCH /crm/api/outreach/suggestions/{id} endpoint."""

    def test_update_nonexistent_returns_404(self, authed_client):
        import uuid

        response = authed_client.patch(
            f"/crm/api/outreach/suggestions/{uuid.uuid4()}",
            json={"status": "sent"},
        )
        assert response.status_code == 404


class TestTitleWeight:
    """Test _title_weight helper function."""

    def test_ceo_gets_highest_weight(self):
        assert _title_weight("CEO") == 3.0

    def test_president_gets_highest_weight(self):
        assert _title_weight("President") == 3.0

    def test_cfo_gets_c_suite_weight(self):
        assert _title_weight("CFO") == 2.5

    def test_evp_gets_senior_weight(self):
        assert _title_weight("Executive Vice President") == 2.0

    def test_vp_gets_vp_weight(self):
        assert _title_weight("VP of Operations") == 1.5

    def test_director_gets_director_weight(self):
        assert _title_weight("Director of Engineering") == 1.2

    def test_engineer_gets_default_weight(self):
        assert _title_weight("Software Engineer") == 1.0

    def test_none_title_gets_default_weight(self):
        assert _title_weight(None) == 1.0


class TestComputePriorityScore:
    """Test _compute_priority_score helper function."""

    def test_no_emails_returns_zero(self):
        assert _compute_priority_score(0, "CEO", 500) == 0.0

    def test_positive_emails_returns_positive_score(self):
        score = _compute_priority_score(10, "VP of Sales", 200)
        assert score > 0

    def test_ceo_scores_higher_than_engineer(self):
        ceo_score = _compute_priority_score(10, "CEO", 100)
        eng_score = _compute_priority_score(10, "Software Engineer", 100)
        assert ceo_score > eng_score

    def test_more_emails_higher_score(self):
        score_10 = _compute_priority_score(10, "Director", 100)
        score_100 = _compute_priority_score(100, "Director", 100)
        assert score_100 > score_10

    def test_company_bonus_capped(self):
        """Company bonus should be capped at 1.0 regardless of email count."""
        score_small = _compute_priority_score(10, "VP", 50)
        score_huge = _compute_priority_score(10, "VP", 100000)
        # Difference should be at most 1.0
        assert (score_huge - score_small) <= 1.0
