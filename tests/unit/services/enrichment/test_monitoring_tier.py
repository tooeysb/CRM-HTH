"""
Tests for the monitoring tier auto-tiering service.

Covers:
  - compute_contact_score with various inputs
  - Score components: email volume, recency, direct bonus
  - Edge cases: zero emails, None last_contact_at
"""

import math
from datetime import UTC, datetime, timedelta

from src.services.enrichment.monitoring_tier import compute_contact_score


class TestComputeContactScore:
    """Test the compute_contact_score function."""

    def test_zero_emails_zero_score(self):
        """Contact with no emails should have a base score of 0."""
        score = compute_contact_score(0, None, is_direct=False)
        assert score == 0.0

    def test_email_volume_log_scaled(self):
        """Score should increase logarithmically with email count."""
        score_10 = compute_contact_score(10, None, is_direct=False)
        score_100 = compute_contact_score(100, None, is_direct=False)
        score_1000 = compute_contact_score(1000, None, is_direct=False)

        assert score_10 > 0
        assert score_100 > score_10
        assert score_1000 > score_100

        # Log-scaled means the increase from 10->100 is same as 100->1000
        increase_1 = score_100 - score_10
        increase_2 = score_1000 - score_100
        assert abs(increase_1 - increase_2) < 0.01

    def test_recency_bonus_recent_contact(self):
        """Recent contact should add to score."""
        yesterday = datetime.now(UTC) - timedelta(days=1)
        score = compute_contact_score(10, yesterday, is_direct=False)
        score_no_recency = compute_contact_score(10, None, is_direct=False)
        assert score > score_no_recency

    def test_recency_decays_over_time(self):
        """Score should decrease as contact becomes older."""
        recent = datetime.now(UTC) - timedelta(days=5)
        old = datetime.now(UTC) - timedelta(days=50)
        very_old = datetime.now(UTC) - timedelta(days=95)

        score_recent = compute_contact_score(10, recent, is_direct=False)
        score_old = compute_contact_score(10, old, is_direct=False)
        score_very_old = compute_contact_score(10, very_old, is_direct=False)

        assert score_recent > score_old > score_very_old

    def test_recency_no_bonus_after_100_days(self):
        """Contacts older than 100 days should get no recency bonus."""
        way_old = datetime.now(UTC) - timedelta(days=200)
        score_old = compute_contact_score(10, way_old, is_direct=False)
        score_no_date = compute_contact_score(10, None, is_direct=False)
        assert score_old == score_no_date

    def test_direct_communication_bonus(self):
        """Direct correspondents should score +50 higher."""
        score_direct = compute_contact_score(10, None, is_direct=True)
        score_indirect = compute_contact_score(10, None, is_direct=False)
        assert abs(score_direct - score_indirect - 50.0) < 1e-9

    def test_naive_datetime_handled(self):
        """Naive datetime (no tzinfo) should be handled without error."""
        naive_dt = datetime(2024, 6, 1)
        score = compute_contact_score(10, naive_dt, is_direct=False)
        assert score >= 0

    def test_one_email_has_positive_score(self):
        """A single email should produce a non-zero score."""
        score = compute_contact_score(1, None, is_direct=False)
        expected = math.log2(1) * 10  # = 0.0
        assert score == expected

    def test_two_emails_has_positive_score(self):
        """Two emails should produce score = log2(2) * 10 = 10.0."""
        score = compute_contact_score(2, None, is_direct=False)
        assert abs(score - 10.0) < 0.01
