import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from twilio.rest import Client

from app.config import settings


class NotificationError(RuntimeError):
    pass


def _resume_upload_link() -> str:
    link = settings.FOLLOW_UP_URL.strip()
    if not link:
        raise NotificationError("FOLLOW_UP_URL (resume upload link) is not configured.")
    return link


def _plain_body() -> str:
    return (
        "Thanks for calling Bhuvi IT Solutions! "
        f"Please upload your resume here: {_resume_upload_link()}. "
        "Our team will be in touch soon."
    )


def _html_body() -> str:
    link = _resume_upload_link()
    return (
        "<p>Thanks for calling <strong>Bhuvi IT Solutions</strong>!</p>"
        f'<p>Please upload your resume here: <a href="{link}">{link}</a>.</p>'
        "<p>Our team will be in touch soon.</p>"
    )


def send_whatsapp_followup(caller_number: str) -> None:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise NotificationError("Twilio credentials are not configured.")
    if not settings.TWILIO_WHATSAPP_FROM:
        raise NotificationError("TWILIO_WHATSAPP_FROM is not configured.")

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=_plain_body(),
        from_=settings.TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{caller_number}",
    )


def send_email_followup(email_address: str) -> None:
    if not settings.GMAIL_SENDER_EMAIL or not settings.GMAIL_APP_PASSWORD:
        raise NotificationError("GMAIL_SENDER_EMAIL and GMAIL_APP_PASSWORD must be configured.")

    message = MIMEMultipart("alternative")
    message["to"] = email_address
    message["from"] = settings.GMAIL_SENDER_EMAIL
    message["subject"] = "Bhuvi IT Solutions — Resume Upload"
    message.attach(MIMEText(_plain_body(), "plain"))
    message.attach(MIMEText(_html_body(), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(settings.GMAIL_SENDER_EMAIL, settings.GMAIL_APP_PASSWORD)
        smtp.sendmail(settings.GMAIL_SENDER_EMAIL, email_address, message.as_string())
