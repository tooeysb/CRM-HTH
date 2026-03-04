"""
News page discovery service.

Discovers the news/press/insights page URL for each company by trying
common URL patterns against their domain.
"""

import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.models.company import Company

logger = get_logger(__name__)

# Common news page paths, ordered by likelihood for construction companies
COMMON_PATHS = [
    "/news",
    "/newsroom",
    "/press",
    "/press-releases",
    "/insights",
    "/media",
    "/blog",
    "/updates",
    "/about/news",
    "/about/press",
    "/about/newsroom",
    "/company/news",
    "/media-center",
    "/about-us/news",
    "/resources/news",
]

# Indicators that a page is a news listing (case-insensitive)
NEWS_INDICATORS = [
    "<article",
    "<time",
    'class="news',
    'class="post',
    'class="press',
    'class="article',
    'class="blog',
    "news-item",
    "press-release",
    "news-card",
    "article-card",
]


class NewsPageDiscoveryService:
    """Discovers news pages on company websites."""

    def __init__(self, db: Session):
        self.db = db
        self.client = httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CRM-NewsBot/1.0)"},
        )

    def close(self):
        self.client.close()

    def _is_news_page(self, html: str) -> bool:
        """Check if the HTML content looks like a news listing page."""
        html_lower = html.lower()
        matches = sum(1 for indicator in NEWS_INDICATORS if indicator in html_lower)
        # Require at least 2 indicators to avoid false positives
        return matches >= 2

    def discover_for_company(self, company: Company, dry_run: bool = False) -> str | None:
        """
        Try common URL paths for a company domain. Return first valid news page URL.
        """
        if not company.domain:
            return None

        base_url = f"https://{company.domain}"

        for path in COMMON_PATHS:
            url = base_url + path
            try:
                resp = self.client.get(url)
                if resp.status_code == 200 and self._is_news_page(resp.text):
                    logger.info("Discovered news page for %s: %s", company.name, url)
                    if not dry_run:
                        company.news_page_url = url
                        company.news_page_discovered_at = datetime.now(timezone.utc)
                    return url
            except httpx.HTTPError:
                continue

            # Be polite — short delay between attempts on same domain
            time.sleep(0.3)

        # No news page found
        logger.debug("No news page found for %s (%s)", company.name, company.domain)
        return None

    def discover_all(self, user_id: str, limit: int | None = None, dry_run: bool = False) -> dict:
        """
        Run discovery for all companies without a news_page_url.

        Returns stats dict: {total, discovered, failed, skipped}
        """
        query = (
            self.db.query(Company)
            .filter(
                Company.user_id == user_id,
                Company.domain.isnot(None),
                Company.domain != "",
                or_(Company.news_page_url.is_(None), Company.news_page_url == ""),
                Company.news_scrape_enabled.is_(True),
            )
            .order_by(Company.name)
        )

        if limit:
            query = query.limit(limit)

        companies = query.all()
        stats = {"total": len(companies), "discovered": 0, "failed": 0, "skipped": 0}

        for i, company in enumerate(companies):
            logger.info(
                "[%d/%d] Discovering news page for %s (%s)",
                i + 1,
                stats["total"],
                company.name,
                company.domain,
            )

            result = self.discover_for_company(company, dry_run=dry_run)
            if result:
                stats["discovered"] += 1
            else:
                stats["failed"] += 1
                if not dry_run:
                    company.news_scrape_enabled = False

            # Rate limit between companies
            time.sleep(1.0)

        if not dry_run:
            self.db.commit()

        logger.info("Discovery complete: %s", stats)
        return stats
