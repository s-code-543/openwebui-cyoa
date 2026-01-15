"""
Utilities for calling external Ollama servers (not localhost).
Supports connecting to Ollama instances on local network or remote servers.
"""
import requests
import json


def test_external_ollama_connection(base_url, timeout=5):
    """
    Test connection to external Ollama server.
    
    Args:
        base_url: Base URL of Ollama server (e.g., 'http://192.168.1.100:11434')
        timeout: Connection timeout in seconds
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    try:
        # Ensure URL ends without trailing slash
        base_url = base_url.rstrip('/')
        
        # Try to get the version/status endpoint
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=timeout
        )
        
        if response.status_code == 200:
            models = response.json().get('models', [])
            return {
                'success': True,
                'message': f"Connected successfully. Found {len(models)} models."
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
            'message': f"Cannot connect to {base_url}. Check URL and network."
        }
    except Exception as e:
        return {
            'success': False,
            'message': f"Error: {str(e)}"
        }


def get_external_ollama_models(base_url, timeout=10):
    """
    Retrieve list of available models from external Ollama server.
    
    Args:
        base_url: Base URL of Ollama server
        timeout: Request timeout in seconds
    
    Returns:
        List of model dicts with 'name', 'size', 'modified', etc.
    """
    try:
        base_url = base_url.rstrip('/')
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            
            # Format models consistently
            formatted_models = []
            for model in models:
                formatted_models.append({
                    'name': model.get('name', 'unknown'),
                    'id': model.get('name', 'unknown'),
                    'size': model.get('size', 0),
                    'modified': model.get('modified_at', ''),
                    'digest': model.get('digest', ''),
                })
            
            return formatted_models
        else:
            print(f"[EXTERNAL OLLAMA] Failed to get models: HTTP {response.status_code}")
            return []
    
    except Exception as e:
        print(f"[EXTERNAL OLLAMA] Error getting models: {e}")
        return []


def call_external_ollama(messages, system_prompt, model, base_url, timeout=30):
    """
    Call external Ollama server for chat completion.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: System prompt text (optional)
        model: Model name/identifier
        base_url: Base URL of Ollama server
        timeout: Request timeout in seconds
    
    Returns:
        String response from the model
    """
    base_url = base_url.rstrip('/')
    
    # Build Ollama chat messages format
    ollama_messages = []
    
    if system_prompt:
        ollama_messages.append({
            "role": "system",
            "content": system_prompt
        })
    
    for msg in messages:
        ollama_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })
    
    payload = {
        "model": model,
        "messages": ollama_messages,
        "stream": False
    }
    
    print(f"[EXTERNAL OLLAMA] Calling {base_url} with model {model}")
    print(f"[EXTERNAL OLLAMA] Messages: {len(ollama_messages)}, Timeout: {timeout}s")
    
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            message = data.get('message', {})
            content = message.get('content', '')
            
            print(f"[EXTERNAL OLLAMA] ✓ Got response: {len(content)} chars")
            return content
        else:
            error_msg = f"External Ollama HTTP {response.status_code}: {response.text}"
            print(f"[EXTERNAL OLLAMA] ✗ {error_msg}")
            raise Exception(error_msg)
    
    except requests.exceptions.Timeout:
        error_msg = f"External Ollama request timed out after {timeout}s"
        print(f"[EXTERNAL OLLAMA] ✗ {error_msg}")
        raise Exception(error_msg)
    
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Cannot connect to external Ollama at {base_url}"
        print(f"[EXTERNAL OLLAMA] ✗ {error_msg}")
        raise Exception(error_msg)
    
    except Exception as e:
        print(f"[EXTERNAL OLLAMA] ✗ Error: {e}")
        raise
