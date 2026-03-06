#!/usr/bin/env python3
"""
Automated LinkedIn company profile enrichment via browser automation.

Fetches companies from the CRM API that need LinkedIn data, searches Google
for their LinkedIn company pages, visits pages to extract and validate data,
and patches the CRM via API.

Uses multi-signal validation (domain match, name similarity, industry) to
ensure high-confidence matching before auto-approving.

Usage:
    python -m scripts.enrichment.company_linkedin_enricher              # Full run
    python -m scripts.enrichment.company_linkedin_enricher --setup      # One-time login
    python -m scripts.enrichment.company_linkedin_enricher --dry-run    # Preview only
    python -m scripts.enrichment.company_linkedin_enricher --limit 5    # Process N companies
    python -m scripts.enrichment.company_linkedin_enricher --domain-only # Only companies with domains
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before reading env vars
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from scripts.enrichment.browser import LinkedInBrowser, LinkedInCompanyProfile  # noqa: E402
from scripts.enrichment.crm_client import CRMClient  # noqa: E402
from scripts.enrichment.human_behavior import WorkSchedule, delay_between_profiles  # noqa: E402
from scripts.enrichment.state import EnrichmentState  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")

COMPANY_STATE_FILE = PROJECT_ROOT / ".company_linkedin_state.json"

# Construction industry keywords for validation
CONSTRUCTION_KEYWORDS = {
    "construction",
    "building",
    "engineering",
    "architecture",
    "infrastructure",
    "contractor",
    "contracting",
    "real estate",
    "development",
    "mechanical",
    "electrical",
    "plumbing",
    "general contractor",
    "subcontractor",
    "specialty contractor",
    "design-build",
    "civil",
    "structural",
    "hvac",
    "roofing",
    "concrete",
    "demolition",
    "excavation",
    "paving",
    "preconstruction",
    "project management",
}


# ---------------------------------------------------------------------------
# Company name and domain normalization
# ---------------------------------------------------------------------------


def _normalize_company_name(name: str) -> str:
    """Normalize company name for comparison (strip suffixes, lowercase)."""
    if not name:
        return ""
    name = name.lower().strip()
    for suffix in (
        ", inc.",
        ", inc",
        " inc.",
        " inc",
        ", llc",
        " llc",
        ", ltd.",
        ", ltd",
        " ltd.",
        " ltd",
        ", corp.",
        ", corp",
        " corp.",
        " corp",
        " corporation",
        " incorporated",
        " company",
        ", l.p.",
        " l.p.",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _normalize_domain(url_or_domain: str) -> str:
    """Extract bare domain: strip protocol, www., trailing paths."""
    d = url_or_domain.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    d = d.split("/")[0].split("?")[0]
    return d.rstrip(".")


# ---------------------------------------------------------------------------
# Multi-signal validation
# ---------------------------------------------------------------------------


def _check_domain_match(crm_domain: str | None, linkedin_website: str | None) -> int:
    """Compare CRM domain with website shown on LinkedIn company page.

    Returns: 3 (exact match), 2 (subdomain), or 0 (no match).
    """
    if not crm_domain or not linkedin_website:
        return 0

    # Handle comma-separated domains
    crm_domains = [_normalize_domain(d.strip()) for d in crm_domain.split(",") if d.strip()]
    li_norm = _normalize_domain(linkedin_website)

    if not li_norm:
        return 0

    for crm_norm in crm_domains:
        if not crm_norm:
            continue
        if crm_norm == li_norm:
            return 3
        if crm_norm.endswith("." + li_norm) or li_norm.endswith("." + crm_norm):
            return 2

    return 0


def _check_name_match(crm_name: str, linkedin_name: str | None) -> int:
    """Compare normalized company names.

    Returns: 2 (exact), 1 (substring/overlap), or 0 (no match).
    """
    if not linkedin_name:
        return 0

    crm_norm = _normalize_company_name(crm_name)
    li_norm = _normalize_company_name(linkedin_name)

    if not crm_norm or not li_norm:
        return 0

    if crm_norm == li_norm:
        return 2

    if crm_norm in li_norm or li_norm in crm_norm:
        return 1

    # Token overlap
    crm_tokens = set(crm_norm.split())
    li_tokens = set(li_norm.split())
    if crm_tokens and li_tokens:
        overlap = len(crm_tokens & li_tokens)
        total = len(crm_tokens | li_tokens)
        if total > 0 and overlap / total >= 0.5:
            return 1

    return 0


def _check_industry_match(industry: str | None, description: str | None) -> int:
    """Check if LinkedIn industry/description indicates construction.

    Returns: 1 (match) or 0 (no match).
    """
    text = " ".join(filter(None, [industry, description])).lower()
    if any(kw in text for kw in CONSTRUCTION_KEYWORDS):
        return 1
    return 0


def score_candidate(
    crm_name: str,
    crm_domain: str | None,
    profile: LinkedInCompanyProfile,
) -> tuple[int, str]:
    """Score a LinkedIn company profile candidate.

    Returns (total_score, explanation_string).
    """
    domain_score = _check_domain_match(crm_domain, profile.website_url)
    name_score = _check_name_match(crm_name, profile.company_name)
    industry_score = _check_industry_match(profile.industry, profile.description)
    total = domain_score + name_score + industry_score

    parts = []
    if domain_score == 3:
        parts.append("domain exact match")
    elif domain_score == 2:
        parts.append("domain subdomain match")
    if name_score == 2:
        parts.append("name exact match")
    elif name_score == 1:
        parts.append("name partial match")
    if industry_score:
        parts.append(f"industry match ({profile.industry})")
    if not parts:
        parts.append("no signals matched")

    explanation = f"score={total}: {', '.join(parts)}"
    return total, explanation


# ---------------------------------------------------------------------------
# Single company enrichment
# ---------------------------------------------------------------------------


def enrich_company(
    company: dict,
    browser: LinkedInBrowser,
    crm: CRMClient,
    dry_run: bool = False,
    min_confidence: int = 2,
) -> str:
    """
    Enrich a single company with LinkedIn data.

    Returns: "enriched", "needs_review", or "not_found".
    """
    company_id = company["id"]
    name = company["name"]
    domain = company.get("domain")

    logger.info("Processing: %s (domain: %s)", name, domain or "none")

    # Step 1: Search Google for LinkedIn company page
    candidates = browser.search_google_for_company_linkedin(name, domain)

    if not candidates:
        logger.info("NOT FOUND: %s — no Google results", name)
        if not dry_run:
            crm.update_company(company_id, linkedin_name=f"[not found] {name}")
        return "not_found"

    # Step 2: Visit each candidate and score it
    best_score = -1
    best_profile: LinkedInCompanyProfile | None = None
    best_explanation = ""
    best_url = ""

    for url in candidates:
        profile = browser.extract_company_profile(url)

        if not profile.company_name:
            logger.info("Skipping %s — no company name extracted", url)
            continue

        total, explanation = score_candidate(name, domain, profile)
        logger.info("Candidate %s: %s", url, explanation)

        if total > best_score:
            best_score = total
            best_profile = profile
            best_explanation = explanation
            best_url = url

        # If we got a perfect domain match, no need to check more
        if total >= 3:
            break

    # Step 3: Decision based on confidence score
    if best_profile is None:
        logger.info("NOT FOUND: %s — no usable profiles from %d candidates", name, len(candidates))
        if not dry_run:
            crm.update_company(company_id, linkedin_name=f"[not found] {name}")
        return "not_found"

    if best_score >= min_confidence:
        # Auto-approve; mark as Tooey Approved when high confidence (score >= 3)
        high_confidence = best_score >= 3
        logger.info(
            "ENRICHED: %s -> %s (%s)%s",
            name, best_url, best_explanation,
            " [APPROVED]" if high_confidence else "",
        )
        if not dry_run:
            update_fields: dict = {"linkedin_url": best_url}
            if best_profile.company_name and best_profile.company_name != name:
                update_fields["linkedin_name"] = best_profile.company_name
            if high_confidence:
                update_fields["is_approved"] = True
            crm.update_company(company_id, **update_fields)
        return "enriched"
    else:
        # Flag for review
        logger.info("NEEDS REVIEW: %s — best candidate %s (%s)", name, best_url, best_explanation)
        if not dry_run:
            crm.update_company(
                company_id,
                linkedin_name=f"[review] {best_profile.company_name or 'unknown'} | {best_url}",
            )
        return "needs_review"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="LinkedIn company profile enrichment")
    parser.add_argument("--setup", action="store_true", help="Interactive LinkedIn login")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API updates")
    parser.add_argument(
        "--limit",
        type=int,
        default=random.randint(40, 60),
        help="Max companies to process (default: ~50 randomized)",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--no-schedule", action="store_true", help="Skip work schedule (run now)")
    parser.add_argument(
        "--start-now", action="store_true", help="Skip initial work hours wait but keep pacing"
    )
    parser.add_argument(
        "--domain-only",
        action="store_true",
        help="Only process companies that have a domain (higher confidence)",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        help="Minimum confidence score to auto-approve (default: 2)",
    )
    args = parser.parse_args()

    browser = LinkedInBrowser(headless=args.headless)

    # --setup mode: interactive login
    if args.setup:
        browser.setup_auth()
        return

    logger.info(
        "Company LinkedIn Enricher starting (dry_run=%s, limit=%s, domain_only=%s, min_confidence=%s)",
        args.dry_run,
        args.limit,
        args.domain_only,
        args.min_confidence,
    )

    # Load state and reset if new day
    state = EnrichmentState.load(state_file=COMPANY_STATE_FILE)
    state.reset_if_new_day()

    # Initialize work schedule
    schedule = WorkSchedule()
    check_hours = not args.no_schedule and not args.start_now
    use_pacing = not args.no_schedule
    if check_hours:
        if not schedule.wait_for_work_hours():
            logger.info("Past work hours for today — exiting")
            return

    # Graceful shutdown on SIGINT/SIGTERM
    shutdown_requested = False

    def _signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("Shutdown requested (signal %d) — finishing current company", signum)
        shutdown_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Initialize API client
    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key — set ENRICHMENT_API_KEY env var or SECRET_KEY in .env")
        return
    crm = CRMClient(base_url=API_BASE, api_key=api_key)

    try:
        browser.start()

        # Fetch queue
        all_companies = crm.get_needs_company_linkedin()
        logger.info("Companies needing LinkedIn: %d total", len(all_companies))

        if args.domain_only:
            all_companies = [c for c in all_companies if c.get("domain")]
            logger.info("After domain-only filter: %d companies", len(all_companies))

        # Filter out already-processed
        companies = [c for c in all_companies if not state.is_processed(c["id"])]
        logger.info(
            "%d companies to process (%d already done today)",
            len(companies),
            len(all_companies) - len(companies),
        )

        if args.limit:
            companies = companies[: args.limit]

        enriched_count = 0
        review_count = 0
        not_found_count = 0

        for company in companies:
            if check_hours and not schedule.wait_for_work_hours():
                logger.info("Work day ended — stopping")
                break

            if shutdown_requested:
                logger.info("Shutdown requested — stopping gracefully")
                break

            if use_pacing and schedule.should_take_break():
                schedule.take_break()

            try:
                result = enrich_company(
                    company, browser, crm, dry_run=args.dry_run, min_confidence=args.min_confidence
                )
                state.mark_processed(company["id"])
                if result == "enriched":
                    enriched_count += 1
                elif result == "needs_review":
                    review_count += 1
                else:
                    not_found_count += 1
            except Exception as e:
                logger.error("Error processing company %s: %s", company["name"], e)
                state.mark_error()
                state.mark_skipped(company["id"])

            state.save()

            if use_pacing:
                delay_between_profiles()

        logger.info(
            "Complete: %d enriched, %d needs review, %d not found, %d errors",
            enriched_count,
            review_count,
            not_found_count,
            state.total_errors,
        )

    finally:
        browser.stop()
        crm.close()
        state.save()


if __name__ == "__main__":
    main()
