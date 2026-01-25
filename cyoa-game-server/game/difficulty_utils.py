"""
Difficulty system utilities.
Handles death probability calculations and game-ending logic.
"""
import random


def calculate_phase_ends(max_turns):
    """
    Calculate phase end turns for story pacing.
    
    Args:
        max_turns: Total turns in the game
    
    Returns:
        Dictionary with phase1_end, phase2_end, phase3_end, phase4_end
    """
    phase1_end = max(2, int(max_turns * 0.25))  # First 25%
    phase2_end = max(phase1_end + 1, int(max_turns * 0.50))  # 50%
    phase3_end = max(phase2_end + 1, int(max_turns * 0.75))  # 75%
    phase4_end = max(phase3_end + 1, max_turns - 1)  # 100% minus final turn
    
    return {
        'phase1_end': phase1_end,
        'phase2_end': phase2_end,
        'phase3_end': phase3_end,
        'phase4_end': phase4_end
    }


def calculate_turn_number(filtered_messages):
    """
    Calculate which turn this is by counting user messages.
    
    Args:
        filtered_messages: List of conversation messages (user/assistant only)
    
    Returns:
        Integer turn number (1-indexed)
    """
    turn_number = 0
    print(f"[TURN_COUNT] Analyzing {len(filtered_messages)} messages...")
    
    for msg in filtered_messages:
        if msg.get("role") == "user":
            turn_number += 1
            print(f"[TURN_COUNT]   - User message triggers turn #{turn_number}")
        elif msg.get("role") == "assistant":
            print(f"[TURN_COUNT]   - Assistant response (turn already generated)")
    
    print(f"[TURN_COUNT] ✓ This will be turn {turn_number} of the game")
    return turn_number


def should_trigger_death(turn_number, max_turns, difficulty_profile, game_session):
    """
    Determine if death should be triggered based on difficulty curve.
    
    Args:
        turn_number: Current turn number (1-indexed)
        max_turns: Total turns in the game
        difficulty_profile: DifficultyProfile instance with death probability curve
        game_session: GameSession instance for state checking
    
    Returns:
        Boolean indicating whether death should trigger
    """
    # Turn 1: Never kill (need to establish the game)
    if turn_number == 1:
        print(f"[DIFFICULTY] Turn 1 - death mechanism disabled (establishing game first)")
        return False
    
    # Game already over
    if game_session and game_session.game_over:
        print(f"[DIFFICULTY] Game already over, forcing game-ending prompt")
        return True
    
    # Get death probability for this turn
    print(f"[DIFFICULTY] Evaluating death for turn {turn_number}...")
    death_probability = difficulty_profile.evaluate(turn_number, max_turns)
    
    # Roll for death
    roll = random.random()
    will_die = roll < death_probability
    
    print(f"[DIFFICULTY] Death probability: {death_probability*100:.2f}%, Roll: {roll:.4f}, Will die: {will_die}")
    
    # Store roll info in session
    if game_session:
        game_session.last_death_probability = death_probability
        game_session.last_death_roll = roll
        game_session.save()
    
    if will_die:
        print(f"[DIFFICULTY] ✓ Death roll succeeded - will use game-ending prompt")
    
    return will_die


def prepare_death_scene_messages(filtered_messages):
    """
    Prepare messages for death scene generation with full story context.
    
    Args:
        filtered_messages: Full conversation history
    
    Returns:
        List with single user message containing story context and death instruction
    """
    # Build narrative summary of what happened
    story_context = "STORY SO FAR:\n\n"
    for msg in filtered_messages:
        role = msg.get('role', '')
        content = msg.get('content', '')
        if role == 'user':
            story_context += f"Player's action: {content}\n\n"
        elif role == 'assistant':
            story_context += f"Story turn: {content}\n\n"
    
    # Create fresh conversation with context but no formatting pattern
    death_messages = [{
        "role": "user",
        "content": f"{story_context}\nThe protagonist has just died due to random chance (difficulty system roll). Write their sudden death scene now (2-4 paragraphs, contextualized to what they were doing, ending with GAME OVER)."
    }]
    
    print(f"[DIFFICULTY] ✓ Prepared death scene with {len(story_context)} chars of story context")
    return death_messages
