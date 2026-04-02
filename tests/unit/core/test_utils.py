"""
Tests for core utility functions.

Covers:
  - serialize_dt with aware, naive, and None datetimes
  - strip_markdown_codeblocks with various fence styles
  - GENERIC_EMAIL_DOMAINS constant
"""

from datetime import UTC, datetime

from src.core.utils import GENERIC_EMAIL_DOMAINS, serialize_dt, strip_markdown_codeblocks


class TestSerializeDt:
    """Test datetime serialization."""

    def test_none_returns_none(self):
        assert serialize_dt(None) is None

    def test_naive_datetime(self):
        dt = datetime(2024, 3, 15, 10, 30, 0)
        assert serialize_dt(dt) == "2024-03-15T10:30:00"

    def test_aware_datetime(self):
        dt = datetime(2024, 3, 15, 10, 30, 0, tzinfo=UTC)
        result = serialize_dt(dt)
        assert "2024-03-15" in result
        assert "10:30:00" in result


class TestStripMarkdownCodeblocks:
    """Test markdown code block fence stripping."""

    def test_json_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = strip_markdown_codeblocks(text)
        assert result == '{"key": "value"}'

    def test_generic_code_block(self):
        text = "```\nhello world\n```"
        result = strip_markdown_codeblocks(text)
        assert result == "hello world"

    def test_no_code_block(self):
        text = '{"key": "value"}'
        result = strip_markdown_codeblocks(text)
        assert result == '{"key": "value"}'

    def test_leading_trailing_whitespace(self):
        text = '  ```json\n{"a": 1}\n```  '
        result = strip_markdown_codeblocks(text)
        assert result == '{"a": 1}'

    def test_empty_string(self):
        assert strip_markdown_codeblocks("") == ""

    def test_only_fences(self):
        text = "```json\n```"
        result = strip_markdown_codeblocks(text)
        assert result == ""


class TestGenericEmailDomains:
    """Test GENERIC_EMAIL_DOMAINS constant."""

    def test_common_providers_included(self):
        for domain in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"]:
            assert domain in GENERIC_EMAIL_DOMAINS

    def test_corporate_domains_not_included(self):
        for domain in ["procore.com", "hth-corp.com", "google.com"]:
            assert domain not in GENERIC_EMAIL_DOMAINS

    def test_is_frozenset(self):
        assert isinstance(GENERIC_EMAIL_DOMAINS, frozenset)
