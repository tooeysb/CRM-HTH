"""
News scraping service.

Fetches news pages from company websites and RSS feeds,
parses article metadata, and stores new items in the database.
"""

import hashlib
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.models.company import Company
from src.models.company_news import CompanyNewsItem
from src.services.news.feeds import RSS_FEEDS
from src.services.news.parser import NewsPageParser

logger = get_logger(__name__)


class NewsScraperService:
    """Scrapes company news pages and RSS feeds for new articles."""

    def __init__(self, db: Session):
        self.db = db
        self.parser = NewsPageParser()
        self.client = httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CRM-NewsBot/1.0)"},
        )

    def close(self):
        self.client.close()

    def scrape_company(self, company: Company, user_id: str) -> list[dict]:
        """
        Fetch a company's news page and extract article metadata.
        Returns list of article dicts.
        """
        if not company.news_page_url:
            return []

        try:
            resp = self.client.get(company.news_page_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch %s: %s", company.news_page_url, e)
            return []

        # Check if content changed since last scrape
        html_hash = hashlib.sha256(resp.text.encode()).hexdigest()

        # Parse articles
        articles = self.parser.parse(resp.text, company.news_page_url)
        logger.debug("Parsed %d articles from %s", len(articles), company.name)

        # Store each article (dedup by unique constraint)
        new_count = 0
        for article in articles:
            if not article.get("url") or not article.get("title"):
                continue

            stmt = (
                pg_insert(CompanyNewsItem)
                .values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    company_id=company.id,
                    source_url=article["url"],
                    source_type="company_website",
                    title=article["title"][:500],
                    summary=article.get("snippet", "")[:2000] or None,
                    published_at=article.get("published_at"),
                    raw_html_hash=html_hash,
                    status="new",
                )
                .on_conflict_do_nothing(constraint="uq_company_news_source")
            )

            result = self.db.execute(stmt)
            if result.rowcount > 0:
                new_count += 1

        self.db.commit()
        return articles

    def scrape_all_companies(self, user_id: str) -> dict:
        """
        Scrape all enabled company news pages.
        Returns stats: {companies_scraped, new_items, errors}
        """
        companies = (
            self.db.query(Company)
            .filter(
                Company.user_id == user_id,
                Company.news_scrape_enabled.is_(True),
                Company.news_page_url.isnot(None),
            )
            .all()
        )

        stats = {"companies_scraped": 0, "new_items": 0, "errors": 0}

        for company in companies:
            try:
                articles = self.scrape_company(company, user_id)
                stats["companies_scraped"] += 1
                stats["new_items"] += len(articles)
            except Exception:
                logger.exception("Error scraping %s", company.name)
                stats["errors"] += 1

            time.sleep(1.0)  # Rate limit between companies

        logger.info("Company scraping complete: %s", stats)
        return stats

    def scrape_rss_feeds(self, user_id: str) -> dict:
        """
        Scrape supplementary RSS feeds and match articles to companies.
        Returns stats: {feeds_scraped, new_items, matched}
        """
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed, skipping RSS feeds")
            return {"feeds_scraped": 0, "new_items": 0, "matched": 0}

        # Load all company names and domains for matching
        companies = self.db.query(Company).filter(Company.user_id == user_id).all()

        # Build lookup: lowercase name/domain -> company
        company_lookup: dict[str, Company] = {}
        for c in companies:
            company_lookup[c.name.lower()] = c
            if c.domain:
                company_lookup[c.domain.lower()] = c
            if c.aliases:
                for alias in c.aliases:
                    company_lookup[alias.lower()] = c

        stats = {"feeds_scraped": 0, "new_items": 0, "matched": 0}

        for feed_config in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_config["url"])
                stats["feeds_scraped"] += 1
            except Exception:
                logger.exception("Failed to parse RSS feed: %s", feed_config["name"])
                continue

            for entry in feed.entries[:50]:  # Limit per feed
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "")
                published = entry.get("published", "")

                if not title or not link:
                    continue

                # Try to match to a company
                text_to_search = f"{title} {summary}".lower()
                matched_company = None
                for name, company in company_lookup.items():
                    if len(name) > 3 and name in text_to_search:
                        matched_company = company
                        break

                if not matched_company:
                    continue

                stats["matched"] += 1

                # Parse published date
                published_at = None
                if published:
                    try:
                        from dateutil import parser as dateutil_parser

                        published_at = dateutil_parser.parse(published)
                    except (ValueError, OverflowError):
                        pass

                stmt = (
                    pg_insert(CompanyNewsItem)
                    .values(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        company_id=matched_company.id,
                        source_url=link[:2048],
                        source_type=feed_config["source_type"],
                        title=title[:500],
                        summary=summary[:2000] or None,
                        published_at=published_at,
                        status="new",
                    )
                    .on_conflict_do_nothing(constraint="uq_company_news_source")
                )

                result = self.db.execute(stmt)
                if result.rowcount > 0:
                    stats["new_items"] += 1

            self.db.commit()

        logger.info("RSS scraping complete: %s", stats)
        return stats
