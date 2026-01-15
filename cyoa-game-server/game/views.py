"""
Views for CYOA game server.
Implements dual-LLM approach: storyteller -> judge -> response
"""
import json
import time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import models
from .file_utils import load_prompt_file
from .anthropic_utils import call_anthropic
from .ollama_utils import call_ollama
from .external_ollama_utils import call_external_ollama
from .external_anthropic_utils import call_anthropic as call_anthropic_api
from .models import Prompt, AuditLog, Configuration, ResponseCache, LLMModel


def get_active_configuration():
    """
    Retrieve the active configuration from database.
    
    Returns:
        Configuration instance or None
    """
    try:
        config = Configuration.objects.filter(is_active=True).first()
        if not config:
            print("[WARNING] No active configuration found in database")
        return config
    except Exception as e:
        print(f"[ERROR] Failed to load configuration from database: {e}")
        return None


def apply_pacing_template(prompt_text, config):
    """
    Replace template variables in prompt text with values from configuration.
    
    Args:
        prompt_text: The prompt text containing template variables
        config: Configuration instance with pacing values
    
    Returns:
        String with template variables replaced
    """
    if not config:
        return prompt_text
    
    pacing = config.get_pacing_dict()
    result = prompt_text
    
    for key, value in pacing.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value))
    
    return result


def get_active_judge_prompt():
    """
    Retrieve the active judge prompt from database.
    Falls back to file if no active prompt exists.
    
    Returns:
        Tuple of (prompt_text, prompt_instance)
    """
    try:
        prompt = Prompt.objects.filter(prompt_type='judge', is_active=True).first()
        if prompt:
            return prompt.prompt_text, prompt
        else:
            # Fallback to file if no active prompt (should only happen before migration)
            print("[WARNING] No active judge prompt in database, falling back to file")
            return load_prompt_file('judge_prompt.txt'), None
    except Exception as e:
        print(f"[ERROR] Failed to load judge prompt from database: {e}")
        return load_prompt_file('judge_prompt.txt'), None


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
            models.Q(name=model) | models.Q(model_identifier=model),
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
    
    from .ollama_utils import get_ollama_models
    
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


@csrf_exempt
@require_http_methods(["POST"])
def chat_completions(request):
    """
    OpenAI-compatible chat completions endpoint.
    Implements dual-LLM logic: storyteller -> judge -> response
    
    Special modes:
    - 'cyoa-test': Hardcoded response (no API calls)
    - 'cyoa-base': Unmodified storyteller output only (for comparison)
    - 'cyoa-moderated': Waits for base output, then judges it (for comparison)
    - 'cyoa-dual-claude': Normal flow (storyteller -> judge -> return)
    """
    try:
        body = json.loads(request.body)
        
        # Get active configuration
        config = get_active_configuration()
        if not config:
            return JsonResponse({
                "error": "No active configuration found. Please set up a configuration in the admin interface."
            }, status=500)
        
        # Extract messages (ignore system message from OpenWebUI, use config's adventure prompt)
        messages = body.get("messages", [])
        filtered_messages = []
        
        for msg in messages:
            if msg.get("role") == "system":
                # Ignore system messages from OpenWebUI
                continue
            else:
                # Ignore messages from base speaker (comparison only, not context)
                if msg.get("speaker") == "base":
                    continue
                filtered_messages.append(msg)
        
        # Use adventure prompt from active configuration and apply pacing template
        system_message = apply_pacing_template(
            config.adventure_prompt.prompt_text,
            config
        )
        
        model_name = body.get("model", "")
        
        # Check for test mode
        if "cyoa-test" in model_name:
            print("\n[TEST MODE] Returning hardcoded response (no API calls)")
            test_response = "If I were Claude Opus, this would have cost you a nickel."
            
            return JsonResponse({
                "id": f"test-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": test_response,
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            })
        
        # Check for BASE mode (unmodified storyteller output)
        if "cyoa-base" in model_name:
            backend_model = config.storyteller_model
            cache_key = ResponseCache.generate_key(filtered_messages, system_message)
            
            # Check Ollama status if using Ollama
            if ":" in backend_model or backend_model.startswith(("qwen", "llama", "mistral", "gemma", "phi", "deepseek")):
                from .ollama_utils import check_ollama_status
                status = check_ollama_status()
                if not status["available"]:
                    print(f"[BASE] WARNING: Ollama not responding, request will likely fail")
                elif status["loaded_models"] and backend_model not in status["loaded_models"]:
                    print(f"[BASE] WARNING: {backend_model} not loaded, first request may be slower")
            
            print(f"\n[BASE] Storyteller: {backend_model} | Timeout: {config.storyteller_timeout}s")
            
            # Call storyteller
            storyteller_timeout = config.storyteller_timeout if config else 30
            story_turn = call_llm(
                messages=filtered_messages,
                system_prompt=system_message,
                model=backend_model,
                timeout=storyteller_timeout
            )
            print(f"[BASE] ✓ Got {len(story_turn)} chars, cached for moderated mode\n")
            
            # Cache the response in database for moderated mode to use
            ResponseCache.set_response(cache_key, story_turn)
            
            return JsonResponse({
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": story_turn,
                            "speaker": "base"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            })
        
        # Check for MODERATED mode (wait for base, then judge)
        if "cyoa-moderated" in model_name:
            cache_key = ResponseCache.generate_key(filtered_messages, system_message)
            
            print(f"\n[MODERATED] Judge: {config.judge_model} | Timeout: {config.judge_timeout}s")
            
            # Wait for base mode to populate cache (database-backed)
            judge_timeout = config.judge_timeout if config else 30
            print(f"[MODERATED] Waiting for base response (cache key: {cache_key})...")
            story_turn = ResponseCache.wait_for_response(cache_key, timeout=float(judge_timeout))
            
            if story_turn is None:
                error_msg = f"Timeout ({judge_timeout}s) waiting for base response. Ensure cyoa-base is called first."
                print(f"[MODERATED] ✗ ERROR: {error_msg}")
                return JsonResponse(
                    {"error": error_msg, "cache_key": cache_key},
                    status=408  # Request Timeout
                )
            
            print(f"[MODERATED] ✓ Got base response ({len(story_turn)} chars), calling judge...")
            judge_messages = [
                {
                    "role": "user",
                    "content": f"Review this story turn:\n\n{story_turn}\n\nNow output the final story turn (either as-is if acceptable, or corrected if needed):"
                }
            ]
            
            try:
                judge_prompt = config.judge_prompt.prompt_text
                judge_timeout_llm = config.judge_timeout if config else 30
                
                final_turn = call_llm(
                    messages=judge_messages,
                    system_prompt=judge_prompt,
                    model=config.judge_model,
                    timeout=judge_timeout_llm
                )
                
                if len(final_turn) == 0:
                    raise Exception(f"Judge {config.judge_model} returned empty response")
                
                # Log the correction to audit log
                was_modified = story_turn.strip() != final_turn.strip()
                AuditLog.objects.create(
                    original_text=story_turn,
                    refined_text=final_turn,
                    was_modified=was_modified,
                    prompt_used=config.judge_prompt
                )
                print(f"[MODERATED] ✓ Judge returned {len(final_turn)} chars (modified={was_modified})\n")
            except Exception as e:
                error_details = str(e)
                print(f"[MODERATED] ✗ JUDGE FAILED: {error_details}\n")
                
                # If timeout, just pass through the story without judgment
                if "timeout" in error_details.lower() or "timed out" in error_details.lower():
                    print(f"[MODERATED] → Timeout detected, passing through original story\n")
                    final_turn = story_turn
                    
                    # Still log it, but mark as passed through
                    AuditLog.objects.create(
                        original_text=story_turn,
                        refined_text=story_turn,
                        was_modified=False,
                        prompt_used=config.judge_prompt
                    )
                else:
                    # Non-timeout errors should still fail
                    return JsonResponse({
                        "error": f"Judge failed: {error_details}",
                        "judge_model": config.judge_model,
                    }, status=500)
            
            return JsonResponse({
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": final_turn,
                            "speaker": "moderated"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            })
        
        # Production mode: gameserver-cyoa
        # This mode combines both LLM calls in a single request (no cache needed)
        if model_name == "gameserver-cyoa":
            print(f"\n[PRODUCTION MODE] Processing gameserver-cyoa request")
            
            print(f"\n{'='*60}")
            print(f"CYOA Game Server - Production Mode")
            print(f"{'='*60}")
            print(f"Adventure: {config.adventure_prompt.description}")
            print(f"Storyteller: {config.storyteller_model}")
            print(f"Judge: {config.judge_model}")
            print(f"Messages in conversation: {len(filtered_messages)}")
            
            # Step 1: Call storyteller LLM
            print(f"\n[STEP 1] Calling storyteller ({config.storyteller_model})...")
            story_turn = call_llm(
                messages=filtered_messages,
                system_prompt=system_message,
                model=config.storyteller_model
            )
            print(f"Storyteller response length: {len(story_turn)} chars")
            print(f"Preview: {story_turn[:200]}...")
            
            # Step 2: Call judge LLM to validate/improve the story turn
            print(f"\n[STEP 2] Calling judge ({config.judge_model})...")
            judge_messages = [
                {
                    "role": "user",
                    "content": f"Review this story turn:\n\n{story_turn}\n\nNow output the final story turn (either as-is if acceptable, or corrected if needed):"
                }
            ]
            
            try:
                judge_prompt = config.judge_prompt.prompt_text
                print(f"[PRODUCTION] Judge prompt loaded: {len(judge_prompt)} chars")
                
                final_turn = call_llm(
                    messages=judge_messages,
                    system_prompt=judge_prompt,
                    model=config.judge_model
                )
                
                print(f"Judge response length: {len(final_turn)} chars")
                
                if len(final_turn) == 0:
                    error_msg = f"CRITICAL ERROR: Judge returned empty response for {config.judge_model}"
                    print(f"[PRODUCTION] ✗ {error_msg}")
                    raise Exception(error_msg)
                    
                print(f"Preview: {final_turn[:200]}...")
                
                # Log the correction to audit log
                was_modified = story_turn.strip() != final_turn.strip()
                AuditLog.objects.create(
                    original_text=story_turn,
                    refined_text=final_turn,
                    was_modified=was_modified,
                    prompt_used=config.judge_prompt
                )
                print(f"[PRODUCTION] ✓ Logged to audit (modified={was_modified})")
                
            except Exception as e:
                error_msg = str(e)
                print(f"[PRODUCTION] ✗ JUDGE FAILURE: {error_msg}")
                
                # If timeout, pass through story
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    print(f"[PRODUCTION] → Timeout, using original story\n")
                    final_turn = story_turn
                else:
                    return JsonResponse({
                        "error": f"Judge failed: {error_msg}",
                        "backend_model": backend_model
                    }, status=500)
            
            # Step 3: Return OpenAI-compatible response with moderated output
            print(f"\n[STEP 3] Returning final moderated response to Open WebUI")
            print(f"{'='*60}\n")
            
            return JsonResponse({
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "gameserver-cyoa",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": final_turn,
                            "speaker": "moderated"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            })
        
        # Unknown model name - return helpful error
        return JsonResponse({
            "error": "Unknown model name",
            "message": f"Model '{model_name}' is not recognized. Available models:",
            "available_models": [
                {
                    "name": "gameserver-cyoa-test",
                    "description": "Simple echo test endpoint"
                },
                {
                    "name": "gameserver-cyoa-base",
                    "description": "Storyteller only (stores to cache for comparison)"
                },
                {
                    "name": "gameserver-cyoa-moderated",
                    "description": "Judge only (retrieves from cache and moderates)"
                },
                {
                    "name": "gameserver-cyoa",
                    "description": "Production: Combined storyteller + judge (single call, no cache)"
                }
            ],
            "hint": "Use gameserver-cyoa for production, or gameserver-cyoa-base + gameserver-cyoa-moderated for side-by-side comparison during judge tuning"
        }, status=400)
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in chat_completions: {error_msg}")
        return JsonResponse(
            {"error": error_msg},
            status=500
        )
