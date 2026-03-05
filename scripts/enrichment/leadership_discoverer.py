#!/usr/bin/env python3
"""
Automated company leadership discovery via browser automation.

For each company in the CRM that has a domain but hasn't been scraped yet:
1. Google search for the company's leadership/team page
2. Scrape the page for executive names and titles
3. Generate email addresses from name + domain
4. Add them as contacts to the company via the CRM API
5. Optionally search LinkedIn for each new contact

Runs as a standalone script with human-like timing.

Usage:
    python -m scripts.enrichment.leadership_discoverer              # Full run
    python -m scripts.enrichment.leadership_discoverer --dry-run    # Preview only
    python -m scripts.enrichment.leadership_discoverer --limit 5    # Process N companies
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before reading env vars
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright  # noqa: E402

from scripts.enrichment.crm_client import CRMClient  # noqa: E402
from scripts.enrichment.human_behavior import (  # noqa: E402
    WorkSchedule,
    delay_between_profiles,
    delay_page_load,
)
from src.core.config import settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")

# Common leadership page URL patterns
LEADERSHIP_URL_PATTERNS = [
    "/about/leadership",
    "/about-us/leadership",
    "/leadership",
    "/our-team",
    "/about/team",
    "/about-us/our-team",
    "/about/our-leadership",
    "/about/executives",
    "/about/management",
    "/people",
    "/team",
]

# Name patterns to exclude (not real people)
EXCLUDE_PATTERNS = re.compile(
    r"(cookie|privacy|contact us|learn more|read more|view all|see all|"
    r"©|copyright|\d{4}|terms|careers|join)",
    re.IGNORECASE,
)

# Common executive title keywords
TITLE_KEYWORDS = re.compile(
    r"(president|chief|ceo|cfo|coo|cto|cio|cmo|cpo|evp|svp|"
    r"vice president|vp|director|head of|managing|partner|founder|"
    r"general manager|executive|officer|principal|senior)",
    re.IGNORECASE,
)


def _looks_like_person_name(text: str) -> bool:
    """Heuristic: check if text looks like a person's name."""
    text = text.strip()
    if not text or len(text) < 3 or len(text) > 60:
        return False
    if EXCLUDE_PATTERNS.search(text):
        return False
    # Must have at least first + last name
    parts = text.split()
    if len(parts) < 2 or len(parts) > 5:
        return False
    # Each part should start with uppercase
    if not all(p[0].isupper() for p in parts if p):
        return False
    # No digits in names
    if any(c.isdigit() for c in text):
        return False
    return True


def _generate_email_guesses(name: str, domain: str) -> list[str]:
    """Generate common email patterns from name + domain."""
    parts = name.lower().split()
    if len(parts) < 2:
        return []
    first = re.sub(r"[^a-z]", "", parts[0])
    last = re.sub(r"[^a-z]", "", parts[-1])
    if not first or not last:
        return []
    return [
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}{last[0]}@{domain}",
        f"{first}@{domain}",
        f"{first}{last}@{domain}",
    ]


class LeadershipScraper:
    """Browser-based leadership page scraper."""

    def __init__(self, headless: bool = False):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = headless

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._page = self._context.new_page()
        logger.info("Leadership scraper browser started")

    def stop(self):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Leadership scraper browser stopped")

    def find_leadership_page(self, company_name: str, domain: str) -> str | None:
        """Search Google for a company's leadership/team page."""
        page = self._page
        query = f'site:{domain} "{company_name}" leadership OR team OR executives OR "our people"'
        page.goto(
            f"https://www.google.com/search?q={query}",
            wait_until="domcontentloaded",
        )
        delay_page_load()

        # Look for results that match the company domain
        links = page.query_selector_all("a[href]")
        for link in links:
            href = link.get_attribute("href") or ""
            if domain in href and any(
                kw in href.lower()
                for kw in ["leader", "team", "people", "executive", "management", "about"]
            ):
                logger.info("Found leadership page via Google: %s", href)
                return href

        # Fallback: try common URL patterns directly
        for pattern in LEADERSHIP_URL_PATTERNS:
            url = f"https://www.{domain}{pattern}"
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=10000)
                if resp and resp.status == 200:
                    # Verify it has people-like content
                    text = page.inner_text("body")
                    if TITLE_KEYWORDS.search(text):
                        logger.info("Found leadership page at known pattern: %s", url)
                        return url
            except Exception:
                continue

        logger.warning("No leadership page found for %s (%s)", company_name, domain)
        return None

    def scrape_leadership_page(self, url: str) -> list[dict]:
        """
        Visit a leadership page and extract name + title pairs.

        Returns list of {"name": str, "title": str} dicts.
        """
        page = self._page
        results = []

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            delay_page_load()
        except Exception as e:
            logger.error("Failed to load leadership page %s: %s", url, e)
            return results

        # Strategy 1: Look for structured cards/sections with name + title
        # Many sites use a common pattern: heading with name, paragraph with title
        # or cards with name + role

        # Try common CSS patterns for leadership cards
        card_selectors = [
            ".team-member",
            ".leadership-card",
            ".executive-card",
            ".person-card",
            ".staff-member",
            ".bio-card",
            "[class*='leader']",
            "[class*='team-member']",
            "[class*='executive']",
            "[class*='person']",
            "[class*='staff']",
        ]

        for selector in card_selectors:
            cards = page.query_selector_all(selector)
            if len(cards) >= 2:  # At least 2 people to be meaningful
                for card in cards:
                    person = self._extract_person_from_card(card)
                    if person:
                        results.append(person)
                if results:
                    logger.info(
                        "Extracted %d leaders from cards (%s) on %s",
                        len(results),
                        selector,
                        url,
                    )
                    return results

        # Strategy 2: Scan all headings + adjacent text for name-title pairs
        results = self._extract_from_headings(page)
        if results:
            logger.info("Extracted %d leaders from headings on %s", len(results), url)
            return results

        # Strategy 3: Look for list items with name + title patterns
        results = self._extract_from_list_items(page)
        if results:
            logger.info("Extracted %d leaders from list items on %s", len(results), url)

        return results

    def _extract_person_from_card(self, card) -> dict | None:
        """Extract name and title from a leadership card element."""
        text_parts = card.inner_text().strip().split("\n")
        text_parts = [t.strip() for t in text_parts if t.strip()]

        name = None
        title = None

        for part in text_parts:
            if not name and _looks_like_person_name(part):
                name = part
            elif name and not title and TITLE_KEYWORDS.search(part):
                title = part[:255]  # Truncate long titles
                break

        if name and title:
            return {"name": name, "title": title}
        return None

    def _extract_from_headings(self, page: Page) -> list[dict]:
        """Extract name-title pairs from headings and their siblings."""
        results = []
        headings = page.query_selector_all("h2, h3, h4, h5")

        for heading in headings:
            name_text = heading.inner_text().strip()
            if not _looks_like_person_name(name_text):
                continue

            # Look at sibling/next element for title
            sibling = heading.evaluate(
                """el => {
                    let next = el.nextElementSibling;
                    if (next) return next.innerText;
                    let parent = el.parentElement;
                    if (parent) {
                        let texts = Array.from(parent.querySelectorAll('p, span, div'))
                            .map(e => e.innerText.trim())
                            .filter(t => t && t !== el.innerText.trim());
                        return texts.join('\\n');
                    }
                    return '';
                }"""
            )

            if sibling:
                for line in sibling.split("\n"):
                    line = line.strip()
                    if line and TITLE_KEYWORDS.search(line):
                        results.append({"name": name_text, "title": line[:255]})
                        break

        return results

    def _extract_from_list_items(self, page: Page) -> list[dict]:
        """Extract from list items that contain name + title."""
        results = []
        items = page.query_selector_all("li, .grid > div, .row > div")

        for item in items:
            text = item.inner_text().strip()
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if len(lines) < 2:
                continue

            name = None
            title = None
            for line in lines[:3]:  # Only check first 3 lines
                if not name and _looks_like_person_name(line):
                    name = line
                elif name and not title and TITLE_KEYWORDS.search(line):
                    title = line[:255]
                    break

            if name and title:
                results.append({"name": name, "title": title})

        return results


def process_company(
    company: dict,
    scraper: LeadershipScraper,
    crm: CRMClient,
    dry_run: bool = False,
) -> int:
    """
    Discover leaders for a single company.

    Returns number of contacts added.
    """
    company_name = company["name"]
    domain = company["domain"]
    company_id = company["id"]

    logger.info("Processing company: %s (%s)", company_name, domain)

    # Step 1: Find the leadership page
    leadership_url = scraper.find_leadership_page(company_name, domain)
    if not leadership_url:
        # Mark as scraped (no page found) to avoid re-processing
        if not dry_run:
            crm.update_company(
                company_id,
                leadership_scraped_at=datetime.now(UTC).isoformat(),
            )
        return 0

    # Step 2: Scrape the leadership page
    leaders = scraper.scrape_leadership_page(leadership_url)
    if not leaders:
        logger.info("No leaders extracted from %s", leadership_url)
        if not dry_run:
            crm.update_company(
                company_id,
                leadership_page_url=leadership_url,
                leadership_scraped_at=datetime.now(UTC).isoformat(),
            )
        return 0

    logger.info("Found %d leaders on %s", len(leaders), leadership_url)

    # Step 3: Generate email addresses and add as contacts
    added = 0
    for leader in leaders:
        name = leader["name"]
        title = leader["title"]

        # Generate best-guess email
        email_guesses = _generate_email_guesses(name, domain)
        if not email_guesses:
            logger.warning("Could not generate email for %s", name)
            continue

        # Use the most common pattern: first.last@domain
        email = email_guesses[0]

        if dry_run:
            logger.info("[DRY RUN] Would add: %s (%s) — %s", name, title, email)
            added += 1
            continue

        try:
            result = crm.add_contact_to_company(
                company_id=company_id,
                email=email,
                name=name,
                title=title,
            )
            if result.get("created"):
                logger.info("Added contact: %s (%s) at %s", name, title, company_name)
                added += 1
            else:
                logger.info("Contact already exists: %s (%s)", name, email)
        except Exception as e:
            logger.error("Failed to add contact %s: %s", name, e)

    # Step 4: Update company with leadership page info
    if not dry_run:
        crm.update_company(
            company_id,
            leadership_page_url=leadership_url,
            leadership_scraped_at=datetime.now(UTC).isoformat(),
        )

    return added


def main():
    parser = argparse.ArgumentParser(description="Company leadership discovery")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API updates")
    parser.add_argument("--limit", type=int, default=0, help="Max companies to process (0=all)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--no-schedule", action="store_true", help="Skip work schedule")
    args = parser.parse_args()

    logger.info(
        "Leadership Discoverer starting (dry_run=%s, limit=%s)",
        args.dry_run,
        args.limit,
    )

    # Initialize work schedule
    schedule = WorkSchedule()
    if not args.no_schedule:
        if not schedule.wait_for_work_hours():
            logger.info("Past work hours for today — exiting")
            return

    # Graceful shutdown
    shutdown_requested = False

    def _signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("Shutdown requested (signal %d)", signum)
        shutdown_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Initialize API client
    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key — set ENRICHMENT_API_KEY env var or SECRET_KEY in .env")
        return

    crm = CRMClient(base_url=API_BASE, api_key=api_key)
    scraper = LeadershipScraper(headless=args.headless)

    try:
        scraper.start()

        # Fetch companies needing leadership discovery
        companies = crm.get_needs_leadership()
        logger.info("Companies needing leadership discovery: %d", len(companies))

        if args.limit:
            companies = companies[: args.limit]

        total_added = 0
        total_processed = 0

        for company in companies:
            if not args.no_schedule and not schedule.wait_for_work_hours():
                logger.info("Work day ended — stopping")
                break

            if shutdown_requested:
                logger.info("Shutdown requested — stopping")
                break

            if not args.no_schedule and schedule.should_take_break():
                schedule.take_break()

            try:
                added = process_company(company, scraper, crm, dry_run=args.dry_run)
                total_added += added
                total_processed += 1
            except Exception as e:
                logger.error("Error processing %s: %s", company["name"], e)

            if not args.no_schedule:
                delay_between_profiles()

        logger.info(
            "Leadership discovery complete: %d companies processed, %d contacts added",
            total_processed,
            total_added,
        )

    finally:
        scraper.stop()
        crm.close()


if __name__ == "__main__":
    main()
