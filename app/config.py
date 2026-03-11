# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    MODEL_NAME: str = "claude-3-haiku-20240307"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    
    # Available job locations (sourced from knowledge base)
    # Used for location matching logic
    JOB_LOCATIONS: list = ["Schaumburg, IL"]  # Add more as jobs are added in other cities
    
    class Config:
        env_file = ".env"
        extra = "ignore"

# Create a global instance
settings = Settings()