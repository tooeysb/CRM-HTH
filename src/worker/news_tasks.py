"""
Celery tasks for the Company News Intelligence pipeline.

Daily schedule (via Celery Beat):
  5:00 AM UTC: run_news_pipeline -- scrape, analyze, generate drafts
"""

from src.core.database import WorkerSessionLocal as SessionLocal
from src.core.logging import get_logger
from src.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, name="scrape_company_news")
def scrape_company_news(self, user_id: str) -> dict:
    """Scrape all enabled company news pages + RSS feeds."""
    db = SessionLocal()
    try:
        from src.services.news.scraper import NewsScraperService

        scraper = NewsScraperService(db)
        try:
            company_stats = scraper.scrape_all_companies(user_id)
            rss_stats = scraper.scrape_rss_feeds(user_id)
        finally:
            scraper.close()

        return {"companies": company_stats, "rss": rss_stats}
    except Exception:
        logger.exception("scrape_company_news failed")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="analyze_news_items")
def analyze_news_items(self, user_id: str) -> dict:
    """Classify new articles with Claude Haiku."""
    db = SessionLocal()
    try:
        from src.services.news.analyzer import NewsAnalysisService

        analyzer = NewsAnalysisService(db)
        try:
            return analyzer.analyze_batch(user_id, limit=500)
        finally:
            analyzer.close()
    except Exception:
        logger.exception("analyze_news_items failed")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_draft_suggestions")
def generate_draft_suggestions(self, user_id: str) -> dict:
    """Generate email drafts for high-relevance news."""
    db = SessionLocal()
    try:
        from src.services.news.draft_generator import NewsDraftGeneratorService

        generator = NewsDraftGeneratorService(db)
        return generator.generate_all_pending(user_id)
    except Exception:
        logger.exception("generate_draft_suggestions failed")
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="run_news_pipeline")
def run_news_pipeline(self, user_id: str) -> dict:
    """Run the complete news intelligence pipeline sequentially."""
    logger.info("Starting news intelligence pipeline for user %s", user_id)

    scrape_result = scrape_company_news(user_id)
    logger.info("Scrape phase complete: %s", scrape_result)

    analyze_result = analyze_news_items(user_id)
    logger.info("Analysis phase complete: %s", analyze_result)

    draft_result = generate_draft_suggestions(user_id)
    logger.info("Draft generation complete: %s", draft_result)

    return {
        "scrape": scrape_result,
        "analysis": analyze_result,
        "drafts": draft_result,
    }
