"""
SMTP email sender for digest delivery.

Uses Gmail SMTP with app passwords (STARTTLS on port 587).
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


class DigestEmailSender:
    """Sends HTML emails via SMTP."""

    def __init__(self):
        settings = get_settings()
        self.host = settings.digest_smtp_host
        self.port = settings.digest_smtp_port
        self.user = settings.digest_smtp_user
        self.password = settings.digest_smtp_password
        self.from_email = settings.digest_from_email

    def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send an email. Returns True on success."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email

        # Plain-text fallback
        plain = (
            f"{subject}\n\n"
            "This email is best viewed in an HTML-capable email client.\n"
            "View your CRM dashboard for the full digest."
        )
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.from_email, [to_email], msg.as_string())
            logger.info("Digest email sent to %s: %s", to_email, subject)
            return True
        except Exception:
            logger.exception("Failed to send digest email")
            return False
