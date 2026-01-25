"""
Session ID management utilities.
Handles session generation, extraction, and conversation fingerprinting.
"""
import hashlib
import time
import re


def generate_session_id(messages):
    """
    Generate a unique session ID from timestamp and message content.
    
    Args:
        messages: List of conversation messages
    
    Returns:
        16-character hex session ID
    """
    timestamp = int(time.time() * 1000)
    first_msg = str(messages[0].get('content', '')) if messages else ''
    combined = f"{timestamp}{first_msg}"
    session_id = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return session_id


def inject_session_id_marker(response_text, session_id):
    """
    Inject session ID as markdown link reference at end of response.
    
    Args:
        response_text: The assistant's response text
        session_id: Session ID to inject
    
    Returns:
        Response text with session ID marker appended
    """
    return f"{response_text}\n\n[^s]: # ({session_id})"


def extract_session_id(messages):
    """
    Extract session ID from conversation messages.
    Checks for markdown link reference, HTML comment, or XML format.
    
    Args:
        messages: List of conversation messages
    
    Returns:
        Session ID string or None if not found
    """
    for msg in messages:
        content = msg.get('content', '')
        if not isinstance(content, str):
            continue
        
        # Try markdown link reference format: [^s]: # (abc123)
        match = re.search(r'\[\^s\]:\s*#\s*\(([a-f0-9]+)\)', content)
        if match:
            return match.group(1)
        
        # Try old HTML comment format
        match = re.search(r'<!--\s*CYOA_SESSION:([a-f0-9]+)\s*-->', content)
        if match:
            return match.group(1)
        
        # Try oldest XML format
        match = re.search(r'<CYOA_SESSION_ID:([a-f0-9]+)>', content)
        if match:
            return match.group(1)
    
    return None


def strip_session_id_marker(content):
    """
    Remove session ID markers from message content.
    
    Args:
        content: Message content string
    
    Returns:
        Content with session ID markers removed
    """
    if not isinstance(content, str):
        return content
    
    # Remove markdown link reference
    content = re.sub(r'\n*\[\^s\]:\s*#\s*\([a-f0-9]+\)', '', content)
    
    # Remove HTML comment
    content = re.sub(r'<!--\s*CYOA_SESSION:[a-f0-9]+\s*-->\s*', '', content)
    
    # Remove XML format
    content = re.sub(r'\n*<CYOA_SESSION_ID:[a-f0-9]+>', '', content)
    
    return content.rstrip()


def generate_conversation_fingerprint(messages):
    """
    Generate a fingerprint from first user + first assistant messages.
    This is unique per game and stable across turns.
    
    Args:
        messages: List of conversation messages
    
    Returns:
        16-character hex fingerprint or None if not enough messages
    """
    first_user = None
    first_assistant = None
    
    for msg in messages:
        role = msg.get('role')
        if role == 'user' and first_user is None:
            first_user = msg.get('content', '')
        elif role == 'assistant' and first_assistant is None:
            first_assistant = msg.get('content', '')
        
        if first_user and first_assistant:
            break
    
    if not (first_user and first_assistant):
        return None
    
    combo = f"{first_user[:200]}|{first_assistant[:200]}"
    fingerprint = hashlib.sha256(combo.encode()).hexdigest()[:16]
    return fingerprint
