import base64
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    pass


def _compose_message(
    *,
    to_email: str,
    from_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> MIMEMultipart:
    message = MIMEMultipart("alternative")
    message["to"] = to_email
    message["from"] = from_email
    message["subject"] = subject
    message.attach(MIMEText(body_text, "plain"))
    if body_html:
        message.attach(MIMEText(body_html, "html"))
    return message


def _send_email_via_app_password(
    email_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> None:
    if not settings.GMAIL_SENDER_EMAIL or not settings.GMAIL_APP_PASSWORD:
        raise NotificationError("GMAIL_SENDER_EMAIL and GMAIL_APP_PASSWORD must be configured.")

    message = _compose_message(
        to_email=email_address,
        from_email=settings.GMAIL_SENDER_EMAIL,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(settings.GMAIL_SENDER_EMAIL, settings.GMAIL_APP_PASSWORD)
        smtp.sendmail(settings.GMAIL_SENDER_EMAIL, email_address, message.as_string())


def _send_email_via_oauth(
    email_address: str,
    from_email: str,
    refresh_token: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise NotificationError("Google OAuth credentials are not configured.")

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    message = _compose_message(
        to_email=email_address,
        from_email=from_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_email(
    email_address: str,
    *,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    gmail_refresh_token: Optional[str] = None,
    gmail_from_email: Optional[str] = None,
) -> None:
    """Send email via client Gmail OAuth (if credentials provided) or platform fallback."""
    if gmail_refresh_token and gmail_from_email:
        _send_email_via_oauth(
            email_address,
            gmail_from_email,
            gmail_refresh_token,
            subject,
            body_text,
            body_html,
        )
    else:
        _send_email_via_app_password(email_address, subject, body_text, body_html)
