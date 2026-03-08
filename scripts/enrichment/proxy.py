"""
Rotating residential proxy support for LinkedIn scraping at scale.

Provider-agnostic: works with any proxy service that supports standard
HTTP/SOCKS5 proxy URLs (Bright Data, SmartProxy, Oxylabs, etc.).

Configuration via environment variables:
    PROXY_URL=http://user:pass@gate.smartproxy.com:10000
    PROXY_ROTATION=per_request    # or per_session

When PROXY_URL is not set, all connections go direct (current behavior).
"""

from __future__ import annotations

import os

from src.core.logging import get_logger

logger = get_logger(__name__)


class ProxyRotator:
    """Manages rotating residential proxy connections for Playwright."""

    def __init__(self):
        self.proxy_url: str | None = os.environ.get("PROXY_URL")
        self.rotation: str = os.environ.get("PROXY_ROTATION", "per_request")
        self._consecutive_failures: int = 0
        self._max_failures: int = 5
        self._disabled: bool = False

        if self.proxy_url:
            # Redact credentials in log
            safe = self.proxy_url.split("@")[-1] if "@" in self.proxy_url else self.proxy_url
            logger.info("Proxy configured: %s (rotation: %s)", safe, self.rotation)
        else:
            logger.info("No proxy configured — using direct connection")

    @property
    def enabled(self) -> bool:
        return bool(self.proxy_url) and not self._disabled

    def get_playwright_proxy(self) -> dict | None:
        """Return proxy config dict for Playwright's browser.launch(), or None."""
        if not self.enabled:
            return None
        return {"server": self.proxy_url}

    def record_success(self):
        """Record a successful proxy connection."""
        if self._consecutive_failures > 0:
            logger.info("Proxy connection restored after %d failures", self._consecutive_failures)
        self._consecutive_failures = 0

    def record_failure(self):
        """Record a proxy connection failure. Disables proxy after too many consecutive failures."""
        self._consecutive_failures += 1
        logger.warning("Proxy failure #%d/%d", self._consecutive_failures, self._max_failures)
        if self._consecutive_failures >= self._max_failures:
            self._disabled = True
            logger.error(
                "Proxy disabled after %d consecutive failures — falling back to direct connection",
                self._max_failures,
            )

    def reset(self):
        """Re-enable proxy (e.g., for a new session)."""
        self._disabled = False
        self._consecutive_failures = 0
