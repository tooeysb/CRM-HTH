#!/usr/bin/env python3
"""
LinkedIn monitoring orchestrator — runs all monitoring tasks in sequence.

Combines tier computation, activity scraping, profile change detection,
and daily email digest into a single entry point for cron/launchd.

Usage:
    python -m scripts.enrichment.linkedin_monitor              # Full run
    python -m scripts.enrichment.linkedin_monitor --posts-only  # Activity scraping only
    python -m scripts.enrichment.linkedin_monitor --jobs-only   # Job/title checks only
    python -m scripts.enrichment.linkedin_monitor --tiers-only  # Recompute tiers only
    python -m scripts.enrichment.linkedin_monitor --digest-only # Send digest only
    python -m scripts.enrichment.linkedin_monitor --dry-run     # Preview all phases
    python -m scripts.enrichment.linkedin_monitor --no-digest   # Skip email digest
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from scripts.enrichment.browser import LinkedInBrowser  # noqa: E402
from scripts.enrichment.crm_client import CRMClient  # noqa: E402
from scripts.enrichment.human_behavior import (  # noqa: E402
    WorkSchedule,
    delay_between_profiles,
)
from scripts.enrichment.linkedin_enricher import recheck_contact  # noqa: E402
from scripts.enrichment.state import EnrichmentState  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")


def _send_digest(user_id: str, to_email: str, dry_run: bool) -> bool:
    """Build and send the LinkedIn daily digest email."""
    from src.core.database import SyncSessionLocal
    from src.services.linkedin.digest import build_daily_digest, render_digest_html
    from src.services.news.email_sender import DigestEmailSender

    db = SyncSessionLocal()
    try:
        data = build_daily_digest(db, user_id)
        if not data.has_content:
            logger.info("No LinkedIn activity for digest — skipping email")
            return False

        subject, html = render_digest_html(data)

        if dry_run:
            logger.info("[DRY RUN] Would send digest: %s", subject)
            logger.info(
                "  Posts: %d, Job changes: %d, Title changes: %d",
                len(data.new_posts),
                len(data.job_changes),
                len(data.title_changes),
            )
            return True

        sender = DigestEmailSender()
        return sender.send(to_email, subject, html)
    finally:
        db.close()


def _run_activity_scraping(
    crm: CRMClient,
    browser: LinkedInBrowser,
    schedule: WorkSchedule,
    state: EnrichmentState,
    *,
    check_hours: bool,
    use_pacing: bool,
    dry_run: bool,
    limit: int,
    shutdown_flag: list[bool],
) -> dict:
    """Scrape recent posts for contacts due for checking."""
    from scripts.enrichment.linkedin_activity_scraper import _post_to_api_dict

    stats = {"checked": 0, "new_posts": 0, "errors": 0}

    for tier in ("A", "B", "C"):
        if shutdown_flag[0]:
            break

        contacts = crm.get_needs_post_check(tier=tier)
        contacts = [c for c in contacts if not state.is_processed(c["id"])]
        logger.info("Activity scrape tier %s: %d contacts due", tier, len(contacts))

        if limit:
            remaining = max(0, limit - stats["checked"])
            contacts = contacts[:remaining]

        for contact in contacts:
            if shutdown_flag[0]:
                break
            if check_hours and not schedule.wait_for_work_hours():
                logger.info("Work day ended — stopping activity scrape")
                return stats

            if use_pacing and schedule.should_take_break():
                schedule.take_break()

            cid = contact["id"]
            name = contact.get("name", "Unknown")
            linkedin_url = contact["linkedin_url"]

            logger.info("Activity check: %s — %s", name, linkedin_url)

            try:
                posts = browser.extract_recent_activity(linkedin_url, max_posts=5)
                valid_posts = [p for p in posts if p.post_url] if posts else []

                if valid_posts and not dry_run:
                    api_posts = [_post_to_api_dict(p) for p in valid_posts]
                    result = crm.create_linkedin_posts(cid, api_posts)
                    stats["new_posts"] += result.get("created", 0)
                elif valid_posts:
                    logger.info("[DRY RUN] Would save %d posts for %s", len(valid_posts), name)

                if not dry_run:
                    crm.update_contact(cid, last_post_check_at=datetime.now(UTC).isoformat())

                state.mark_processed(cid)
                stats["checked"] += 1
            except Exception as e:
                logger.error("Error checking activity for %s: %s", name, e)
                state.mark_skipped(cid)
                stats["errors"] += 1

            state.save()
            if use_pacing:
                delay_between_profiles()

    return stats


def _run_profile_checks(
    crm: CRMClient,
    browser: LinkedInBrowser,
    schedule: WorkSchedule,
    state: EnrichmentState,
    *,
    check_hours: bool,
    use_pacing: bool,
    dry_run: bool,
    limit: int,
    shutdown_flag: list[bool],
) -> dict:
    """Check profiles for job/title changes."""
    from scripts.enrichment.crm_client import ContactToEnrich

    stats = {"checked": 0, "matches": 0, "company_changes": 0, "title_changes": 0, "errors": 0}

    for tier in ("A", "B", "C"):
        if shutdown_flag[0]:
            break

        contacts_raw = crm.get_needs_profile_check(tier=tier)
        logger.info("Profile check tier %s: %d contacts due", tier, len(contacts_raw))

        contacts = []
        for item in contacts_raw:
            item.setdefault("linkedin_url", None)
            item.setdefault("email_count", 0)
            c = ContactToEnrich.from_dict(item)
            if not state.is_processed(c.id) and c.linkedin_url:
                contacts.append(c)

        if limit:
            remaining = max(0, limit - stats["checked"])
            contacts = contacts[:remaining]

        for contact in contacts:
            if shutdown_flag[0]:
                break
            if check_hours and not schedule.wait_for_work_hours():
                logger.info("Work day ended — stopping profile checks")
                return stats

            if use_pacing and schedule.should_take_break():
                schedule.take_break()

            try:
                result = recheck_contact(contact, browser, crm, dry_run=dry_run)
                state.mark_processed(contact.id)
                stats["checked"] += 1

                if result == "match":
                    stats["matches"] += 1
                elif result == "company_changed":
                    stats["company_changes"] += 1
                elif result == "title_changed":
                    stats["title_changes"] += 1
            except Exception as e:
                logger.error("Error checking profile for %s: %s", contact.name, e)
                state.mark_skipped(contact.id)
                stats["errors"] += 1

            state.save()
            if use_pacing:
                delay_between_profiles()

    return stats


def main():
    parser = argparse.ArgumentParser(description="LinkedIn monitoring orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--limit", type=int, default=0, help="Max contacts per phase (0=all)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--proxy", action="store_true", help="Use rotating proxy")
    parser.add_argument("--no-schedule", action="store_true", help="Skip work schedule")
    parser.add_argument("--start-now", action="store_true", help="Skip initial wait, keep pacing")
    parser.add_argument("--no-digest", action="store_true", help="Skip email digest")
    # Phase selectors (default: run all)
    parser.add_argument("--tiers-only", action="store_true", help="Only recompute tiers")
    parser.add_argument("--posts-only", action="store_true", help="Only scrape activity")
    parser.add_argument("--jobs-only", action="store_true", help="Only check job/title changes")
    parser.add_argument("--digest-only", action="store_true", help="Only send digest")
    args = parser.parse_args()

    run_all = not any([args.tiers_only, args.posts_only, args.jobs_only, args.digest_only])
    run_tiers = run_all or args.tiers_only
    run_posts = run_all or args.posts_only
    run_jobs = run_all or args.jobs_only
    run_digest = (run_all or args.digest_only) and not args.no_digest

    logger.info(
        "LinkedIn Monitor starting (tiers=%s, posts=%s, jobs=%s, digest=%s, dry_run=%s)",
        run_tiers,
        run_posts,
        run_jobs,
        run_digest,
        args.dry_run,
    )

    # Graceful shutdown
    shutdown_flag = [False]

    def _signal_handler(signum, frame):
        logger.info("Shutdown requested (signal %d)", signum)
        shutdown_flag[0] = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key — set ENRICHMENT_API_KEY or SECRET_KEY")
        return

    # Phase 1: Recompute tiers
    if run_tiers and not shutdown_flag[0]:
        logger.info("=== Phase 1: Computing monitoring tiers ===")
        try:
            from src.core.database import SyncSessionLocal
            from src.models.user import User
            from src.services.enrichment.monitoring_tier import compute_tiers_for_user

            db = SyncSessionLocal()
            try:
                user = db.query(User).first()
                if user:
                    counts = compute_tiers_for_user(db, user.id, dry_run=args.dry_run)
                    logger.info(
                        "Tiers: A=%d, B=%d, C=%d (manual=%d)",
                        counts["A"],
                        counts["B"],
                        counts["C"],
                        counts["skipped_manual"],
                    )
                else:
                    logger.error("No user found for tier computation")
            finally:
                db.close()
        except Exception:
            logger.exception("Tier computation failed")

    # Phases 2-3 need browser
    needs_browser = (run_posts or run_jobs) and not shutdown_flag[0]
    browser = None
    crm = None

    if needs_browser:
        schedule = WorkSchedule()
        check_hours = not args.no_schedule and not args.start_now
        use_pacing = not args.no_schedule

        if check_hours:
            if not schedule.wait_for_work_hours():
                logger.info("Past work hours — skipping browser phases")
                needs_browser = False

    if needs_browser:
        browser = LinkedInBrowser(headless=args.headless, proxy=args.proxy)
        crm = CRMClient(base_url=API_BASE, api_key=api_key)
        state = EnrichmentState.load()
        state.reset_if_new_day()

        try:
            browser.start()

            # Phase 2: Activity scraping
            if run_posts and not shutdown_flag[0]:
                logger.info("=== Phase 2: Activity scraping ===")
                post_stats = _run_activity_scraping(
                    crm,
                    browser,
                    schedule,
                    state,
                    check_hours=check_hours,
                    use_pacing=use_pacing,
                    dry_run=args.dry_run,
                    limit=args.limit,
                    shutdown_flag=shutdown_flag,
                )
                logger.info(
                    "Activity scraping: %d checked, %d new posts, %d errors",
                    post_stats["checked"],
                    post_stats["new_posts"],
                    post_stats["errors"],
                )

            # Phase 3: Profile/job/title change checks
            if run_jobs and not shutdown_flag[0]:
                logger.info("=== Phase 3: Profile change detection ===")
                profile_stats = _run_profile_checks(
                    crm,
                    browser,
                    schedule,
                    state,
                    check_hours=check_hours,
                    use_pacing=use_pacing,
                    dry_run=args.dry_run,
                    limit=args.limit,
                    shutdown_flag=shutdown_flag,
                )
                logger.info(
                    "Profile checks: %d checked, %d matches, %d company changes, "
                    "%d title changes, %d errors",
                    profile_stats["checked"],
                    profile_stats["matches"],
                    profile_stats["company_changes"],
                    profile_stats["title_changes"],
                    profile_stats["errors"],
                )

        finally:
            browser.stop()
            crm.close()
            state.save()

    # Phase 4: Daily digest email
    if run_digest and not shutdown_flag[0]:
        logger.info("=== Phase 4: Daily digest ===")
        try:
            from src.core.database import SyncSessionLocal
            from src.models.user import User

            db = SyncSessionLocal()
            try:
                user = db.query(User).first()
                if user:
                    to_email = os.environ.get("DIGEST_TO_EMAIL", user.email or "tooey@procore.com")
                    sent = _send_digest(str(user.id), to_email, args.dry_run)
                    if sent:
                        logger.info("Digest sent to %s", to_email)
                    else:
                        logger.info("No digest content or send skipped")
                else:
                    logger.error("No user found for digest")
            finally:
                db.close()
        except Exception:
            logger.exception("Digest failed")

    logger.info("LinkedIn Monitor complete")


if __name__ == "__main__":
    main()
