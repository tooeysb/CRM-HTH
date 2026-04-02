"""
Tests for Settings configuration and environment detection.

Covers:
  - is_production / is_development properties
  - Vault path validation (absolute path required)
  - get_gmail_accounts returns all three accounts
  - Default values for optional fields
"""

from unittest.mock import patch

import pytest

from src.core.config import Settings


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance with all required fields populated."""
    defaults = {
        "SECRET_KEY": "test-secret-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_KEY": "test-supabase-key",
        "DATABASE_URL": "postgresql://localhost/test",
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/auth/callback",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestEnvironmentDetection:
    """Test is_production and is_development properties."""

    def test_default_is_development(self):
        s = _make_settings()
        assert s.is_development is True
        assert s.is_production is False

    def test_production_mode(self):
        s = _make_settings(APP_ENV="production")
        assert s.is_production is True
        assert s.is_development is False

    def test_staging_mode(self):
        s = _make_settings(APP_ENV="staging")
        assert s.is_production is False
        assert s.is_development is False


class TestVaultPathValidation:
    """Test obsidian_vault_path must be absolute."""

    def test_absolute_path_accepted(self):
        s = _make_settings(OBSIDIAN_VAULT_PATH="/tmp/vault")
        assert s.obsidian_vault_path == "/tmp/vault"

    def test_relative_path_rejected(self):
        with pytest.raises(Exception):
            _make_settings(OBSIDIAN_VAULT_PATH="relative/path")


class TestGmailAccounts:
    """Test get_gmail_accounts returns configured accounts."""

    def test_default_gmail_accounts(self):
        s = _make_settings()
        accounts = s.get_gmail_accounts()
        assert len(accounts) == 3
        labels = [a["label"] for a in accounts]
        assert "procore-main" in labels
        assert "procore-private" in labels
        assert "personal" in labels

    def test_custom_gmail_accounts(self):
        s = _make_settings(
            GMAIL_ACCOUNT_1_LABEL="work",
            GMAIL_ACCOUNT_1_EMAIL="work@test.com",
        )
        accounts = s.get_gmail_accounts()
        assert accounts[0] == {"label": "work", "email": "work@test.com"}


class TestDefaultValues:
    """Test default values for optional configuration fields."""

    def test_redis_default(self):
        s = _make_settings()
        assert s.redis_url == "redis://localhost:6379/0"

    def test_claude_model_default(self):
        s = _make_settings()
        assert "haiku" in s.claude_model

    def test_draft_model_default(self):
        s = _make_settings()
        assert "sonnet" in s.draft_model

    def test_sentry_dsn_default_none(self):
        s = _make_settings()
        assert s.sentry_dsn is None

    def test_sso_jwt_secret_default_empty(self):
        s = _make_settings()
        assert s.sso_jwt_secret == ""

    def test_news_scrape_enabled_default(self):
        s = _make_settings()
        assert s.news_scrape_enabled is True

    def test_digest_enabled_default(self):
        s = _make_settings()
        assert s.digest_enabled is False

    def test_app_url_default(self):
        s = _make_settings()
        assert s.app_url == "http://localhost:8000"

    def test_gmail_rate_limit_defaults(self):
        s = _make_settings()
        assert s.gmail_rate_limit_qps == 40
        assert s.gmail_rate_limit_burst == 100
        assert s.gmail_batch_size == 500
