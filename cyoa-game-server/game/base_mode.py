"""
Base mode handler (cyoa-base).
Storyteller only - generates story turns without judge moderation.
"""
from .llm_router import call_llm
from .models import ResponseCache, GameSession
from .session_utils import generate_session_id, inject_session_id_marker
from .config_utils import apply_pacing_template


def handle_base_mode(config, filtered_messages, system_message, cache_key, session_id, 
                     conversation_fingerprint, use_game_ending_prompt):
    """
    Handle cyoa-base mode: storyteller only with caching.
    
    Args:
        config: Configuration instance
        filtered_messages: Processed conversation messages
        system_message: System prompt for storyteller
        cache_key: Cache key for response storage
        session_id: Session ID (may be None on turn 1)
        conversation_fingerprint: Fingerprint for session lookup
        use_game_ending_prompt: Whether death was triggered
    
    Returns:
        Tuple of (response_dict, session_id)
    """
    backend_model = config.storyteller_model
    
    # Check Ollama status if using Ollama
    if ":" in backend_model or backend_model.startswith(("qwen", "llama", "mistral", "gemma", "phi", "deepseek")):
        from .ollama_utils import check_ollama_status
        status = check_ollama_status()
        if not status["available"]:
            print(f"[BASE] WARNING: Ollama not responding, request will likely fail")
        elif status["loaded_models"] and backend_model not in status["loaded_models"]:
            print(f"[BASE] WARNING: {backend_model} not loaded, first request may be slower")
    
    print(f"\n[BASE] Storyteller: {backend_model} | Timeout: {config.storyteller_timeout}s")
    print(f"[BASE] System prompt length: {len(system_message)} chars")
    print(f"[BASE] System prompt preview: {system_message[:200]}...")
    print(f"[BASE] Conversation messages: {len(filtered_messages)}")
    
    if len(filtered_messages) == 1:
        print(f"[BASE] ⚠️  FIRST MESSAGE: {filtered_messages[0].get('content', '')[:200]}")
    
    # Call storyteller
    storyteller_timeout = config.storyteller_timeout if config else 30
    story_turn = call_llm(
        messages=filtered_messages,
        system_prompt=system_message,
        model=backend_model,
        timeout=storyteller_timeout
    )
    print(f"[BASE] ✓ Got {len(story_turn)} chars, cached for moderated mode")
    
    # Log the full response if using game-ending prompt
    if use_game_ending_prompt:
        print(f"[DIFFICULTY] ═══════════════════════════════════════════════════════════")
        print(f"[DIFFICULTY] CLAUDE'S DEATH SCENE RESPONSE ({len(story_turn)} chars):")
        print(f"[DIFFICULTY] ───────────────────────────────────────────────────────────")
        print(f"[DIFFICULTY] {story_turn}")
        print(f"[DIFFICULTY] ═══════════════════════════════════════════════════════════")
    
    # Warn if response is suspiciously short (likely a refusal or error)
    if len(story_turn) < 100:
        print(f"[BASE] ⚠️  WARNING: Very short response ({len(story_turn)} chars)")
        print(f"[BASE] Full response: {repr(story_turn)}")
    
    print()  # Blank line for readability
    
    # Cache the response in database for moderated mode to use
    ResponseCache.set_response(cache_key, story_turn)
    
    # Generate session ID if this is turn 1
    if session_id is None and len(filtered_messages) == 1:
        session_id = generate_session_id(filtered_messages)
        story_turn = inject_session_id_marker(story_turn, session_id)
        print(f"[SESSION] ✓ Generated and injected session ID: {session_id}")
        
        # Store in database with fingerprint for future lookup
        if conversation_fingerprint:
            GameSession.objects.get_or_create(
                session_id=session_id,
                defaults={'conversation_fingerprint': conversation_fingerprint}
            )
    
    # Return OpenAI-compatible response
    import time
    response = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gameserver-cyoa-base",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": story_turn
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }
    
    return response, session_id
