"""
Utilities for calling OpenAI API.
Supports GPT-4, GPT-3.5-turbo, and other OpenAI models.
"""
import requests
import json


def test_openai_connection(api_key, timeout=10):
    """
    Test connection to OpenAI API by attempting to validate the key.
    
    Args:
        api_key: OpenAI API key
        timeout: Connection timeout in seconds
    
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    if not api_key or not api_key.startswith('sk-'):
        return {
            'success': False,
            'message': "Invalid API key format. Should start with 'sk-'"
        }
    
    try:
        # Make a minimal test call to validate the key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Use a minimal request to test authentication
        # Using gpt-3.5-turbo for cheap testing
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
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
                'message': f"HTTP {response.status_code}: {response.text[:200]}"
            }
    
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'message': f"Connection timeout after {timeout}s"
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'message': "Cannot connect to api.openai.com. Check network."
        }
    except Exception as e:
        return {
            'success': False,
            'message': f"Error: {str(e)}"
        }


def get_openai_models(api_key, timeout=10):
    """
    Fetch available models from OpenAI API.
    
    Args:
        api_key: OpenAI API key (required)
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
            "https://api.openai.com/v1/models",
            headers=headers,
            timeout=timeout
        )
        
        if response.status_code != 200:
            print(f"Failed to fetch OpenAI models: {response.status_code}")
            return []
        
        data = response.json()
        models_list = []
        
        # OpenAI returns models in 'data' array
        # Filter to chat models (gpt-*) and commonly used models
        for model in data.get('data', []):
            model_id = model.get('id', '')
            
            # Filter to useful chat models
            if not any([
                model_id.startswith('gpt-4'),
                model_id.startswith('gpt-3.5'),
                model_id == 'o1-preview',
                model_id == 'o1-mini'
            ]):
                continue
            
            # Build friendly description
            description = ""
            if 'gpt-4' in model_id:
                if 'turbo' in model_id:
                    description = "GPT-4 Turbo - Most capable, faster"
                elif 'vision' in model_id:
                    description = "GPT-4 with vision capabilities"
                elif 'o' in model_id:
                    description = "GPT-4o - Optimized for speed and cost"
                else:
                    description = "GPT-4 - Most capable model"
            elif 'gpt-3.5' in model_id:
                description = "GPT-3.5 Turbo - Fast and efficient"
            elif 'o1' in model_id:
                if 'mini' in model_id:
                    description = "O1 Mini - Faster reasoning model"
                else:
                    description = "O1 - Advanced reasoning model"
            
            # Add created date if available
            created = model.get('created')
            if created:
                from datetime import datetime
                created_date = datetime.fromtimestamp(created).strftime('%Y-%m-%d')
                if description:
                    description += f" (released {created_date})"
                else:
                    description = f"Released {created_date}"
            
            models_list.append({
                'id': model_id,
                'name': model_id,
                'description': description,
                'size': 0,  # API models don't have a size
                'owned_by': model.get('owned_by', 'openai')
            })
        
        # Sort by model name (gpt-4 first, then gpt-3.5)
        models_list.sort(key=lambda x: (
            0 if 'o1' in x['id'] else 1 if 'gpt-4' in x['id'] else 2,
            x['id']
        ))
        
        return models_list
    
    except Exception as e:
        print(f"Error fetching OpenAI models: {e}")
        return []


def call_openai(messages, system_prompt, model, api_key, timeout=30):
    """
    Call OpenAI API with messages.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        system_prompt: Optional system prompt to prepend
        model: Model identifier (e.g., 'gpt-4', 'gpt-3.5-turbo')
        api_key: OpenAI API key
        timeout: Request timeout in seconds
    
    Returns:
        String response from the model
    
    Raises:
        Exception: If the API call fails
    """
    if not api_key:
        raise ValueError("OpenAI API key is required")
    
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
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": api_messages
    }
    
    print(f"[OPENAI] Calling {model} with {len(api_messages)} messages")
    
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        
        if response.status_code != 200:
            error_msg = f"OpenAI API error: {response.status_code}"
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
            print(f"[OPENAI] Received {len(content)} chars")
            return content
        else:
            raise Exception("No response content in OpenAI API result")
    
    except requests.exceptions.Timeout:
        raise Exception(f"OpenAI API timeout after {timeout}s")
    except requests.exceptions.RequestException as e:
        raise Exception(f"OpenAI API request failed: {str(e)}")
