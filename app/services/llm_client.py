"""
LLM Client Factory

Provides a unified interface for different LLM providers.
Supports OpenAI, GROQ, DeepSeek, and Grok.
"""

from openai import OpenAI
from typing import Optional, Dict, Any
from app.core.config import settings


# Global variable to store current LLM provider
_current_provider = settings.DEFAULT_LLM_PROVIDER


def set_llm_provider(provider: str):
    """Set the global LLM provider."""
    global _current_provider
    valid_providers = ["openai", "groq", "deepseek", "grok"]
    if provider.lower() not in valid_providers:
        raise ValueError(f"Invalid provider. Must be one of: {valid_providers}")
    _current_provider = provider.lower()


def get_current_provider() -> str:
    """Get the currently configured LLM provider."""
    return _current_provider


def get_llm_client(provider: Optional[str] = None) -> OpenAI:
    """
    Get an OpenAI-compatible client for the specified provider.
    
    Args:
        provider: LLM provider name (openai, groq, deepseek, grok).
                 If None, uses the globally configured provider.
    
    Returns:
        OpenAI client instance configured for the provider
    """
    if provider is None:
        provider = _current_provider
    
    provider = provider.lower()
    
    if provider == "openai":
        return OpenAI(api_key=settings.OPENAI_API_KEY)
    
    elif provider == "groq":
        # GROQ uses OpenAI-compatible API
        return OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
    
    elif provider == "deepseek":
        # DeepSeek uses OpenAI-compatible API
        return OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
    
    elif provider == "grok":
        # Grok (xAI) uses OpenAI-compatible API
        return OpenAI(
            api_key=settings.GROK_API_KEY,
            base_url="https://api.x.ai/v1"
        )
    
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_model_name(provider: Optional[str] = None) -> str:
    """
    Get the appropriate model name for the provider.
    
    Args:
        provider: LLM provider name. If None, uses current provider.
    
    Returns:
        Model name string
    """
    if provider is None:
        provider = _current_provider
    
    provider = provider.lower()
    
    model_mapping = {
        "openai": "gpt-4o",
        "groq": "llama-3.3-70b-versatile",  # GROQ's fastest model
        "deepseek": "deepseek-chat",
        "grok": "grok-beta"
    }
    
    return model_mapping.get(provider, "gpt-4o")


def get_provider_info() -> Dict[str, Any]:
    """
    Get information about the current provider configuration.
    
    Returns:
        Dictionary with provider details
    """
    return {
        "provider": _current_provider,
        "model": get_model_name(_current_provider),
        "available_providers": ["openai", "groq", "deepseek", "grok"]
    }
