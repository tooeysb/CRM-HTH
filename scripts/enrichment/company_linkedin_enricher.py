#!/usr/bin/env python3
"""
Two-phase LinkedIn company profile enrichment via browser automation.

Phase 1 (google): Search Google for LinkedIn company page URLs. Saves candidates
to a JSON file. Only hits Google — never touches LinkedIn.

Phase 2 (linkedin): Read candidates file, visit each LinkedIn company page to
extract profiles, score, and update CRM. Only hits LinkedIn — never touches Google.

This separation prevents Google CAPTCHAs from blocking LinkedIn work and vice versa.

Usage:
    python -m scripts.enrichment.company_linkedin_enricher --phase google     # Phase 1
    python -m scripts.enrichment.company_linkedin_enricher --phase linkedin   # Phase 2
    python -m scripts.enrichment.company_linkedin_enricher --setup            # One-time login
    python -m scripts.enrichment.company_linkedin_enricher --phase google --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before reading env vars
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from scripts.enrichment.browser import LinkedInBrowser, LinkedInCompanyProfile  # noqa: E402
from scripts.enrichment.crm_client import CRMClient  # noqa: E402
from scripts.enrichment.human_behavior import (
    delay_between_clicks,
)

# noqa: E402
from src.core.config import settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")

CANDIDATES_FILE = PROJECT_ROOT / ".company_linkedin_candidates.json"

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
    if not crm_domain or not linkedin_website:
        return 0
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
    crm_tokens = set(crm_norm.split())
    li_tokens = set(li_norm.split())
    if crm_tokens and li_tokens:
        overlap = len(crm_tokens & li_tokens)
        total = len(crm_tokens | li_tokens)
        if total > 0 and overlap / total >= 0.5:
            return 1
    return 0


def _check_industry_match(industry: str | None, description: str | None) -> int:
    text = " ".join(filter(None, [industry, description])).lower()
    if any(kw in text for kw in CONSTRUCTION_KEYWORDS):
        return 1
    return 0


def score_candidate(
    crm_name: str,
    crm_domain: str | None,
    profile: LinkedInCompanyProfile,
) -> tuple[int, str]:
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
# Candidates file management
# ---------------------------------------------------------------------------


def _load_candidates() -> dict:
    """Load candidates file. Format: {company_id: {company data + candidates list}}."""
    if CANDIDATES_FILE.exists():
        try:
            return json.loads(CANDIDATES_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt candidates file — starting fresh")
    return {}


def _save_candidates(data: dict):
    CANDIDATES_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Phase 1: Google search
# ---------------------------------------------------------------------------


def phase_google(args):
    """Search Google for LinkedIn company page candidates. Saves to JSON file."""
    logger.info("PHASE 1: Google Search (dry_run=%s, limit=%s)", args.dry_run, args.limit)

    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key")
        return
    crm = CRMClient(base_url=API_BASE, api_key=api_key)

    # Load existing candidates to skip already-searched companies
    candidates_data = _load_candidates()

    # Fetch queue
    all_companies = crm.get_needs_company_linkedin()
    logger.info("Companies needing LinkedIn: %d total", len(all_companies))

    if args.domain_only:
        all_companies = [c for c in all_companies if c.get("domain")]
        logger.info("After domain-only filter: %d", len(all_companies))

    if args.retry_misses:
        # Only retry companies that were searched but got zero candidates
        miss_ids = {
            cid
            for cid, v in candidates_data.items()
            if v.get("searched") and not v.get("candidate_urls")
        }
        companies = [c for c in all_companies if c["id"] in miss_ids]
        # Clear their "searched" flag so they get re-processed
        for c in companies:
            candidates_data[c["id"]]["searched"] = False
        logger.info("Retrying %d companies that had zero candidates", len(companies))
    else:
        searched_ids = {cid for cid, v in candidates_data.items() if v.get("searched")}
        companies = [c for c in all_companies if c["id"] not in searched_ids]
        logger.info(
            "%d to search (%d already done)", len(companies), len(all_companies) - len(companies)
        )

    if args.limit:
        companies = companies[: args.limit]

    # Graceful shutdown
    shutdown_requested = False

    def _signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("Shutdown requested — saving progress")
        shutdown_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    browser = LinkedInBrowser(headless=args.headless)
    found = 0
    not_found = 0

    try:
        browser.start()

        for i, company in enumerate(companies):
            if shutdown_requested:
                break

            cid = company["id"]
            name = company["name"]
            domain = company.get("domain")

            logger.info(
                "[%d/%d] Searching: %s (domain: %s)", i + 1, len(companies), name, domain or "none"
            )

            urls = browser.search_google_for_company_linkedin(name, domain, engine=args.engine)

            candidates_data[cid] = {
                "id": cid,
                "name": name,
                "domain": domain,
                "company_type": company.get("company_type"),
                "candidate_urls": urls,
                "searched": True,
                "enriched": False,
            }

            if urls:
                found += 1
                logger.info("FOUND %d candidates for %s: %s", len(urls), name, urls)
            else:
                not_found += 1
                logger.info("NO CANDIDATES for %s", name)

            _save_candidates(candidates_data)

            # Pace searches: 30-60s for DuckDuckGo, 60-90s for Google (more aggressive rate limiting)
            if i < len(companies) - 1 and not shutdown_requested:
                if args.engine == "google":
                    delay = random.uniform(60, 90)
                else:
                    delay = random.uniform(30, 60)
                logger.info("Waiting %.0f seconds before next search", delay)
                time.sleep(delay)

    finally:
        browser.stop()
        crm.close()
        _save_candidates(candidates_data)

    logger.info("Phase 1 complete: %d found, %d not found", found, not_found)


# ---------------------------------------------------------------------------
# Phase 2: LinkedIn visit + scoring
# ---------------------------------------------------------------------------


def phase_linkedin(args):
    """Visit LinkedIn candidate pages, extract profiles, score, and update CRM."""
    logger.info("PHASE 2: LinkedIn Visit (dry_run=%s, limit=%s)", args.dry_run, args.limit)

    candidates_data = _load_candidates()
    if not candidates_data:
        logger.error("No candidates file found — run --phase google first")
        return

    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key")
        return
    crm = CRMClient(base_url=API_BASE, api_key=api_key)

    # Filter to companies with candidates that haven't been enriched yet
    to_process = [
        v
        for v in candidates_data.values()
        if v.get("searched") and not v.get("enriched") and v.get("candidate_urls")
    ]
    # Also handle companies with no candidates (mark as not found)
    no_candidates = [
        v
        for v in candidates_data.values()
        if v.get("searched") and not v.get("enriched") and not v.get("candidate_urls")
    ]

    logger.info(
        "%d companies with candidates, %d with no candidates",
        len(to_process),
        len(no_candidates),
    )

    # Mark no-candidate companies as not found
    for company in no_candidates:
        if not args.dry_run:
            crm.update_company(company["id"], linkedin_name=f"[not found] {company['name']}")
        company["enriched"] = True
        company["result"] = "not_found"
        logger.info("NOT FOUND: %s — no Google candidates", company["name"])
    _save_candidates(candidates_data)

    if args.limit:
        to_process = to_process[: args.limit]

    # Graceful shutdown
    shutdown_requested = False

    def _signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("Shutdown requested — saving progress")
        shutdown_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    browser = LinkedInBrowser(headless=args.headless)
    enriched_count = 0
    review_count = 0
    not_found_count = 0

    try:
        browser.start()

        for i, company in enumerate(to_process):
            if shutdown_requested:
                break

            cid = company["id"]
            name = company["name"]
            domain = company.get("domain")
            urls = company["candidate_urls"]

            logger.info(
                "[%d/%d] Visiting: %s (%d candidates)", i + 1, len(to_process), name, len(urls)
            )

            # Visit each candidate and score
            best_score = -1
            best_profile: LinkedInCompanyProfile | None = None
            best_explanation = ""
            best_url = ""

            for url in urls:
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

                if total >= 3:
                    break

                delay_between_clicks()

            # Decision
            if best_profile is None:
                logger.info("NOT FOUND: %s — no usable profiles", name)
                if not args.dry_run:
                    crm.update_company(cid, linkedin_name=f"[not found] {name}")
                company["result"] = "not_found"
                not_found_count += 1

            elif best_score >= args.min_confidence:
                high_confidence = best_score >= 3
                logger.info(
                    "ENRICHED: %s -> %s (%s)%s",
                    name,
                    best_url,
                    best_explanation,
                    " [APPROVED]" if high_confidence else "",
                )
                if not args.dry_run:
                    update_fields: dict = {"linkedin_url": best_url}
                    if best_profile.company_name and best_profile.company_name != name:
                        update_fields["linkedin_name"] = best_profile.company_name
                    if high_confidence:
                        update_fields["is_approved"] = True
                    crm.update_company(cid, **update_fields)
                company["result"] = "enriched"
                enriched_count += 1

            else:
                logger.info("NEEDS REVIEW: %s — best %s (%s)", name, best_url, best_explanation)
                if not args.dry_run:
                    crm.update_company(
                        cid,
                        linkedin_name=f"[review] {best_profile.company_name or 'unknown'} | {best_url}",
                    )
                company["result"] = "needs_review"
                review_count += 1

            company["enriched"] = True
            _save_candidates(candidates_data)

            # Pace LinkedIn visits: 30-60 seconds between companies
            if i < len(to_process) - 1 and not shutdown_requested:
                delay = random.uniform(30, 60)
                logger.info("Waiting %.0f seconds before next LinkedIn visit", delay)
                time.sleep(delay)

    finally:
        browser.stop()
        crm.close()
        _save_candidates(candidates_data)

    logger.info(
        "Phase 2 complete: %d enriched, %d needs review, %d not found",
        enriched_count,
        review_count,
        not_found_count,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Two-phase LinkedIn company enrichment")
    parser.add_argument("--setup", action="store_true", help="Interactive LinkedIn login")
    parser.add_argument(
        "--phase",
        choices=["google", "linkedin"],
        help="Phase to run: google (search) or linkedin (visit+score)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without API updates")
    parser.add_argument("--limit", type=int, default=0, help="Max companies to process (0=all)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument(
        "--domain-only",
        action="store_true",
        help="Only process companies that have a domain",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        help="Minimum confidence score to auto-approve (default: 2)",
    )
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help="Phase 1 only: retry companies that had zero candidates",
    )
    parser.add_argument(
        "--engine",
        choices=["duckduckgo", "google"],
        default="duckduckgo",
        help="Search engine to use for Phase 1 (default: duckduckgo)",
    )
    args = parser.parse_args()

    browser = LinkedInBrowser(headless=args.headless)

    if args.setup:
        browser.setup_auth()
        return

    if not args.phase:
        parser.error("--phase is required (google or linkedin)")

    if args.phase == "google":
        phase_google(args)
    elif args.phase == "linkedin":
        phase_linkedin(args)


if __name__ == "__main__":
    main()
