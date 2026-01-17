"""
LLM router - routes requests to appropriate backend (Ollama, Anthropic, etc).
"""
from django.db import models as django_models
from .anthropic_utils import call_anthropic
from .ollama_utils import call_ollama, get_ollama_models
from .external_ollama_utils import call_external_ollama
from .external_anthropic_utils import call_anthropic as call_anthropic_api
from .models import LLMModel


def call_llm(messages, system_prompt=None, model="qwen3:30b", timeout=30):
    """
    Universal LLM caller - routes to appropriate backend using database configuration.
    Replaces name-based routing with explicit LLMModel lookup.
    
    Args:
        messages: List of message dicts
        system_prompt: Optional system prompt
        model: Model name or identifier (looks up in LLMModel table)
        timeout: Timeout in seconds for LLM calls (default: 30)
    
    Returns:
        String response from the LLM
    
    Raises:
        ValueError: If model cannot be found or routed
    """
    print(f"[CALL_LLM] Looking up model: {model}")
    
    # Try to find model in database first
    try:
        llm_model = LLMModel.objects.filter(
            django_models.Q(name=model) | django_models.Q(model_identifier=model),
            is_available=True
        ).first()
        
        if llm_model:
            print(f"[CALL_LLM] Found model in database: {llm_model.name} ({llm_model.source})")
            routing_info = llm_model.get_routing_info()
            
            if routing_info['type'] == 'local_ollama':
                return call_ollama(
                    messages, 
                    system_prompt, 
                    routing_info['model'], 
                    timeout=timeout
                )
            
            elif routing_info['type'] == 'ollama':
                # External Ollama
                return call_external_ollama(
                    messages,
                    system_prompt,
                    routing_info['model'],
                    routing_info['base_url'],
                    timeout=timeout
                )
            
            elif routing_info['type'] == 'anthropic':
                # External Anthropic
                return call_anthropic_api(
                    messages,
                    system_prompt,
                    routing_info['model'],
                    routing_info['api_key'],
                    timeout=timeout
                )
            
            else:
                raise ValueError(f"Unknown routing type: {routing_info['type']}")
    
    except LLMModel.DoesNotExist:
        pass  # Fall through to legacy routing
    except Exception as e:
        print(f"[CALL_LLM] Database lookup error: {e}")
    
    # LEGACY FALLBACK: Try name-based routing for backwards compatibility
    # This supports existing configurations before migration to LLMModel
    print(f"[CALL_LLM] Model not in database, trying legacy routing...")
    
    # Route to Ollama if model has ollama/ prefix
    if model.startswith("ollama/"):
        return call_ollama(messages, system_prompt, model, timeout=timeout)
    
    # Check if model name pattern suggests Anthropic (legacy)
    if model.startswith("claude"):
        print(f"[CALL_LLM] WARNING: Using legacy Anthropic routing for {model}")
        print(f"[CALL_LLM] Please register this model in the database for proper routing")
        # For legacy support, try local anthropic_utils if it exists
        try:
            return call_anthropic(messages, system_prompt, model)
        except Exception as e:
            print(f"[CALL_LLM] Legacy Anthropic routing failed: {e}")
            raise ValueError(f"Model '{model}' not found in database and legacy routing failed")
    
    # Check if this model is available in local Ollama
    try:
        ollama_models = get_ollama_models()
        ollama_model_names = [m['name'] for m in ollama_models]
        
        # Route to Ollama if model name matches
        if model in ollama_model_names:
            return call_ollama(messages, system_prompt, model, timeout=timeout)
        else:
            # Check if it looks like an Ollama model
            if ":" in model or model.startswith(("qwen", "llama", "mistral", "gemma", "phi", "deepseek")):
                return call_ollama(messages, system_prompt, model, timeout=timeout)
    except Exception as e:
        # If we can't check Ollama, but model looks like an Ollama model, try Ollama anyway
        if ":" in model or model.startswith(("qwen", "llama", "mistral", "gemma", "phi", "deepseek", "ollama")):
            return call_ollama(messages, system_prompt, model, timeout=timeout)
    
    # Cannot route - raise error
    error_msg = f"Cannot route model '{model}' - not found in database or legacy patterns"
    print(f"[CALL_LLM] ✗ {error_msg}")
    raise ValueError(error_msg)
