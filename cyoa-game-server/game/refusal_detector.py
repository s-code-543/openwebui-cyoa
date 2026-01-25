"""
Refusal detection and correction system for CYOA game.

This module handles:
1. Detecting when the storyteller refuses to generate a valid turn
2. Stripping refusal content from the message chain
3. Calling the judge to generate a replacement turn
"""
from .llm_router import call_llm


def detect_refusal(story_turn, classifier_model, classifier_prompt_text, classifier_question, timeout=10):
    """
    Use a classifier model to determine if a story turn is a refusal.
    
    Args:
        story_turn: The storyteller's response text
        classifier_model: Model to use for classification (e.g., "gemma3:270m")
        classifier_prompt_text: System prompt explaining how to classify
        classifier_question: Question to ask along with the story turn
        timeout: Classification timeout in seconds
    
    Returns:
        tuple: (is_refusal: bool, classifier_response: str)
    """
    if not classifier_model or not classifier_prompt_text:
        print("[REFUSAL] No classifier configured, skipping detection")
        return False, ""
    
    # Build classification message
    messages = [{
        "role": "user",
        "content": f"{classifier_question}\n\n{story_turn}"
    }]
    
    try:
        print(f"[REFUSAL] Checking with {classifier_model}")
        
        classifier_response = call_llm(
            messages=messages,
            system_prompt=classifier_prompt_text,
            llm_model=classifier_model,
            timeout=timeout,
            disable_thinking=True  # Fast binary classification, no chain-of-thought needed
        )
        
        # Check if response indicates refusal
        # Looking for YES/TRUE at start of response (classifier should answer with single word)
        response_lower = classifier_response.strip().lower()
        # Check if response starts with yes/true, or is exactly "yes" or "true"
        is_refusal = (
            response_lower.startswith('yes') or 
            response_lower.startswith('true') or
            response_lower == 'yes' or
            response_lower == 'true'
        )
        
        if is_refusal:
            print(f"[REFUSAL] ⚠️  DETECTED - Classifier says: {classifier_response[:100]}")
        else:
            print(f"[CLASSIFIER] ✓ No refusal detected - Response: {classifier_response[:100]}")
        
        return is_refusal, classifier_response
    
    except Exception as e:
        print(f"[REFUSAL] Classification error: {e}")
        # On error, assume it's not a refusal (fail-safe)
        return False, f"Error: {str(e)}"


def strip_refusal_from_messages(messages):
    """
    Remove the last assistant message (the refusal) from the message chain.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
    
    Returns:
        List of messages with the last assistant message removed
    """
    if not messages:
        return messages
    
    # Simply remove the last message (which should be the refusal from assistant)
    if messages and messages[-1].get('role') == 'assistant':
        filtered = messages[:-1]
        print(f"[REFUSAL] Stripped last assistant message: {len(filtered)} messages remaining")
        return filtered
    
    # If last message wasn't from assistant, return as-is
    return messages


def generate_corrected_turn(messages, turn_correction_prompt_text, turn_correction_model, timeout=30):
    """
    Use the turn correction prompt to generate a valid turn.
    
    Args:
        messages: Message chain with refusal stripped
        turn_correction_prompt_text: Turn correction prompt (used as-is)
        turn_correction_model: LLMModel instance to use for correction
        timeout: Generation timeout in seconds
    
    Returns:
        str: Generated corrected turn
    """
    try:
        print(f"[REFUSAL] Generating correction with {turn_correction_model.name}")
        
        corrected_turn = call_llm(
            messages=messages,
            system_prompt=turn_correction_prompt_text,
            llm_model=turn_correction_model,
            timeout=timeout
        )
        
        print(f"[REFUSAL] ✓ Generated corrected turn: {len(corrected_turn)} chars")
        return corrected_turn
    
    except Exception as e:
        print(f"[REFUSAL] Error generating correction: {e}")
        raise


def process_potential_refusal(
    messages,
    story_turn,
    config,
    user_message,
    is_game_ending=False,
    turn_number=1,
    max_retries=3
):
    """
    Complete refusal detection and correction pipeline with retry logic.
    
    Args:
        messages: Full message history including the refusal
        story_turn: The storyteller's response (potential refusal)
        config: Configuration object with classifier/judge settings
        user_message: The user's last message content
        is_game_ending: Whether this is a game-ending turn
        turn_number: Current turn number (for special handling of turn 1)
        max_retries: Maximum correction attempts (default: 3 total including initial)
    
    Returns:
        dict: {
            'final_turn': str,           # The final turn to use
            'was_refusal': bool,          # Whether a refusal was detected
            'classifier_response': str,   # Classifier's raw response
            'was_corrected': bool,        # Whether correction was applied
            'turn_1_refusal': bool,       # If this was a turn 1 refusal (not correctable)
            'attempts': list              # All attempts with details
        }
    """
    result = {
        'final_turn': story_turn,
        'was_refusal': False,
        'classifier_response': '',
        'was_corrected': False,
        'turn_1_refusal': False,
        'attempts': []
    }
    
    # Skip if refusal detection is disabled
    if not config.enable_refusal_detection:
        print("[REFUSAL] Detection disabled in config")
        return result
    
    # Check for classifier configuration
    if not config.classifier_model or not config.classifier_prompt:
        print("[REFUSAL] No classifier configured, skipping")
        return result
    
    # Check for turn correction configuration (needed if we detect a refusal)
    if turn_number > 1 and (not config.turn_correction_model or not config.turn_correction_prompt):
        print("[REFUSAL] Warning: Refusal detection enabled but no turn correction configured")
        print("[REFUSAL] Can detect refusals but cannot correct them (will use original turn)")
        # Still run detection but won't be able to correct
    
    # Step 1: Detect refusal on initial turn
    is_refusal, classifier_response = detect_refusal(
        story_turn=story_turn,
        classifier_model=config.classifier_model,
        classifier_prompt_text=config.classifier_prompt.prompt_text,
        classifier_question=config.classifier_question,
        timeout=config.classifier_timeout
    )
    
    result['was_refusal'] = is_refusal
    result['classifier_response'] = classifier_response
    result['attempts'].append({
        'attempt_number': 1,
        'turn_text': story_turn,
        'classifier_response': classifier_response,
        'was_refusal': is_refusal
    })
    
    # If not a refusal, return original turn
    if not is_refusal:
        return result
    
    # Special handling for turn 1 refusals - can't rewrite without context
    if turn_number == 1:
        print("[REFUSAL] ⚠️  Turn 1 refusal detected - not enough context to rewrite")
        result['turn_1_refusal'] = True
        return result
    
    # Check that we have turn correction configured before attempting
    if not config.turn_correction_model or not config.turn_correction_prompt:
        print("[REFUSAL] ❌ Refusal detected but no turn correction configured - cannot fix")
        result['all_attempts_failed'] = True
        return result
    
    # Step 2: Attempt to correct the refusal (with retry loop)
    cleaned_messages = strip_refusal_from_messages(messages)
    
    # Determine which correction prompt to use
    if is_game_ending and config.game_ending_turn_correction_prompt:
        correction_prompt = config.game_ending_turn_correction_prompt.prompt_text
        print("[REFUSAL] Using game-ending turn correction prompt")
    elif is_game_ending and config.game_ending_prompt:
        # Fallback to regular game ending prompt
        correction_prompt = config.game_ending_prompt.prompt_text
        print("[REFUSAL] Game-ending correction prompt not found, using game-ending prompt")
    else:
        correction_prompt = config.turn_correction_prompt.prompt_text
        print("[REFUSAL] Using regular turn correction prompt")
    
    # Retry loop: try up to max_retries total (including initial refusal)
    attempts_remaining = max_retries - 1  # -1 because initial turn counts as attempt 1
    current_attempt = 2
    
    while attempts_remaining > 0:
        try:
            # Generate corrected turn
            corrected_turn = generate_corrected_turn(
                messages=cleaned_messages,
                turn_correction_prompt_text=correction_prompt,
                turn_correction_model=config.turn_correction_model,
                timeout=config.turn_correction_timeout
            )
            
            # Check if the correction is also a refusal
            is_corrected_refusal, corrected_classifier_response = detect_refusal(
                story_turn=corrected_turn,
                classifier_model=config.classifier_model,
                classifier_prompt_text=config.classifier_prompt.prompt_text,
                classifier_question=config.classifier_question,
                timeout=config.classifier_timeout
            )
            
            result['attempts'].append({
                'attempt_number': current_attempt,
                'turn_text': corrected_turn,
                'classifier_response': corrected_classifier_response,
                'was_refusal': is_corrected_refusal
            })
            
            if not is_corrected_refusal:
                # Success! Use this corrected turn
                result['final_turn'] = corrected_turn
                result['was_corrected'] = True
                result['classifier_response'] = corrected_classifier_response
                print(f"[REFUSAL] ✅ Successfully corrected refusal on attempt {current_attempt}")
                return result
            
            # Still a refusal, try again
            print(f"[REFUSAL] ⚠️  Attempt {current_attempt} still a refusal, retrying...")
            attempts_remaining -= 1
            current_attempt += 1
            
        except Exception as e:
            print(f"[REFUSAL] ❌ Error on attempt {current_attempt}: {e}")
            result['attempts'].append({
                'attempt_number': current_attempt,
                'turn_text': '',
                'classifier_response': f'Error: {str(e)}',
                'was_refusal': True,
                'error': True
            })
            attempts_remaining -= 1
            current_attempt += 1
    
    # All attempts exhausted - still a refusal
    print(f"[REFUSAL] ❌ Failed to correct after {max_retries} attempts")
    result['was_corrected'] = False
    result['all_attempts_failed'] = True
    
    return result
