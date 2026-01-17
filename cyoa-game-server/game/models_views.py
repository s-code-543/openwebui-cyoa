"""
Model discovery views for listing available LLMs.
"""
import time
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .ollama_utils import get_ollama_models


@require_http_methods(["GET"])
def list_models(request):
    """
    OpenAI-compatible models endpoint.
    Lists both Claude and Ollama models.
    """
    models = [
        {
            "id": "gameserver-cyoa",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "cyoa-game-server",
            "description": "Production: Combined storyteller + judge (single call, no cache)"
        },
        {
            "id": "gameserver-cyoa-base",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "cyoa-game-server",
            "description": "Base storyteller only (for testing prompts)"
        },
        {
            "id": "gameserver-cyoa-test",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "cyoa-game-server",
            "description": "Test mode - hardcoded response (no API calls)"
        }
    ]
    
    # Add Ollama models
    ollama_models = get_ollama_models()
    for model in ollama_models:
        models.append({
            "id": model["id"],
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ollama",
            "description": f"Ollama: {model['name']}"
        })
    
    return JsonResponse({
        "object": "list",
        "data": models
    })
