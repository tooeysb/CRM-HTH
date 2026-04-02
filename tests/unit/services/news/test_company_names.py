"""
Tests for company name utilities.

Covers:
  - clean_company_name suffix stripping
  - SKIP_NAMES set contains expected generic names
"""

from src.services.news.company_names import SKIP_NAMES, SUFFIXES, clean_company_name


class TestCleanCompanyName:
    """Test clean_company_name suffix stripping."""

    def test_strip_llc(self):
        assert clean_company_name("Acme LLC") == "Acme"

    def test_strip_inc_with_dot(self):
        assert clean_company_name("Acme Inc.") == "Acme"

    def test_strip_inc_no_dot(self):
        assert clean_company_name("Acme Inc") == "Acme"

    def test_strip_corp_with_dot(self):
        assert clean_company_name("Acme Corp.") == "Acme"

    def test_strip_corp_no_dot(self):
        assert clean_company_name("Acme Corp") == "Acme"

    def test_strip_group(self):
        assert clean_company_name("Walsh Group") == "Walsh"

    def test_strip_company(self):
        assert clean_company_name("JT Magen Company") == "JT Magen"

    def test_strip_hq(self):
        assert clean_company_name("Procore - HQ") == "Procore"

    def test_strip_ltd(self):
        assert clean_company_name("Balfour Beatty Ltd") == "Balfour Beatty"

    def test_strip_corporation(self):
        assert clean_company_name("Turner Corporation") == "Turner"

    def test_no_suffix_unchanged(self):
        assert clean_company_name("Kiewit") == "Kiewit"

    def test_leading_trailing_whitespace(self):
        assert clean_company_name("  Acme  ") == "Acme"

    def test_case_insensitive_suffix_stripping(self):
        """Suffix matching should be case-insensitive."""
        assert clean_company_name("Acme LLC") == "Acme"
        assert clean_company_name("Acme llc") == "Acme"

    def test_multiple_suffixes_strips_one(self):
        """Only strips one suffix per pass (outermost)."""
        result = clean_company_name("Acme Co.")
        assert result == "Acme"

    def test_empty_string(self):
        assert clean_company_name("") == ""


class TestSkipNames:
    """Test SKIP_NAMES constant."""

    def test_common_generic_names_included(self):
        for name in ["target", "compass", "summit", "frontier", "core"]:
            assert name in SKIP_NAMES

    def test_specific_company_names_not_included(self):
        for name in ["turner", "kiewit", "procore", "skanska"]:
            assert name not in SKIP_NAMES

    def test_is_set_type(self):
        assert isinstance(SKIP_NAMES, set)


class TestSuffixes:
    """Test SUFFIXES constant."""

    def test_suffixes_all_lowercase(self):
        for suffix in SUFFIXES:
            assert suffix == suffix.lower()

    def test_suffixes_all_start_with_space_or_dash(self):
        for suffix in SUFFIXES:
            assert suffix.startswith(" ") or suffix.startswith("-")
