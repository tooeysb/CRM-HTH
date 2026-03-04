"""
Unit tests for Gmail rate limiter.

Tests the token bucket rate limiter backed by Redis with atomic Lua script.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.gmail.rate_limiter import (
    GmailRateLimiter,
    GmailRateLimitExceeded,
    rate_limited,
    with_retry,
)


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("src.integrations.gmail.rate_limiter.redis.from_url") as mock:
        redis_mock = MagicMock()
        mock.return_value = redis_mock

        # register_script returns a callable script object
        script_mock = MagicMock()
        redis_mock.register_script.return_value = script_mock

        yield redis_mock


@pytest.fixture
def rate_limiter(mock_redis):
    """Create rate limiter instance with mocked Redis."""
    limiter = GmailRateLimiter(
        redis_url="redis://localhost:6379/0",
        max_tokens=10,
        refill_rate=10.0,
    )
    return limiter


class TestGmailRateLimiter:
    """Test suite for GmailRateLimiter."""

    def test_init(self, mock_redis):
        """Test rate limiter initialization."""
        limiter = GmailRateLimiter(
            redis_url="redis://localhost:6379/0",
            max_tokens=250,
            refill_rate=250.0,
        )

        assert limiter.max_tokens == 250
        assert limiter.refill_rate == 250.0
        assert limiter.redis_url == "redis://localhost:6379/0"

    def test_acquire_success(self, rate_limiter):
        """Test successful token acquisition via Lua script."""
        # Lua script returns 1 = tokens acquired
        rate_limiter._acquire_script.return_value = 1

        result = rate_limiter.acquire(tokens=1)

        assert result is True
        rate_limiter._acquire_script.assert_called_once()
        # Verify correct keys and args were passed
        call_kwargs = rate_limiter._acquire_script.call_args
        assert call_kwargs.kwargs["keys"] == [
            rate_limiter.bucket_key,
            rate_limiter.timestamp_key,
        ]

    def test_acquire_failure(self, rate_limiter):
        """Test token acquisition failure when bucket is empty."""
        # Lua script returns 0 = insufficient tokens
        rate_limiter._acquire_script.return_value = 0

        result = rate_limiter.acquire(tokens=1)

        assert result is False

    def test_acquire_redis_connection_error(self, rate_limiter):
        """Test acquire returns None on Redis connection failure."""
        import redis as redis_lib

        rate_limiter._acquire_script.side_effect = redis_lib.ConnectionError("down")

        result = rate_limiter.acquire(tokens=1)

        assert result is None

    def test_wait_for_token_success(self, rate_limiter):
        """Test wait_for_token successfully acquires token."""
        rate_limiter._acquire_script.return_value = 1

        # Should not raise exception
        rate_limiter.wait_for_token(timeout=1.0)

    def test_wait_for_token_timeout(self, rate_limiter):
        """Test wait_for_token times out when no tokens available."""
        # Lua script always returns 0 (no tokens)
        rate_limiter._acquire_script.return_value = 0

        with pytest.raises(GmailRateLimitExceeded):
            rate_limiter.wait_for_token(timeout=0.2)

    def test_wait_for_token_redis_fallback(self, rate_limiter):
        """Test wait_for_token falls back to local sleep when Redis unavailable."""
        import redis as redis_lib

        rate_limiter._acquire_script.side_effect = redis_lib.ConnectionError("down")

        # Should not raise - falls back to local rate limiting
        rate_limiter.wait_for_token(timeout=1.0)

    def test_get_token_count(self, rate_limiter, mock_redis):
        """Test getting current token count."""
        mock_redis.pipeline.return_value.execute.return_value = ["7.5", str(time.time())]

        count = rate_limiter.get_token_count()

        assert count == 7.5

    def test_reset(self, rate_limiter, mock_redis):
        """Test resetting rate limiter to full capacity."""
        rate_limiter.reset()

        # Verify Redis was updated with max tokens via pipeline
        calls = mock_redis.pipeline.return_value.set.call_args_list
        assert len(calls) >= 2
        # First call should set tokens to max_tokens (int -> str)
        assert calls[0][0][1] == str(rate_limiter.max_tokens)

    def test_close(self, rate_limiter, mock_redis):
        """Test closing Redis connection."""
        rate_limiter.close()

        mock_redis.close.assert_called_once()


class TestRateLimitedDecorator:
    """Test suite for rate_limited decorator."""

    def test_rate_limited_decorator(self, rate_limiter):
        """Test rate_limited decorator enforces rate limiting."""
        rate_limiter._acquire_script.return_value = 1

        call_count = 0

        @rate_limited(rate_limiter)
        def test_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = test_function()

        assert result == "success"
        assert call_count == 1


class TestWithRetryDecorator:
    """Test suite for with_retry decorator."""

    def test_with_retry_success(self):
        """Test with_retry decorator on successful call."""
        call_count = 0

        @with_retry
        def test_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = test_function()

        assert result == "success"
        assert call_count == 1

    def test_with_retry_on_rate_limit_error(self):
        """Test with_retry decorator retries on rate limit error."""
        call_count = 0

        @with_retry
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise GmailRateLimitExceeded("Rate limit exceeded")
            return "success"

        result = test_function()

        assert result == "success"
        assert call_count == 3

    def test_with_retry_on_quota_error(self):
        """Test with_retry decorator retries on quota error."""
        call_count = 0

        @with_retry
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Quota exceeded")
            return "success"

        result = test_function()

        assert result == "success"
        assert call_count == 2

    def test_with_retry_max_attempts(self):
        """Test with_retry decorator stops after max attempts."""
        call_count = 0

        @with_retry
        def test_function():
            nonlocal call_count
            call_count += 1
            raise GmailRateLimitExceeded("Rate limit exceeded")

        with pytest.raises(GmailRateLimitExceeded):
            test_function()

        assert call_count == 5  # Should retry 5 times


class TestDistributedRateLimiting:
    """Test suite for distributed rate limiting scenarios."""

    def test_multiple_instances_share_state(self, mock_redis):
        """Test multiple rate limiter instances share Redis keys."""
        limiter1 = GmailRateLimiter(
            redis_url="redis://localhost:6379/0",
            max_tokens=10,
            refill_rate=10.0,
        )
        limiter2 = GmailRateLimiter(
            redis_url="redis://localhost:6379/0",
            max_tokens=10,
            refill_rate=10.0,
        )

        # Both should use same Redis keys
        assert limiter1.bucket_key == limiter2.bucket_key
        assert limiter1.timestamp_key == limiter2.timestamp_key

    def test_token_consumption_across_instances(self, mock_redis):
        """Test token consumption is tracked across instances."""
        limiter1 = GmailRateLimiter(
            redis_url="redis://localhost:6379/0",
            max_tokens=10,
            refill_rate=10.0,
        )

        # Lua script returns 1 = tokens acquired
        limiter1._acquire_script.return_value = 1

        # Instance 1 acquires token
        result = limiter1.acquire(tokens=1)
        assert result is True

        # Verify Lua script was called (atomic operation)
        limiter1._acquire_script.assert_called_once()
