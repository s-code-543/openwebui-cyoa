"""
Utilities for calling OpenRouter API (OpenAI-compatible endpoint).
Supports access to various models through OpenRouter's unified API.
"""
import requests
import json


def test_openrouter_connection(api_key, timeout=10):
    """
    Test connection to OpenRouter API by attempting to validate the key.
    
    Args:
        api_key: OpenRouter API key
        timeout: Connection timeout in seconds
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    if not api_key:
        return {
            'success': False,
            'message': "API key is required"
        }
    
    # Accept both old (sk-or-) and new (sk-or-v1-) formats
    if not (api_key.startswith('sk-or-v1-') or api_key.startswith('sk-or-')):
        return {
            'success': False,
            'message': "Invalid API key format. Should start with 'sk-or-' or 'sk-or-v1-'"
        }
    
    try:
        # Make a minimal test call to validate the key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Use a minimal request to test authentication
        # Using a cheap model for testing
        payload = {
            "model": "openai/gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
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
        elif response.status_code == 402:
            return {
                'success': True,
                'message': "API key valid (insufficient credits, but auth OK)"
            }
        elif response.status_code == 429:
            return {
                'success': True,
                'message': "API key valid (rate limit encountered, but auth OK)"
            }
        else:
            error_detail = response.text[:200]
            try:
                error_json = response.json()
                if 'error' in error_json:
                    error_detail = error_json['error'].get('message', error_detail)
            except:
                pass
            return {
                'success': False,
                'message': f"HTTP {response.status_code}: {error_detail}"
            }
    
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'message': f"Connection timeout after {timeout}s"
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'message': "Cannot connect to openrouter.ai. Check network."
        }
    except Exception as e:
        return {
            'success': False,
            'message': f"Error: {str(e)}"
        }


def get_openrouter_models(api_key, timeout=10):
    """
    Fetch available models from OpenRouter API.
    
    Args:
        api_key: OpenRouter API key (required)
        timeout: Request timeout in seconds
    
    Returns:
        List of model dicts with 'name', 'id', 'description', 'size' (0 for API models)
    """
    if not api_key:
        return []
    
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=timeout
        )
        
        if response.status_code != 200:
            print(f"Failed to fetch OpenRouter models: {response.status_code}")
            return []
        
        data = response.json()
        models_list = []
        
        # OpenRouter returns models in 'data' array
        for model in data.get('data', []):
            model_id = model.get('id', '')
            model_name = model.get('name', model_id)
            description = model.get('description', '')
            
            # Get pricing info for context (optional)
            pricing = model.get('pricing', {})
            prompt_price = pricing.get('prompt', 0)
            completion_price = pricing.get('completion', 0)
            
            # Build description with pricing if available
            full_description = description
            if prompt_price or completion_price:
                full_description += f" (${prompt_price}/M prompt, ${completion_price}/M completion)"
            
            models_list.append({
                'id': model_id,
                'name': model_name,
                'description': full_description,
                'size': 0,  # API models don't have a size
                'context_length': model.get('context_length', 0),
                'pricing': pricing
            })
        
        return models_list
    
    except Exception as e:
        print(f"Error fetching OpenRouter models: {e}")
        return []


def call_openrouter(messages, system_prompt, model, api_key, timeout=30):
    """
    Call OpenRouter API with messages using OpenAI-compatible format.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: Optional system prompt to prepend
        model: Model identifier (e.g., 'anthropic/claude-3.5-sonnet', 'openai/gpt-4')
        api_key: OpenRouter API key
        timeout: Request timeout in seconds
    
    Returns:
        String response from the model
    
    Raises:
        Exception: If the API call fails
    """
    if not api_key:
        raise ValueError("OpenRouter API key is required")
    
    # Prepare messages array
    api_messages = []
    
    # Add system prompt if provided
    if system_prompt:
        api_messages.append({
            "role": "system",
            "content": system_prompt
        })
    
    # Add conversation messages
    api_messages.extend(messages)
    
    # Prepare API request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-username/openwebui-cyoa",  # Optional: for rankings
        "X-Title": "CYOA Game Server"  # Optional: for display in OpenRouter dashboard
    }
    
    payload = {
        "model": model,
        "messages": api_messages
    }
    
    print(f"[OPENROUTER] Calling {model} with {len(api_messages)} messages")
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        
        if response.status_code != 200:
            error_msg = f"OpenRouter API error: {response.status_code}"
            try:
                error_data = response.json()
                error_msg += f" - {error_data.get('error', {}).get('message', response.text)}"
            except:
                error_msg += f" - {response.text[:200]}"
            raise Exception(error_msg)
        
        result = response.json()
        
        # Extract the response content
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            print(f"[OPENROUTER] Received {len(content)} chars")
            return content
        else:
            raise Exception("No response content in OpenRouter API result")
    
    except requests.exceptions.Timeout:
        raise Exception(f"OpenRouter API timeout after {timeout}s")
    except requests.exceptions.RequestException as e:
        raise Exception(f"OpenRouter API request failed: {str(e)}")
