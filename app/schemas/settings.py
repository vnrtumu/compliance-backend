"""
Settings API Schemas
"""

from pydantic import BaseModel
from typing import Optional


class LLMSettings(BaseModel):
    """LLM provider settings."""
    provider: str  # openai, groq, deepseek, grok
    model: str
    available_providers: list[str]


class LLMSettingsUpdate(BaseModel):
    """Request to update LLM provider."""
    provider: str
