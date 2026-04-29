from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "VoiceConnect API"
    APP_VERSION: str = "2.0.0"

    ANTHROPIC_API_KEY: str = ""
    MODEL_NAME: str = "claude-3-haiku-20240307"

    FIRESTORE_PROFILE_COLLECTION: str = "caller_profiles"
    FIRESTORE_FAILED_NOTIFICATION_COLLECTION: str = "failed_notifications"

    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_AGENT_ID: str = ""

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""

    FOLLOW_UP_COMPANY_NAME: str = "VoiceConnect"

    PLATFORM_CLIENT_ID: str = "platform"
    PLATFORM_CLIENT_NAME: str = "Bhuvi IT"
    PLATFORM_PHONE_NUMBER: str = ""
    PLATFORM_AGENT_ID: str = ""

    GMAIL_SENDER_EMAIL: str = ""
    GMAIL_APP_PASSWORD: str = ""

    TOOL_SECRET: str = ""
    PUBLIC_BASE_URL: str = ""

    DASHBOARD_USERNAME: str = "admin"
    DASHBOARD_PASSWORD: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    CORS_ORIGINS: str = "http://localhost:5173"

    DEFAULT_INACTIVITY_TIMEOUT_SECONDS: int = 28
    DEFAULT_MAX_CALL_DURATION_SECONDS: int = 300
    MIN_INACTIVITY_TIMEOUT_SECONDS: int = 15
    MAX_INACTIVITY_TIMEOUT_SECONDS: int = 60
    MIN_MAX_CALL_DURATION_SECONDS: int = 120
    MAX_MAX_CALL_DURATION_SECONDS: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
