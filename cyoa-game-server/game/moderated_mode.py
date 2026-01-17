"""
Moderated mode handler (gameserver-cyoa).
Combined storyteller + judge in single request.
"""
from .llm_router import call_llm
from .models import AuditLog
from .session_utils import generate_session_id, inject_session_id_marker
from .config_utils import apply_pacing_template


def handle_moderated_mode(config, filtered_messages, system_message, session_id, 
                           conversation_fingerprint, use_game_ending_prompt):
    """
    Handle gameserver-cyoa mode: storyteller + judge combined.
    
    Args:
        config: Configuration instance
        filtered_messages: Processed conversation messages
        system_message: System prompt for storyteller
        session_id: Session ID (may be None on turn 1)
        conversation_fingerprint: Fingerprint for session lookup
        use_game_ending_prompt: Whether death was triggered
    
    Returns:
        Tuple of (response_dict, session_id)
    """
    print(f"\n[MODERATED MODE] Processing gameserver-cyoa request")
    
    print(f"\n{'='*60}")
    print(f"CYOA Game Server - Moderated Mode")
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
    
    # Skip judge if using game-ending prompt (death already determined)
    if use_game_ending_prompt:
        print(f"\n[STEP 2] SKIPPING judge (death scene already finalized)")
        final_turn = story_turn
        
        # Still log it to audit
        AuditLog.objects.create(
            original_text=story_turn,
            refined_text=story_turn,
            was_modified=False,
            prompt_used=config.judge_prompt
        )
    else:
        # Step 2: Call judge LLM to validate/improve the story turn
        print(f"\n[STEP 2] Calling judge ({config.judge_model})...")
        
        # Build judge messages with full conversation history for context
        judge_messages = filtered_messages.copy()
        judge_messages.append({
            "role": "assistant",
            "content": story_turn
        })
        judge_messages.append({
            "role": "user",
            "content": "Now review the conversation above, especially the most recent story turn. Output the final story turn (either as-is if acceptable, or corrected if needed):"
        })
        
        try:
            judge_prompt = config.judge_prompt.prompt_text
            print(f"[MODERATED] Judge prompt loaded: {len(judge_prompt)} chars")
            
            final_turn = call_llm(
                messages=judge_messages,
                system_prompt=judge_prompt,
                model=config.judge_model
            )
            
            print(f"Judge response length: {len(final_turn)} chars")
            
            if len(final_turn) == 0:
                error_msg = f"CRITICAL ERROR: Judge returned empty response for {config.judge_model}"
                print(f"\n{error_msg}")
                print("Falling back to original storyteller response\n")
                final_turn = story_turn
            
            # Log the correction to audit log
            was_modified = story_turn.strip() != final_turn.strip()
            AuditLog.objects.create(
                original_text=story_turn,
                refined_text=final_turn,
                was_modified=was_modified,
                prompt_used=config.judge_prompt
            )
            
            if was_modified:
                print(f"\n[JUDGE] ✓ Modified the story turn")
            else:
                print(f"\n[JUDGE] ✓ Approved story turn as-is")
        
        except Exception as e:
            error_details = str(e)
            print(f"\n[JUDGE] ✗ FAILED: {error_details}")
            print("Falling back to original storyteller response\n")
            final_turn = story_turn
            
            # Still log it
            AuditLog.objects.create(
                original_text=story_turn,
                refined_text=story_turn,
                was_modified=False,
                prompt_used=config.judge_prompt
            )
    
    # Generate session ID if this is turn 1
    if session_id is None and len(filtered_messages) == 1:
        session_id = generate_session_id(filtered_messages)
        final_turn = inject_session_id_marker(final_turn, session_id)
        print(f"[SESSION] ✓ Generated and injected session ID: {session_id}")
        
        # Store in database with fingerprint for future lookup
        if conversation_fingerprint:
            from .models import GameSession
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
        "model": "gameserver-cyoa",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": final_turn
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
