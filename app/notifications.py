import base64
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from twilio.rest import Client

from app.config import settings

logger = logging.getLogger(__name__)
EMAIL_SUBJECT = f"{settings.FOLLOW_UP_COMPANY_NAME} - Resume Upload"


class NotificationError(RuntimeError):
    pass


def _resume_upload_link() -> str:
    link = settings.FOLLOW_UP_URL.strip()
    if not link:
        raise NotificationError("FOLLOW_UP_URL (resume upload link) is not configured.")
    return link


def _default_follow_up_body() -> str:
    return (
        f"Thanks for calling {settings.FOLLOW_UP_COMPANY_NAME}! "
        f"Please upload your resume here: {_resume_upload_link()}. "
        "Our team will be in touch soon."
    )


def _render_message_body(template: Optional[str]) -> str:
    if not template or not template.strip():
        return _default_follow_up_body()

    return (
        template.replace("{{resume_link}}", _resume_upload_link())
        .replace("{{company_name}}", settings.FOLLOW_UP_COMPANY_NAME)
        .strip()
    )


def _html_body() -> str:
    link = _resume_upload_link()
    return (
        f"<p>Thanks for calling <strong>{settings.FOLLOW_UP_COMPANY_NAME}</strong>!</p>"
        f'<p>Please upload your resume here: <a href="{link}">{link}</a>.</p>'
        "<p>Our team will be in touch soon.</p>"
    )


def send_whatsapp_followup(
    caller_number: str,
    from_number: Optional[str] = None,
    message_body: Optional[str] = None,
) -> None:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise NotificationError("Twilio credentials are not configured.")

    effective_from = from_number or settings.TWILIO_WHATSAPP_FROM
    if not effective_from:
        raise NotificationError("No WhatsApp/SMS from-number is configured.")

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=_render_message_body(message_body),
        from_=effective_from,
        to=f"whatsapp:{caller_number}",
    )


def _send_email_via_app_password(email_address: str) -> None:
    if not settings.GMAIL_SENDER_EMAIL or not settings.GMAIL_APP_PASSWORD:
        raise NotificationError("GMAIL_SENDER_EMAIL and GMAIL_APP_PASSWORD must be configured.")

    message = MIMEMultipart("alternative")
    message["to"] = email_address
    message["from"] = settings.GMAIL_SENDER_EMAIL
    message["subject"] = EMAIL_SUBJECT
    message.attach(MIMEText(_default_follow_up_body(), "plain"))
    message.attach(MIMEText(_html_body(), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(settings.GMAIL_SENDER_EMAIL, settings.GMAIL_APP_PASSWORD)
        smtp.sendmail(settings.GMAIL_SENDER_EMAIL, email_address, message.as_string())


def _send_email_via_oauth(
    email_address: str,
    from_email: str,
    refresh_token: str,
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

    message = MIMEMultipart("alternative")
    message["to"] = email_address
    message["from"] = from_email
    message["subject"] = EMAIL_SUBJECT
    message.attach(MIMEText(_default_follow_up_body(), "plain"))
    message.attach(MIMEText(_html_body(), "html"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_email_followup(
    email_address: str,
    *,
    gmail_refresh_token: Optional[str] = None,
    gmail_from_email: Optional[str] = None,
) -> None:
    if gmail_refresh_token and gmail_from_email:
        _send_email_via_oauth(email_address, gmail_from_email, gmail_refresh_token)
    else:
        _send_email_via_app_password(email_address)
