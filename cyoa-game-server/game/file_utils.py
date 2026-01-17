"""
Utility functions for loading prompts and text files.
"""
import os


def load_prompt_file(filename):
    """
    Load a text file from the configured prompts directory.
    
    Args:
        filename: Name of the file to load (e.g., 'judge-prompt.txt')
    
    Returns:
        String contents of the file, stripped of leading/trailing whitespace
    """
    # 1. Check Docker mount point first
    if os.path.exists('/story_prompts'):
        prompts_dir = '/story_prompts'
    else:
        # 2. Local development fallback
        # Navigate from game/file_utils.py to project root/cyoa_prompts
        # game/file_utils.py -> game -> cyoa-game-server -> openwebui-cyoa -> cyoa_prompts
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompts_dir = os.path.join(base_dir, 'cyoa_prompts')

    file_path = os.path.join(prompts_dir, filename)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found at {file_path}")

