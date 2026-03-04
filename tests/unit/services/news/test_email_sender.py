"""Tests for the SMTP email sender."""

from unittest.mock import MagicMock, patch

from src.services.news.email_sender import DigestEmailSender


class TestDigestEmailSender:
    @patch("src.services.news.email_sender.get_settings")
    @patch("src.services.news.email_sender.smtplib.SMTP")
    def test_send_success(self, mock_smtp_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            digest_smtp_host="smtp.gmail.com",
            digest_smtp_port=587,
            digest_smtp_user="user@test.com",
            digest_smtp_password="app-password",
            digest_from_email="digest@test.com",
        )

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        sender = DigestEmailSender()
        result = sender.send("recipient@test.com", "Test Subject", "<h1>Hello</h1>")

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "app-password")
        mock_server.sendmail.assert_called_once()

        # Verify sendmail args
        call_args = mock_server.sendmail.call_args
        assert call_args[0][0] == "digest@test.com"
        assert call_args[0][1] == ["recipient@test.com"]
        # Message body should contain both plain and HTML parts
        msg_str = call_args[0][2]
        assert "Test Subject" in msg_str
        assert "<h1>Hello</h1>" in msg_str

    @patch("src.services.news.email_sender.get_settings")
    @patch("src.services.news.email_sender.smtplib.SMTP")
    def test_send_failure_returns_false(self, mock_smtp_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            digest_smtp_host="smtp.gmail.com",
            digest_smtp_port=587,
            digest_smtp_user="user@test.com",
            digest_smtp_password="app-password",
            digest_from_email="digest@test.com",
        )

        mock_smtp_cls.return_value.__enter__ = MagicMock(
            side_effect=ConnectionRefusedError("Connection refused")
        )
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        sender = DigestEmailSender()
        result = sender.send("recipient@test.com", "Subject", "<h1>Test</h1>")

        assert result is False

    @patch("src.services.news.email_sender.get_settings")
    def test_credentials_from_settings(self, mock_settings):
        mock_settings.return_value = MagicMock(
            digest_smtp_host="custom.smtp.com",
            digest_smtp_port=465,
            digest_smtp_user="custom@test.com",
            digest_smtp_password="secret",
            digest_from_email="from@test.com",
        )

        sender = DigestEmailSender()
        assert sender.host == "custom.smtp.com"
        assert sender.port == 465
        assert sender.user == "custom@test.com"
        assert sender.from_email == "from@test.com"
