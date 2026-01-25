"""
LLM router - routes requests to appropriate backend (Ollama, Anthropic, OpenAI, OpenRouter, etc).
"""
from django.db import models as django_models
from .anthropic_utils import call_anthropic
from .ollama_utils import call_ollama
from .openai_utils import call_openai
from .openrouter_utils import call_openrouter
from .models import LLMModel


def call_llm(messages, system_prompt=None, llm_model=None, timeout=30, disable_thinking=False):
    """
    Universal LLM caller - routes to appropriate backend using LLMModel instance.
    
    Args:
        messages: List of message dicts
        system_prompt: Optional system prompt
        llm_model: LLMModel instance (required) containing routing information
        timeout: Timeout in seconds for LLM calls (default: 30)
        disable_thinking: Disable chain-of-thought reasoning for Ollama models (default: False)
    
    Returns:
        String response from the LLM
    
    Raises:
        ValueError: If llm_model is not provided or routing fails
    """
    
    if not llm_model:
        raise ValueError("llm_model parameter is required for call_llm")
    
    if not isinstance(llm_model, LLMModel):
        raise ValueError(f"llm_model must be an LLMModel instance, got {type(llm_model)}")
    
    print(f"[CALL_LLM] Routing model: {llm_model.name} (provider: {llm_model.provider.provider_type})")
    
    # Get routing information from the model
    routing_info = llm_model.get_routing_info()
    
    if routing_info['type'] == 'ollama':
        # All Ollama calls use the same function with different base_url
        return call_ollama(
            messages, 
            system_prompt, 
            routing_info['model'],
            base_url=routing_info.get('base_url'),
            timeout=timeout,
            disable_thinking=disable_thinking
        )
    
    elif routing_info['type'] == 'anthropic':
        # External Anthropic
        return call_anthropic(
            messages,
            system_prompt,
            routing_info['model'],
            routing_info['api_key'],
            timeout=timeout
        )
    
    elif routing_info['type'] == 'openai':
        # OpenAI
        return call_openai(
            messages,
            system_prompt,
            routing_info['model'],
            routing_info['api_key'],
            timeout=timeout
        )
    
    elif routing_info['type'] == 'openrouter':
        # OpenRouter (OpenAI-compatible)
        return call_openrouter(
            messages,
            system_prompt,
            routing_info['model'],
            routing_info['api_key'],
            timeout=timeout
        )
    
    else:
        raise ValueError(f"Unknown routing type: {routing_info['type']}")
