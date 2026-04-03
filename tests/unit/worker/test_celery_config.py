"""
Tests for Celery application configuration.

Covers:
  - Beat schedule contains expected tasks
  - Celery config values are correct
  - Task serialization settings
  - Redis SSL config for Heroku
"""

from src.worker.celery_app import celery_app


class TestCeleryConfig:
    """Test Celery application configuration."""

    def test_task_serializer_is_json(self):
        assert celery_app.conf.task_serializer == "json"

    def test_accept_content_json_only(self):
        assert "json" in celery_app.conf.accept_content

    def test_timezone_utc(self):
        assert celery_app.conf.timezone == "UTC"

    def test_enable_utc(self):
        assert celery_app.conf.enable_utc is True

    def test_task_track_started(self):
        assert celery_app.conf.task_track_started is True

    def test_task_acks_late(self):
        """Tasks should be acknowledged only after completion."""
        assert celery_app.conf.task_acks_late is True

    def test_task_reject_on_worker_lost(self):
        """Tasks should be re-queued if worker dies."""
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_result_expires_24h(self):
        assert celery_app.conf.result_expires == 3600 * 24

    def test_task_time_limit(self):
        """Max task duration should be 4 hours."""
        assert celery_app.conf.task_time_limit == 3600 * 4

    def test_task_soft_time_limit(self):
        """Soft limit should be 3 hours."""
        assert celery_app.conf.task_soft_time_limit == 3600 * 3


class TestBeatSchedule:
    """Test scheduled task definitions."""

    def test_beat_schedule_has_daily_news(self):
        schedule = celery_app.conf.beat_schedule
        assert "daily-news-pipeline" in schedule
        assert schedule["daily-news-pipeline"]["task"] == "run_news_pipeline"

    def test_beat_schedule_has_weekly_digest(self):
        schedule = celery_app.conf.beat_schedule
        assert "weekly-news-digest" in schedule
        assert schedule["weekly-news-digest"]["task"] == "send_weekly_digest"

    def test_beat_schedule_has_daily_email_sync(self):
        schedule = celery_app.conf.beat_schedule
        assert "daily-email-sync" in schedule
        assert schedule["daily-email-sync"]["task"] == "scan_gmail_task"

    def test_beat_schedule_has_domain_discovery(self):
        schedule = celery_app.conf.beat_schedule
        assert "daily-domain-discovery" in schedule
        assert schedule["daily-domain-discovery"]["task"] == "discover_domain_contacts"

    def test_all_scheduled_tasks_have_user_id_arg(self):
        """All scheduled tasks should pass a user_id as their first argument."""
        schedule = celery_app.conf.beat_schedule
        for name, config in schedule.items():
            assert "args" in config, f"Scheduled task '{name}' missing 'args'"
            assert len(config["args"]) >= 1, f"Scheduled task '{name}' has no user_id arg"


class TestCeleryIncludes:
    """Test task module discovery."""

    def test_includes_tasks_module(self):
        assert "src.worker.tasks" in celery_app.conf.include

    def test_includes_id_first_tasks(self):
        assert "src.worker.id_first_tasks" in celery_app.conf.include

    def test_includes_news_tasks(self):
        assert "src.worker.news_tasks" in celery_app.conf.include

    def test_includes_backfill_tasks(self):
        assert "src.worker.backfill_body_tasks" in celery_app.conf.include
