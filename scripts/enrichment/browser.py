"""
Playwright-based browser automation for LinkedIn profile extraction.

Uses saved auth state (cookies) to access LinkedIn without locking the user's Chrome profile.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from scripts.enrichment.human_behavior import delay_between_clicks, delay_page_load
from scripts.enrichment.proxy import ProxyRotator
from src.core.logging import get_logger

logger = get_logger(__name__)

AUTH_STATE_FILE = Path(__file__).parent / ".auth_state.json"


@dataclass
class LinkedInProfile:
    """Extracted LinkedIn profile data."""

    title: str | None = None
    linkedin_url: str | None = None
    company_name: str | None = None
    company_linkedin_url: str | None = None


@dataclass
class LinkedInCompanyProfile:
    """Extracted LinkedIn company page data."""

    company_name: str | None = None
    linkedin_url: str | None = None
    website_url: str | None = None
    industry: str | None = None
    description: str | None = None


@dataclass
class LinkedInPostData:
    """Extracted LinkedIn post from a contact's activity feed."""

    post_url: str | None = None
    post_text: str | None = None
    post_date_raw: str | None = None  # raw relative date: "3d", "1w"
    post_type: str = "original"  # original, shared, article
    engagement_count: int = 0


class LinkedInBrowser:
    """Manages a Playwright browser session for LinkedIn browsing."""

    def __init__(self, headless: bool = False, proxy: bool = False):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = headless
        self._proxy = ProxyRotator() if proxy else None

    # ------------------------------------------------------------------
    # Setup: interactive login to save cookies
    # ------------------------------------------------------------------

    def setup_auth(self):
        """Launch browser for manual LinkedIn login, then save auth state.

        Auto-detects successful login by watching for URL change from /login
        to the LinkedIn feed. Waits up to 5 minutes.
        """
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        logger.info("Please log into LinkedIn in the browser window.")
        logger.info("Waiting for login to complete (up to 5 minutes)...")

        # Wait until the URL is no longer the login page
        page.wait_for_url(
            lambda url: "/login" not in url and "/checkpoint" not in url,
            timeout=300000,
        )
        logger.info("Login detected — saving session cookies...")

        context.storage_state(path=str(AUTH_STATE_FILE))
        logger.info("Auth state saved to %s", AUTH_STATE_FILE)

        context.close()
        browser.close()
        pw.stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Launch Chromium with saved LinkedIn session."""
        if not AUTH_STATE_FILE.exists():
            raise FileNotFoundError(
                f"No auth state found at {AUTH_STATE_FILE}. "
                "Run with --setup first to log into LinkedIn."
            )

        self._playwright = sync_playwright().start()

        launch_kwargs = {
            "headless": self._headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        if self._proxy and self._proxy.enabled:
            proxy_config = self._proxy.get_playwright_proxy()
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            storage_state=str(AUTH_STATE_FILE),
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        # Remove webdriver property that LinkedIn checks
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self._page = self._context.new_page()
        logger.info("Browser started with saved LinkedIn session")

    def stop(self):
        """Close browser and cleanup."""
        if self._context:
            # Save refreshed cookies for next run
            try:
                self._context.storage_state(path=str(AUTH_STATE_FILE))
            except Exception:
                pass
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Browser stopped")

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    def _scroll_page(self):
        """Scroll down the page like a human would."""
        page = self._page
        scroll_amount = random.randint(300, 700)
        page.mouse.wheel(0, scroll_amount)
        delay_between_clicks()
        # Sometimes scroll a bit more
        if random.random() < 0.3:
            page.mouse.wheel(0, random.randint(200, 500))
            delay_between_clicks()

    def _is_login_page(self) -> bool:
        """Check if LinkedIn redirected to the login page (cookies expired)."""
        url = self._page.url
        return "/login" in url or "/authwall" in url or "/checkpoint" in url

    def _check_and_handle_captcha(self) -> bool:
        """Detect CAPTCHA from Google or LinkedIn and back off if found.

        Returns True if a CAPTCHA was detected (and we waited it out).
        """
        import time

        url = self._page.url
        page_text = ""
        try:
            page_text = self._page.inner_text("body")
        except Exception:
            pass

        text_lower = page_text.lower()

        is_captcha = (
            "/sorry/" in url
            or "recaptcha" in url
            or "/checkpoint/challenge" in url
            or "security verification" in text_lower
            or "verify you're a real person" in text_lower
            or "let's do a quick security check" in text_lower
            or "unusual traffic" in text_lower
            or "captcha" in text_lower
            or "are you a robot" in text_lower
        )

        if is_captcha:
            wait_minutes = random.uniform(15, 20)
            logger.warning(
                "CAPTCHA detected at %s — backing off for %.1f minutes", url, wait_minutes
            )
            time.sleep(wait_minutes * 60)
            return True
        return False

    # ------------------------------------------------------------------
    # Web search helpers
    # ------------------------------------------------------------------

    def _web_search(self, query: str) -> str:
        """Execute a DuckDuckGo search and return page HTML content."""
        page = self._page
        url = f"https://duckduckgo.com/?q={quote_plus(query)}"
        page.goto(url, wait_until="domcontentloaded")
        delay_page_load()
        if self._check_and_handle_captcha():
            page.goto(url, wait_until="domcontentloaded")
            delay_page_load()
        self._scroll_page()
        return page.content()

    def _google_search(self, query: str) -> str:
        """Execute a Google search and return page HTML content."""
        page = self._page
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        page.goto(url, wait_until="domcontentloaded")
        delay_page_load()
        if self._check_and_handle_captcha():
            page.goto(url, wait_until="domcontentloaded")
            delay_page_load()
        self._scroll_page()
        return page.content()

    def search_google_for_linkedin(self, name: str, company: str | None) -> str | None:
        """
        Search DuckDuckGo for a person's LinkedIn profile.

        Returns the first linkedin.com/in/ URL found, or None.
        """
        parts = [name]
        if company:
            parts.append(company)
        parts.append("LinkedIn")
        query = " ".join(parts)

        content = self._web_search(query)

        # Extract LinkedIn profile URLs from search results
        matches = re.findall(r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)", content)
        if matches:
            seen = []
            for slug in matches:
                if slug not in seen:
                    seen.append(slug)
            linkedin_url = f"https://www.linkedin.com/in/{seen[0]}"
            logger.info("Found LinkedIn URL: %s", linkedin_url)
            return linkedin_url

        logger.warning("No LinkedIn profile found for: %s", query)
        return None

    # ------------------------------------------------------------------
    # Company LinkedIn search
    # ------------------------------------------------------------------

    def search_google_for_company_linkedin(
        self,
        company_name: str,
        domain: str | None = None,
        engine: str = "duckduckgo",
    ) -> list[str]:
        """
        Search for a company's LinkedIn page.

        Args:
            engine: "duckduckgo" (default) or "google"

        Returns up to 5 candidate linkedin.com/company/ URLs.
        Tries site: operator first, then falls back to simpler "Company LinkedIn" query.
        """
        search_fn = self._google_search if engine == "google" else self._web_search
        candidates: list[str] = []

        # Primary search: company name with site: operator
        query = f'"{company_name}" site:linkedin.com/company/'
        search_fn(query)
        candidates.extend(self._extract_company_slugs_from_page())

        # Domain-based search — always run when domain is available
        if domain and len(candidates) < 5:
            delay_between_clicks()
            domains = [d.strip() for d in domain.split(",") if d.strip()]
            for d in domains[:2]:
                query = f'"{d}" site:linkedin.com/company/'
                search_fn(query)
                for url in self._extract_company_slugs_from_page():
                    if url not in candidates:
                        candidates.append(url)
                if len(candidates) >= 5:
                    break

        # Fallback: simpler query without site: operator (works better on some engines)
        if not candidates:
            delay_between_clicks()
            query = f'{company_name} LinkedIn company'
            search_fn(query)
            candidates.extend(self._extract_company_slugs_from_page())

        if candidates:
            logger.info(
                "Found %d company LinkedIn candidate(s) for %s", len(candidates), company_name
            )
        else:
            logger.warning("No LinkedIn company page found for: %s", company_name)

        return candidates[:5]

    def _extract_company_slugs_from_page(self) -> list[str]:
        """Extract unique linkedin.com/company/ URLs from current Google results page."""
        content = self._page.content()
        matches = re.findall(r"https?://(?:www\.)?linkedin\.com/company/([a-zA-Z0-9_-]+)", content)
        seen: list[str] = []
        for slug in matches:
            if slug not in seen and slug not in ("company", "companies"):
                seen.append(slug)
        return [f"https://www.linkedin.com/company/{s}/" for s in seen]

    # ------------------------------------------------------------------
    # Company profile extraction
    # ------------------------------------------------------------------

    def extract_company_profile(self, company_url: str) -> LinkedInCompanyProfile:
        """Navigate to a LinkedIn company page and extract profile data."""
        result = LinkedInCompanyProfile(linkedin_url=company_url)
        page = self._page

        try:
            # Visit the About tab for the richest data
            about_url = company_url.rstrip("/") + "/about/"
            page.goto(about_url, wait_until="domcontentloaded", timeout=15000)
            delay_page_load()

            if self._check_and_handle_captcha():
                # Retry after backoff
                page.goto(about_url, wait_until="domcontentloaded", timeout=15000)
                delay_page_load()

            if self._is_login_page():
                logger.error("LinkedIn session expired — re-run with --setup")
                return result

            self._scroll_page()

            # Company name from h1
            h1 = page.query_selector("h1")
            if h1:
                name = h1.inner_text().strip()
                if name and len(name) < 200:
                    result.company_name = name

            # Fallback: page title "Company Name | LinkedIn"
            if not result.company_name:
                title = page.title()
                if title and " | LinkedIn" in title:
                    result.company_name = title.split(" | LinkedIn")[0].strip()

            # Extract structured data from page text (resilient to layout changes)
            page_text = page.inner_text("body")

            # Website URL — look for a line after "Website" label
            website_match = re.search(r"Website\s*\n\s*(.+)", page_text)
            if website_match:
                candidate = website_match.group(1).strip()
                # Validate it looks like a domain
                if "." in candidate and len(candidate) < 100 and " " not in candidate:
                    result.website_url = candidate

            # Also check for website redirect links
            if not result.website_url:
                website_links = page.query_selector_all("a[href*='/company/'][href*='/website']")
                for link in website_links:
                    text = link.inner_text().strip()
                    if text and "." in text and len(text) < 100:
                        result.website_url = text
                        break

            # Industry
            industry_match = re.search(r"Industry\s*\n\s*(.+)", page_text)
            if industry_match:
                result.industry = industry_match.group(1).strip()

            # Description — first large paragraph in the overview section
            overview_match = re.search(
                r"Overview\s*\n\s*(.+?)(?:\n\n|\nWebsite|\nIndustry)", page_text, re.DOTALL
            )
            if overview_match:
                desc = overview_match.group(1).strip()
                if len(desc) > 20:
                    result.description = desc[:500]

            delay_between_clicks()
            logger.info(
                "Extracted company profile: name=%s, website=%s, industry=%s",
                result.company_name,
                result.website_url,
                result.industry,
            )

        except Exception as e:
            logger.error("Error extracting company profile from %s: %s", company_url, e)

        return result

    # ------------------------------------------------------------------
    # LinkedIn activity/post extraction
    # ------------------------------------------------------------------

    def extract_recent_activity(
        self, linkedin_url: str, max_posts: int = 5
    ) -> list[LinkedInPostData]:
        """Navigate to a contact's recent activity page and extract posts.

        Args:
            linkedin_url: The contact's LinkedIn profile URL (e.g., https://www.linkedin.com/in/johndoe)
            max_posts: Maximum number of posts to extract.

        Returns:
            List of LinkedInPostData with extracted post info.
        """
        page = self._page
        activity_url = linkedin_url.rstrip("/") + "/recent-activity/all/"

        try:
            page.goto(activity_url, wait_until="domcontentloaded", timeout=15000)
            delay_page_load()

            if self._check_and_handle_captcha():
                page.goto(activity_url, wait_until="domcontentloaded", timeout=15000)
                delay_page_load()

            if self._is_login_page():
                logger.error("LinkedIn session expired — cannot extract activity")
                return []

            # Scroll to load more posts
            self._scroll_page()
            delay_between_clicks()
            self._scroll_page()

            posts: list[LinkedInPostData] = []
            content = page.content()

            # Try multiple selector strategies — LinkedIn changes DOM frequently
            post_selectors = [
                "div.feed-shared-update-v2",
                "div[data-urn*='activity']",
                "div.occludable-update",
                "article.feed-shared-update",
            ]

            post_elements = []
            for selector in post_selectors:
                post_elements = page.query_selector_all(selector)
                if post_elements:
                    break

            if not post_elements:
                # Fallback: try to detect "no activity" state
                page_text = ""
                try:
                    page_text = page.inner_text("body")
                except Exception:
                    pass
                if "hasn't posted" in page_text.lower() or "no activity" in page_text.lower():
                    logger.info("No activity found for %s", linkedin_url)
                else:
                    logger.warning(
                        "Could not find post elements for %s — DOM may have changed", linkedin_url
                    )
                return []

            for elem in post_elements[:max_posts]:
                post = LinkedInPostData()

                # Extract post text (multiple selector fallbacks)
                for text_sel in [
                    ".feed-shared-text",
                    ".update-components-text",
                    ".feed-shared-inline-show-more-text",
                    "span[dir='ltr']",
                ]:
                    text_el = elem.query_selector(text_sel)
                    if text_el:
                        raw_text = text_el.inner_text().strip()
                        if raw_text:
                            post.post_text = raw_text[:2000]
                            break

                # Extract post URL from permalink/share link
                for link_sel in [
                    "a[href*='/feed/update/']",
                    "a[href*='activity-']",
                    ".feed-shared-actor__sub-description a",
                ]:
                    link_el = elem.query_selector(link_sel)
                    if link_el:
                        href = link_el.get_attribute("href")
                        if href:
                            post.post_url = href.split("?")[0]
                            if not post.post_url.startswith("http"):
                                post.post_url = "https://www.linkedin.com" + post.post_url
                            break

                # Extract relative date
                for time_sel in [
                    "time",
                    ".update-components-actor__sub-description",
                    "span.feed-shared-actor__sub-description",
                ]:
                    time_el = elem.query_selector(time_sel)
                    if time_el:
                        raw = time_el.inner_text().strip()
                        if raw and any(c.isdigit() for c in raw):
                            post.post_date_raw = raw
                            break

                # Detect post type
                if elem.query_selector(
                    ".feed-shared-reshared-update, .update-components-mini-update-v2"
                ):
                    post.post_type = "shared"
                elif elem.query_selector(".feed-shared-article, .update-components-article"):
                    post.post_type = "article"

                # Extract engagement count
                for social_sel in [
                    ".social-details-social-counts",
                    ".social-details-social-activity",
                ]:
                    social_el = elem.query_selector(social_sel)
                    if social_el:
                        social_text = social_el.inner_text()
                        numbers = re.findall(r"(\d+)", social_text)
                        post.engagement_count = sum(int(n) for n in numbers)
                        break

                if post.post_url or post.post_text:
                    posts.append(post)

            logger.info(
                "Extracted %d posts from %s", len(posts), linkedin_url
            )
            return posts

        except Exception as e:
            logger.error("Error extracting activity from %s: %s", linkedin_url, e)
            return []

    @staticmethod
    def parse_relative_date(text: str) -> int | None:
        """Parse LinkedIn relative date string to days ago.

        Examples: "3d" -> 3, "1w" -> 7, "2mo" -> 60, "1yr" -> 365
        Returns None if unparseable.
        """
        import re as _re

        patterns = [
            (r"(\d+)\s*m(?:in)?(?:ute)?s?\b", lambda m: 0),  # minutes -> 0 days
            (r"(\d+)\s*h(?:r|our)?s?\b", lambda m: 0),  # hours -> 0 days
            (r"(\d+)\s*d(?:ay)?s?\b", lambda m: int(m)),
            (r"(\d+)\s*w(?:eek|k)?s?\b", lambda m: int(m) * 7),
            (r"(\d+)\s*mo(?:nth)?s?\b", lambda m: int(m) * 30),
            (r"(\d+)\s*y(?:r|ear)?s?\b", lambda m: int(m) * 365),
        ]
        text = text.lower().strip()
        for pattern, calc in patterns:
            match = _re.search(pattern, text)
            if match:
                return calc(match.group(1))
        return None

    # ------------------------------------------------------------------
    # Personal profile extraction
    # ------------------------------------------------------------------

    def extract_profile(self, linkedin_url: str) -> LinkedInProfile:
        """Navigate to a LinkedIn profile and extract title + company info."""
        result = LinkedInProfile(linkedin_url=linkedin_url)
        page = self._page

        try:
            page.goto(linkedin_url, wait_until="domcontentloaded", timeout=15000)
            delay_page_load()

            if self._check_and_handle_captcha():
                page.goto(linkedin_url, wait_until="domcontentloaded", timeout=15000)
                delay_page_load()

            if self._is_login_page():
                logger.error("LinkedIn session expired — re-run with --setup")
                return result

            self._scroll_page()

            # Extract headline/title from the profile
            # LinkedIn puts the headline in a div.text-body-medium below the name
            headline_el = page.query_selector("div.text-body-medium.break-words")
            if headline_el:
                headline = headline_el.inner_text().strip()
                result.title = self._parse_title_from_headline(headline)
                logger.info("Extracted title: %s", result.title)
            else:
                # Fallback: try the page title tag ("Name - Title - Company | LinkedIn")
                title_tag = page.title()
                if title_tag:
                    parsed = self._parse_title_from_page_title(title_tag)
                    if parsed:
                        result.title = parsed
                        logger.info("Extracted title from page title: %s", result.title)

            # Find company LinkedIn URL from the profile
            company_links = page.query_selector_all("a[href*='/company/']")
            for link in company_links:
                href = link.get_attribute("href") or ""
                match = re.search(r"(https?://www\.linkedin\.com/company/[^/?#]+)", href)
                if match:
                    result.company_linkedin_url = match.group(1).rstrip("/") + "/"
                    # Get company name text from the link
                    text = link.inner_text().strip()
                    if text and len(text) < 100:
                        result.company_name = text
                    break

            delay_between_clicks()

            # Visit company page to get canonical name
            if result.company_linkedin_url:
                canonical_name = self._extract_company_name(result.company_linkedin_url)
                if canonical_name:
                    result.company_name = canonical_name

        except Exception as e:
            logger.error("Error extracting profile from %s: %s", linkedin_url, e)

        return result

    def _extract_company_name(self, company_url: str) -> str | None:
        """Navigate to company LinkedIn page and extract the canonical name."""
        page = self._page
        try:
            page.goto(company_url, wait_until="domcontentloaded", timeout=15000)
            delay_page_load()
            if self._check_and_handle_captcha():
                page.goto(company_url, wait_until="domcontentloaded", timeout=15000)
                delay_page_load()
            self._scroll_page()

            # Company name is in the h1 element
            name_el = page.query_selector("h1")
            if name_el:
                name = name_el.inner_text().strip()
                if name and len(name) < 200:
                    logger.info("Company name from LinkedIn: %s", name)
                    return name
        except Exception as e:
            logger.error("Error extracting company from %s: %s", company_url, e)

        return None

    # ------------------------------------------------------------------
    # Title parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_title_from_headline(headline: str) -> str:
        """
        Parse a job title from a LinkedIn headline.

        Headlines vary: "VP of Engineering at Procore Technologies",
        "CEO & Co-Founder, Acme Corp", "Senior Software Engineer | ML"
        """
        # Split on common delimiters — take the part before company
        for sep in [" at ", " @ "]:
            if sep in headline:
                return headline.split(sep)[0].strip()
        # If pipe or dash, might be "Title | Company" or "Title - Company"
        for sep in [" | ", " - "]:
            if sep in headline:
                candidate = headline.split(sep)[0].strip()
                if candidate:
                    return candidate
        return headline.strip()

    @staticmethod
    def _parse_title_from_page_title(page_title: str) -> str | None:
        """
        Parse title from page <title> tag.

        Format: "Name - Title - Company | LinkedIn" (3+ parts)
        or: "Name - Title | LinkedIn" (2 parts)
        """
        raw = page_title.split(" | ")[0].strip()
        parts = [p.strip() for p in raw.split(" - ")]
        if len(parts) >= 3:
            title = " - ".join(parts[1:-1])
            if title.lower() not in ("linkedin", ""):
                return title
        elif len(parts) == 2:
            candidate = parts[1]
            if candidate.lower() not in ("linkedin", ""):
                return candidate
        return None
