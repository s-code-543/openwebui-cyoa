"""
Configuration utilities.
"""
from .models import Configuration


def get_active_configuration():
    """
    Retrieve the active configuration from database.
    
    Returns:
        Configuration instance or None
    """
    try:
        config = Configuration.objects.filter(is_active=True).first()
        if not config:
            print("[WARNING] No active configuration found in database")
        return config
    except Exception as e:
        print(f"[ERROR] Failed to load configuration from database: {e}")
        return None


def apply_pacing_template(prompt_text, config):
    """
    Replace template variables in prompt text with values from configuration.
    
    Args:
        prompt_text: The prompt text containing template variables
        config: Configuration instance with pacing values
    
    Returns:
        String with template variables replaced
    """
    if not config:
        return prompt_text
    
    pacing = config.get_pacing_dict()
    result = prompt_text
    
    for key, value in pacing.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value))
    
    return result
