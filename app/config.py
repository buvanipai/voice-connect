# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    MODEL_NAME: str = "claude-3-haiku-20240307"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

# Create a global instance
settings = Settings()