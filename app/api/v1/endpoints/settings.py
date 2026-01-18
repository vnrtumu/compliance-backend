"""
Settings API Endpoint

Provides endpoints for system configuration, including LLM provider settings.
"""

from fastapi import APIRouter
from app.schemas.settings import LLMSettings, LLMSettingsUpdate
from app.services.llm_client import get_provider_info, set_llm_provider, get_current_provider, get_model_name


router = APIRouter()


@router.get("/llm", response_model=LLMSettings)
async def get_llm_settings():
    """
    Get current LLM provider configuration.
    """
    info = get_provider_info()
    return LLMSettings(**info)


@router.post("/llm", response_model=LLMSettings)
async def update_llm_settings(settings_update: LLMSettingsUpdate):
    """
    Update LLM provider configuration.
    """
    provider = settings_update.provider.lower()
    
    # Validate and set provider
    set_llm_provider(provider)
    
    # Return updated settings
    return LLMSettings(
        provider=get_current_provider(),
        model=get_model_name(),
        available_providers=["openai", "groq", "deepseek", "grok"]
    )
