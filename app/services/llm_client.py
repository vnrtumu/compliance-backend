"""
LLM Client Factory

Provides a unified interface for different LLM providers using LangChain.
Supports OpenAI, GROQ, DeepSeek, and Grok.

Migration Note: This module now uses LangChain for LLM abstraction.
- get_chat_model() returns LangChain BaseChatModel instances
- get_llm_client() is kept for backward compatibility (returns OpenAI SDK)
"""

from openai import OpenAI
from typing import Optional, Dict, Any, Union
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq

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


def get_chat_model(
    provider: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: Optional[int] = None
) -> BaseChatModel:
    """
    Get a LangChain ChatModel for the specified provider.
    
    This is the primary method for getting LLM instances in the LangChain-based architecture.
    
    Args:
        provider: LLM provider name (openai, groq, deepseek, grok).
                 If None, uses the globally configured provider.
        temperature: Sampling temperature (default 0.1 for consistency)
        max_tokens: Maximum tokens in response (None = provider default)
    
    Returns:
        LangChain BaseChatModel instance configured for the provider
    """
    if provider is None:
        provider = _current_provider
    
    provider = provider.lower()
    model_name = get_model_name(provider)
    
    common_kwargs = {
        "temperature": temperature,
    }
    if max_tokens:
        common_kwargs["max_tokens"] = max_tokens
    
    if provider == "openai":
        return ChatOpenAI(
            model=model_name,
            api_key=settings.OPENAI_API_KEY,
            **common_kwargs
        )
    
    elif provider == "groq":
        return ChatGroq(
            model=model_name,
            api_key=settings.GROQ_API_KEY,
            **common_kwargs
        )
    
    elif provider == "deepseek":
        # DeepSeek uses OpenAI-compatible API
        return ChatOpenAI(
            model=model_name,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
            **common_kwargs
        )
    
    elif provider == "grok":
        # Grok (xAI) uses OpenAI-compatible API
        return ChatOpenAI(
            model=model_name,
            api_key=settings.GROK_API_KEY,
            base_url="https://api.x.ai/v1",
            **common_kwargs
        )
    
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_vision_model(
    temperature: float = 0.1,
    max_tokens: int = 4096
) -> ChatOpenAI:
    """
    Get a vision-capable ChatModel (GPT-4o).
    
    Vision capabilities are currently only available with OpenAI GPT-4o.
    
    Args:
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
    
    Returns:
        ChatOpenAI instance with vision capabilities
    """
    return ChatOpenAI(
        model="gpt-4o",
        api_key=settings.OPENAI_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens
    )


# ============ BACKWARD COMPATIBILITY ============
# The following functions maintain compatibility with existing code
# that uses the OpenAI SDK directly. Gradually migrate to get_chat_model().

def get_llm_client(provider: Optional[str] = None) -> OpenAI:
    """
    [DEPRECATED] Get an OpenAI-compatible client for the specified provider.
    
    Use get_chat_model() for new code.
    
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


def get_provider_info() -> Dict[str, Any]:
    """
    Get information about the current provider configuration.
    
    Returns:
        Dictionary with provider details
    """
    return {
        "provider": _current_provider,
        "model": get_model_name(_current_provider),
        "available_providers": ["openai", "groq", "deepseek", "grok"],
        "framework": "langchain"  # Indicates LangChain is now used
    }
