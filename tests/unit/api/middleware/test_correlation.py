"""
Tests for CorrelationIdMiddleware internals.

Covers:
  - request_id_var context variable defaults to '-'
  - Context variable is reset after request
"""

from src.api.middleware.correlation import request_id_var


class TestRequestIdVar:
    """Test the request_id context variable."""

    def test_default_value_is_dash(self):
        """Default request_id should be '-' when no middleware is active."""
        assert request_id_var.get() == "-"

    def test_set_and_reset(self):
        """Setting and resetting the context variable should work."""
        token = request_id_var.set("test-123")
        assert request_id_var.get() == "test-123"
        request_id_var.reset(token)
        assert request_id_var.get() == "-"
