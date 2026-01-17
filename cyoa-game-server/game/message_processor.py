"""
Message processing utilities.
Handles message filtering, session extraction, and conversation setup.
"""
from .models import GameSession
from .session_utils import extract_session_id, strip_session_id_marker, generate_conversation_fingerprint


def process_messages(messages):
    """
    Process incoming OpenWebUI messages.
    Filters system messages, extracts session ID, generates fingerprint.
    
    Args:
        messages: Raw message list from OpenWebUI request
    
    Returns:
        Tuple of (filtered_messages, session_id, conversation_fingerprint)
    """
    print(f"[DEBUG] Processing {len(messages)} total messages from OpenWebUI")
    
    filtered_messages = []
    session_id = None
    
    # First, extract session ID from any message
    session_id = extract_session_id(messages)
    if session_id:
        print(f"[SESSION] ✓ Extracted session ID from messages: {session_id}")
    
    # Process and filter messages
    for idx, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        print(f"[DEBUG] Message {idx}: role={role}, speaker={msg.get('speaker', 'none')}")
        
        # Skip system messages
        if role == "system":
            print(f"[DEBUG]   → Ignoring system message")
            continue
        
        # Skip base speaker messages (used for side-by-side comparison)
        if msg.get("speaker") == "base":
            print(f"[DEBUG]   → Ignoring base speaker message")
            continue
        
        # Strip session ID markers from content
        msg = msg.copy()
        content = msg.get("content", "")
        if isinstance(content, str):
            # DEBUG: Show preview of assistant messages
            if role == "assistant" and len(content) > 100:
                print(f"[DEBUG] Assistant message preview ({len(content)} chars): ...{content[-200:]}")
            
            msg["content"] = strip_session_id_marker(content)
        
        filtered_messages.append(msg)
        print(f"[DEBUG]   → Added to filtered messages")
    
    print(f"[DEBUG] Filtered down to {len(filtered_messages)} messages")
    
    # Generate conversation fingerprint for session lookup
    conversation_fingerprint = generate_conversation_fingerprint(filtered_messages)
    if conversation_fingerprint:
        print(f"[DEBUG] Conversation fingerprint: {conversation_fingerprint}")
    
    # If no session ID found, try looking up by fingerprint
    if not session_id and conversation_fingerprint:
        try:
            game_session = GameSession.objects.filter(
                conversation_fingerprint=conversation_fingerprint
            ).first()
            if game_session:
                session_id = game_session.session_id
                print(f"[SESSION] ✓ Found session via fingerprint: {session_id}")
            else:
                print(f"[SESSION] ⚠️  No session found for fingerprint {conversation_fingerprint}")
        except Exception as e:
            print(f"[SESSION] Error looking up by fingerprint: {e}")
    
    # Log final session status
    if not session_id:
        print(f"[SESSION] ⚠ ⚠ ⚠  NO SESSION ID FOUND - DIFFICULTY SYSTEM WILL NOT RUN ⚠ ⚠ ⚠")
        print(f"[SESSION] Without session ID, games will have no death mechanics or turn tracking")
    else:
        print(f"[SESSION] Using session ID: {session_id}")
    
    return filtered_messages, session_id, conversation_fingerprint
