"""
Main views for CYOA game server - streamlined version.
Uses modular utilities for clarity.
"""
import json
import time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .config_utils import get_active_configuration, apply_pacing_template
from .message_processor import process_messages
from .difficulty_utils import calculate_turn_number, should_trigger_death, prepare_death_scene_messages
from .base_mode import handle_base_mode
from .moderated_mode import handle_moderated_mode
from .models import ResponseCache, GameSession


def get_active_game_ending_prompt():
    """Get the active game-ending prompt from database."""
    from .models import Prompt
    prompt = Prompt.objects.filter(prompt_type='game-ending', is_active=True).first()
    if prompt:
        return prompt.prompt_text
    # Fallback
    from .file_utils import load_prompt_file
    return load_prompt_file('game-ending-prompt.txt')


@csrf_exempt
@require_http_methods(["POST"])
def chat_completions(request):
    """
    OpenAI-compatible chat completions endpoint.
    
    Supported models:
    - 'gameserver-cyoa': Production mode (storyteller + judge combined)
    - 'gameserver-cyoa-base': Base mode (storyteller only, for testing)
    - 'gameserver-cyoa-test': Test mode (hardcoded response)
    """
    try:
        body = json.loads(request.body)
        model_name = body.get("model", "")
        
        # DEBUG: Log request details
        print("\n" + "="*60)
        print("[DEBUG] OpenWebUI Request Analysis")
        print("="*60)
        print(f"Headers: {dict(request.headers)}")
        print(f"Body keys: {body.keys()}")
        print(f"Model: {model_name}")
        print("="*60 + "\n")
        
        # Get active configuration
        config = get_active_configuration()
        if not config:
            return JsonResponse({
                "error": "No active configuration found. Please set up a configuration in the admin interface."
            }, status=500)
        
        # Process messages: filter, extract session, generate fingerprint
        messages = body.get("messages", [])
        filtered_messages, session_id, conversation_fingerprint = process_messages(messages)
        
        # Log configuration status
        if config.difficulty:
            print(f"[DIFFICULTY] Active difficulty: {config.difficulty.name}")
        else:
            print(f"[DIFFICULTY] No difficulty profile configured")
        
        # Get or create game session for turn tracking
        game_session = None
        use_game_ending_prompt = False
        turn_number = 0
        
        if session_id and config.difficulty:
            # Calculate turn number
            turn_number = calculate_turn_number(filtered_messages)
            
            # Get or create session
            game_session, created = GameSession.objects.get_or_create(
                session_id=session_id,
                defaults={
                    'configuration': config,
                    'max_turns': config.total_turns,
                    'turn_number': turn_number,
                    'conversation_fingerprint': conversation_fingerprint
                }
            )
            
            # Update turn number and fingerprint
            if not created:
                game_session.turn_number = turn_number
                if conversation_fingerprint and not game_session.conversation_fingerprint:
                    game_session.conversation_fingerprint = conversation_fingerprint
                game_session.save()
            
            print(f"[DIFFICULTY] Session {session_id[:8]}: Turn {turn_number}/{game_session.max_turns}, Game Over: {game_session.game_over}")
            
            # Check if death should trigger
            use_game_ending_prompt = should_trigger_death(
                turn_number, 
                game_session.max_turns, 
                config.difficulty, 
                game_session
            )
            
            if use_game_ending_prompt:
                game_session.game_over = True
                game_session.save()
        
        elif not session_id:
            print(f"[DIFFICULTY] ⚠ ⚠ ⚠  SKIPPING DIFFICULTY SYSTEM - NO SESSION ID ⚠ ⚠ ⚠")
        elif not config.difficulty:
            print(f"[DIFFICULTY] Difficulty system disabled (no difficulty profile configured)")
        
        # Determine system prompt
        if use_game_ending_prompt:
            # Use game-ending prompt
            if hasattr(config, 'game_ending_prompt') and config.game_ending_prompt:
                system_message = config.game_ending_prompt.prompt_text
            else:
                system_message = get_active_game_ending_prompt()
            
            print(f"[DIFFICULTY] ✓ REPLACED system prompt with game-ending prompt ({len(system_message)} chars)")
            print(f"[DIFFICULTY] Game-ending prompt preview: {system_message[:200]}...")
            
            # Replace conversation with death scene context
            filtered_messages = prepare_death_scene_messages(filtered_messages)
            
            # Log what we're sending to Claude
            print(f"[DIFFICULTY] ═══════════════════════════════════════════════════════════")
            print(f"[DIFFICULTY] DEATH TRIGGERED - SENDING TO CLAUDE:")
            print(f"[DIFFICULTY] ───────────────────────────────────────────────────────────")
            print(f"[DIFFICULTY] System prompt ({len(system_message)} chars):")
            print(f"[DIFFICULTY] {system_message}")
            print(f"[DIFFICULTY] ───────────────────────────────────────────────────────────")
            print(f"[DIFFICULTY] User message:")
            print(f"[DIFFICULTY] {filtered_messages[0]['content'][:500]}...")
            print(f"[DIFFICULTY] ═══════════════════════════════════════════════════════════")
        else:
            # Use normal adventure prompt with pacing template
            system_message = apply_pacing_template(
                config.adventure_prompt.prompt_text,
                config
            )
        
        # Route to appropriate handler based on model
        if "cyoa-test" in model_name:
            # Test mode: hardcoded response
            print("\n[TEST MODE] Returning hardcoded response (no API calls)")
            test_response = "If I were Claude Opus, this would have cost you a nickel."
            
            return JsonResponse({
                "id": f"test-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": test_response},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            })
        
        elif "cyoa-base" in model_name:
            # Base mode: storyteller only
            print(f"\n[DEBUG] BASE generating cache key from {len(filtered_messages)} messages")
            print(f"[DEBUG] Session ID at this point: {session_id}")
            cache_key = ResponseCache.generate_key(filtered_messages, system_message)
            print(f"[DEBUG] BASE cache key: {cache_key}")
            
            response, session_id = handle_base_mode(
                config, filtered_messages, system_message, cache_key,
                session_id, conversation_fingerprint, use_game_ending_prompt
            )
            return JsonResponse(response)
        
        else:
            # Moderated mode: storyteller + judge combined
            response, session_id = handle_moderated_mode(
                config, filtered_messages, system_message,
                session_id, conversation_fingerprint, use_game_ending_prompt
            )
            return JsonResponse(response)
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"\n[ERROR] Exception in chat_completions:")
        print(error_trace)
        
        return JsonResponse({
            "error": str(e),
            "trace": error_trace
        }, status=500)
