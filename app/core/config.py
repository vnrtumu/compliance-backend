from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Compliance Backend"
    API_V1_STR: str = "/api/v1"
    
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "compliance_db"
    DATABASE_URL: Optional[str] = None
    ExternalDatabaseURL: Optional[str] = None
    InternalDatabaseURL: Optional[str] = None
    UPLOAD_DIR: str = "uploads"
    OPENAI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    GROK_API_KEY: Optional[str] = None
    
    # LLM Configuration
    DEFAULT_LLM_PROVIDER: str = "groq"  # Options: openai, groq, deepseek, grok
    
    # Mock GST Server
    GST_SERVER_URL: str = "http://localhost:8080"

    @property
    def sync_database_url(self) -> str:
        if self.ExternalDatabaseURL:
            return self.ExternalDatabaseURL
        if self.InternalDatabaseURL:
            return self.InternalDatabaseURL
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
