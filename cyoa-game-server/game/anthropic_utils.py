"""
Anthropic API utilities for calling Claude models.
Supports direct API access to claude-opus, claude-sonnet, claude-haiku, etc.
"""
import requests
import json
from django.conf import settings


ANTHROPIC_API_VERSION = "2023-06-01"


def test_anthropic_connection(api_key, timeout=10):
    """
    Test connection to Anthropic API by attempting to list models or validate key.
    
    Args:
        api_key: Anthropic API key
        timeout: Connection timeout in seconds
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    if not api_key or not api_key.startswith('sk-ant-'):
        return {
            'success': False,
            'message': "Invalid API key format. Should start with 'sk-ant-'"
        }
    
    try:
        # Make a minimal test call to validate the key
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json"
        }
        
        # Use a minimal request to test authentication
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Hi"}]
        }
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        
        if response.status_code == 200:
            return {
                'success': True,
                'message': "API key validated successfully"
            }
        elif response.status_code == 401:
            return {
                'success': False,
                'message': "Invalid API key or authentication failed"
            }
        elif response.status_code == 429:
            return {
                'success': True,
                'message': "API key valid (rate limit encountered, but auth OK)"
            }
        else:
            return {
                'success': False,
                'message': f"HTTP {response.status_code}: {response.text}"
            }
    
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'message': f"Connection timeout after {timeout}s"
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'message': "Cannot connect to api.anthropic.com. Check network."
        }
    except Exception as e:
        return {
            'success': False,
            'message': f"Error: {str(e)}"
        }


def get_anthropic_models(api_key, timeout=10):
    """
    Fetch available Claude models from Anthropic API.
    
    Args:
        api_key: Anthropic API key (required)
        timeout: Request timeout in seconds
    
    Returns:
        List of model dicts with 'name', 'id', 'description', 'size' (0 for API models)
    """
    if not api_key:
        print("[ANTHROPIC] No API key provided, cannot list models")
        return []
    
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json"
        }
        
        response = requests.get(
            "https://api.anthropic.com/v1/models",
            headers=headers,
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"[ANTHROPIC] Raw API response: {json.dumps(data, indent=2)}")
            models = []
            
            for model in data.get('data', []):
                # Extract created_at for better description if available
                created_at = model.get('created_at', '')
                description = model.get('description', '')
                if created_at and not description:
                    description = f"Released: {created_at}"
                
                models.append({
                    'name': model.get('display_name', model.get('id', 'Unknown')),
                    'id': model.get('id', ''),
                    'description': description,
                    'size': 0,  # API models don't have downloadable size
                    'created_at': created_at
                })
            
            print(f"[ANTHROPIC] ✓ Found {len(models)} models")
            return models
        
        elif response.status_code == 401:
            print("[ANTHROPIC] ✗ Authentication failed - invalid API key")
            return []
        
        else:
            print(f"[ANTHROPIC] ✗ HTTP {response.status_code}: {response.text}")
            return []
    
    except requests.exceptions.Timeout:
        print(f"[ANTHROPIC] ✗ Request timeout after {timeout}s")
        return []
    
    except requests.exceptions.ConnectionError:
        print("[ANTHROPIC] ✗ Cannot connect to api.anthropic.com")
        return []
    
    except Exception as e:
        print(f"[ANTHROPIC] ✗ Error fetching models: {e}")
        return []


def call_anthropic(messages, system_prompt=None, model="claude-haiku-4-5", api_key=None, timeout=60):
    """
    Call Anthropic API for chat completion.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: System prompt text (optional)
        model: Model identifier (default: 'claude-haiku-4-5')
        api_key: Anthropic API key (if None, uses settings.ANTHROPIC_API_KEY)
        timeout: Request timeout in seconds (default: 60)
    
    Returns:
        String response from Claude
    """
    # Use provided api_key or fall back to settings
    if api_key is None:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            raise ValueError("No Anthropic API key provided and none found in settings")
    
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json"
    }
    
    # Build Anthropic messages format (no system role in messages)
    anthropic_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Skip system messages (they go in the system field)
        if role == "system":
            continue
        
        # Anthropic only accepts 'user' and 'assistant' roles
        if role not in ("user", "assistant"):
            continue
        
        # Handle both simple string content and multipart content
        if isinstance(content, list):
            # Multipart content - extract text parts
            processed_content = []
            for item in content:
                if item.get("type") == "text":
                    processed_content.append({"type": "text", "text": item.get("text", "")})
            anthropic_messages.append({
                "role": role,
                "content": processed_content
            })
        else:
            # Simple text content
            anthropic_messages.append({
                "role": role,
                "content": content
            })
    
    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": anthropic_messages
    }
    
    if system_prompt:
        payload["system"] = system_prompt
    
    print(f"[ANTHROPIC] Calling API with model {model}")
    print(f"[ANTHROPIC] Messages: {len(anthropic_messages)}, Timeout: {timeout}s")
    
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            content_blocks = data.get('content', [])
            
            # Extract text from content blocks
            text_parts = []
            for block in content_blocks:
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            
            result = '\n'.join(text_parts)
            print(f"[ANTHROPIC] ✓ Got response: {len(result)} chars")
            return result
        
        elif response.status_code == 401:
            error_msg = "Anthropic API authentication failed. Check API key."
            print(f"[ANTHROPIC] ✗ {error_msg}")
            raise Exception(error_msg)
        
        elif response.status_code == 429:
            error_msg = "Anthropic API rate limit exceeded. Try again later."
            print(f"[ANTHROPIC] ✗ {error_msg}")
            raise Exception(error_msg)
        
        else:
            error_msg = f"Anthropic API HTTP {response.status_code}: {response.text}"
            print(f"[ANTHROPIC] ✗ {error_msg}")
            raise Exception(error_msg)
    
    except requests.exceptions.Timeout:
        error_msg = f"Anthropic API request timed out after {timeout}s"
        print(f"[ANTHROPIC] ✗ {error_msg}")
        raise Exception(error_msg)
    
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot connect to api.anthropic.com. Check network."
        print(f"[ANTHROPIC] ✗ {error_msg}")
        raise Exception(error_msg)
    
    except Exception as e:
        print(f"[ANTHROPIC] ✗ Error: {e}")
        raise
