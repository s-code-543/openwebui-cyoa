"""
Views for CYOA game server.
Implements dual-LLM approach: storyteller -> judge -> response
"""
import json
import time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .file_utils import load_prompt_file
from .anthropic_utils import call_anthropic
from .ollama_utils import call_ollama
from .cache_utils import response_cache
from .models import Prompt, AuditLog


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


def call_llm(messages, system_prompt=None, model="qwen3:30b"):
    """
    Universal LLM caller - routes to appropriate backend based on model name.
    
    Args:
        messages: List of message dicts
        system_prompt: Optional system prompt
        model: Model identifier (claude-*, gameserver-ollama/*, ollama/*, etc.)
    
    Returns:
        String response from the LLM
    """
    # Strip gameserver- prefix if present for routing logic
    routing_model = model
    if routing_model.startswith("gameserver-"):
        routing_model = routing_model[11:]
    
    if routing_model.startswith("ollama/") or routing_model in ["qwen3:30b", "mistral:22b"]:
        return call_ollama(messages, system_prompt, model)
    else:
        return call_anthropic(messages, system_prompt, model)


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
        
        # Extract system message and messages
        messages = body.get("messages", [])
        system_message = None
        filtered_messages = []
        
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                # Ignore messages from base speaker (comparison only, not context)
                if msg.get("speaker") == "base":
                    continue
                filtered_messages.append(msg)
        
        model_name = body.get("model", "")
        
        # Check for test mode
        if "cyoa-test" in model_name:
            print("\n[TEST MODE] Returning hardcoded response (no API calls)")
            test_response = load_prompt_file('test_prompt.txt')
            
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
            backend_model = body.get("backend_model", "qwen3:4b")
            
            print(f"\n{'='*60}")
            print(f"[BASE] Received system_message: {repr(system_message)}")
            print(f"[BASE] Received {len(filtered_messages)} filtered messages")
            
            # Generate cache key FIRST
            cache_key = response_cache.generate_key(filtered_messages, system_message)
            
            print(f"\n{'='*60}")
            print(f"[BASE] Unmodified Storyteller Mode")
            print(f"[BASE] Backend: {backend_model}")
            print(f"[BASE] Messages: {len(filtered_messages)}")
            print(f"[BASE] Cache Key: {cache_key}")
            print(f"{'='*60}")
            
            # Call storyteller
            print(f"\n[BASE] Calling storyteller...")
            story_turn = call_llm(
                messages=filtered_messages,
                system_prompt=system_message,
                model=backend_model
            )
            print(f"[BASE] ✓ Response: {len(story_turn)} chars")
            print(f"[BASE] Preview: {story_turn[:150]}...\n")
            
            # Cache the response for moderated mode to use
            response_cache.set(cache_key, story_turn)
            print(f"[BASE] ✓ Cached for moderated mode")
            print(f"{'='*60}\n")
            
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
            backend_model = body.get("backend_model", "qwen3:4b")
            
            print(f"\n{'='*60}")
            print(f"[MODERATED] Received system_message: {repr(system_message)}")
            print(f"[MODERATED] Received {len(filtered_messages)} filtered messages")
            
            # Generate cache key FIRST
            cache_key = response_cache.generate_key(filtered_messages, system_message)
            
            print(f"\n{'='*60}")
            print(f"[MODERATED] Judge-Only Mode")
            print(f"[MODERATED] Backend: {backend_model}")
            print(f"[MODERATED] Messages: {len(filtered_messages)}")
            print(f"[MODERATED] Cache Key: {cache_key}")
            print(f"{'='*60}")
            
            # Wait for base mode to populate cache
            print(f"\n[MODERATED] Waiting for base response (timeout: 30s)...")
            story_turn = response_cache.wait_for(cache_key, timeout=30.0)
            
            if story_turn is None:
                error_msg = "Timeout waiting for base response. Did you call cyoa-base first?"
                print(f"[MODERATED] ✗ ERROR: {error_msg}")
                return JsonResponse(
                    {"error": error_msg},
                    status=408  # Request Timeout
                )
            
            print(f"[MODERATED] ✓ Retrieved from cache: {len(story_turn)} chars")
            
            # Now call judge to moderate it
            print(f"\n[MODERATED] Calling judge...")
            print(f"[MODERATED] Story turn preview: {story_turn[:200]}...")
            judge_messages = [
                {
                    "role": "user",
                    "content": f"Review this story turn:\n\n{story_turn}\n\nNow output the final story turn (either as-is if acceptable, or corrected if needed):"
                }
            ]
            
            try:
                judge_prompt, active_prompt_obj = get_active_judge_prompt()
                print(f"[MODERATED] Judge prompt loaded: {len(judge_prompt)} chars")
                print(f"[MODERATED] Judge message content: {judge_messages[0]['content'][:300]}...")
                
                final_turn = call_llm(
                    messages=judge_messages,
                    system_prompt=judge_prompt,
                    model=backend_model
                )
                
                print(f"[MODERATED] ✓ Judge returned: {len(final_turn)} chars")
                
                if len(final_turn) == 0:
                    error_msg = f"CRITICAL ERROR: Judge returned empty response for {backend_model}"
                    print(f"[MODERATED] ✗ {error_msg}")
                    print(f"[MODERATED] Judge input was: {repr(judge_messages)}")
                    raise Exception(error_msg)
                    
                print(f"[MODERATED] Preview: {final_turn[:150]}...")
                
                # Log the correction to audit log
                was_modified = story_turn.strip() != final_turn.strip()
                AuditLog.objects.create(
                    original_text=story_turn,
                    refined_text=final_turn,
                    was_modified=was_modified,
                    prompt_used=active_prompt_obj
                )
                print(f"[MODERATED] ✓ Logged to audit (modified={was_modified})")
            except Exception as e:
                print(f"[MODERATED] ✗ JUDGE FAILURE: {e}")
                import traceback
                traceback.print_exc()
                return JsonResponse({
                    "error": "Judge LLM call failed",
                    "details": str(e),
                    "backend_model": backend_model,
                    "story_turn_length": len(story_turn)
                }, status=500)
            
            print(f"{'='*60}\n")
            
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
            
            # Determine which backend model to use
            # Default to qwen3:4b, but allow override
            backend_model = body.get("backend_model", "qwen3:4b")
            
            print(f"\n{'='*60}")
            print(f"CYOA Game Server - Production Mode")
            print(f"{'='*60}")
            print(f"Backend model: {backend_model}")
            print(f"Messages in conversation: {len(filtered_messages)}")
            if system_message:
                print(f"System prompt: {system_message[:100]}...")
            
            # Step 1: Call storyteller LLM
            print(f"\n[STEP 1] Calling storyteller ({backend_model})...")
            story_turn = call_llm(
                messages=filtered_messages,
                system_prompt=system_message,
                model=backend_model
            )
            print(f"Storyteller response length: {len(story_turn)} chars")
            print(f"Preview: {story_turn[:200]}...")
            
            # Step 2: Call judge LLM to validate/improve the story turn
            print(f"\n[STEP 2] Calling judge ({backend_model})...")
            judge_messages = [
                {
                    "role": "user",
                    "content": f"Review this story turn:\n\n{story_turn}\n\nNow output the final story turn (either as-is if acceptable, or corrected if needed):"
                }
            ]
            
            try:
                judge_prompt, active_prompt_obj = get_active_judge_prompt()
                print(f"[PRODUCTION] Judge prompt loaded: {len(judge_prompt)} chars")
                
                final_turn = call_llm(
                    messages=judge_messages,
                    system_prompt=judge_prompt,
                    model=backend_model
                )
                
                print(f"Judge response length: {len(final_turn)} chars")
                
                if len(final_turn) == 0:
                    error_msg = f"CRITICAL ERROR: Judge returned empty response for {backend_model}"
                    print(f"[PRODUCTION] ✗ {error_msg}")
                    raise Exception(error_msg)
                    
                print(f"Preview: {final_turn[:200]}...")
                
                # Log the correction to audit log
                was_modified = story_turn.strip() != final_turn.strip()
                AuditLog.objects.create(
                    original_text=story_turn,
                    refined_text=final_turn,
                    was_modified=was_modified,
                    prompt_used=active_prompt_obj
                )
                print(f"[PRODUCTION] ✓ Logged to audit (modified={was_modified})")
                
            except Exception as e:
                print(f"[PRODUCTION] ✗ JUDGE FAILURE: {e}")
                import traceback
                traceback.print_exc()
                return JsonResponse({
                    "error": "Judge LLM call failed in production mode",
                    "details": str(e),
                    "backend_model": backend_model,
                    "story_turn_length": len(story_turn)
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
        print(f"ERROR in chat_completions: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {"error": str(e)},
            status=500
        )
