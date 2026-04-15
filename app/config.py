from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "VoiceConnect API"
    APP_VERSION: str = "2.0.0"

    FIRESTORE_PROFILE_COLLECTION: str = "caller_profiles"
    FIRESTORE_FAILED_NOTIFICATION_COLLECTION: str = "failed_notifications"

    ELEVENLABS_API_KEY: str = ""

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    FOLLOW_UP_URL: str = ""
    FOLLOW_UP_COMPANY_NAME: str = "VoiceConnect"

    GMAIL_SENDER_EMAIL: str = ""
    GMAIL_APP_PASSWORD: str = ""

    DASHBOARD_USERNAME: str = "admin"
    DASHBOARD_PASSWORD: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
