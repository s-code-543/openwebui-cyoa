"""
Management command to reload adventure/system prompts from cyoa_story_prompts directory.
Also loads the game-ending prompt from the game directory.
Updates existing prompts in-place to avoid foreign key issues.
Use this after updating the prompt .txt files with template variables.
"""
from django.core.management.base import BaseCommand
from game.models import Prompt
import os
import glob


class Command(BaseCommand):
    help = 'Reload adventure prompts from cyoa_story_prompts directory and game-ending prompt (updates in-place)'

    def handle(self, *args, **options):
        # Path to story prompts directory
        # In Docker, this is mounted at /story_prompts
        # Locally, look in parent directory
        if os.path.exists('/story_prompts'):
            prompts_dir = '/story_prompts'
        else:
            # Running locally - navigate from game/management/commands to project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            prompts_dir = os.path.join(os.path.dirname(project_root), 'cyoa_story_prompts')
        
        self.stdout.write(f"Reloading story prompts from: {prompts_dir}")
        
        if not os.path.exists(prompts_dir):
            self.stdout.write(self.style.ERROR(f"Directory not found: {prompts_dir}"))
            return
        
        # Find all .txt files in the directory
        txt_files = glob.glob(os.path.join(prompts_dir, '*.txt'))
        
        if not txt_files:
            self.stdout.write(self.style.WARNING(f"No .txt files found in {prompts_dir}"))
            return
        
        # Update existing adventure prompts in-place
        updated_count = 0
        created_count = 0
        
        # Load each prompt file
        for filepath in txt_files:
            filename = os.path.basename(filepath)
            # Use filename without extension as the adventure type
            adventure_type = filename.replace('.txt', '')
            
            # Read the prompt text
            with open(filepath, 'r', encoding='utf-8') as f:
                prompt_text = f.read().strip()
            
            # Generate description from adventure type (convert kebab-case to Title Case)
            description = adventure_type.replace('-', ' ').replace('_', ' ').title()
            
            # Update existing or create new version 1 of this adventure
            prompt, created = Prompt.objects.update_or_create(
                prompt_type=adventure_type,
                version=1,
                defaults={
                    'description': description,
                    'prompt_text': prompt_text,
                    'is_active': False  # Don't auto-activate, let admin choose
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {description} (v1) - type: {adventure_type}"))
                created_count += 1
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Updated: {description} (v1) - type: {adventure_type}"))
                updated_count += 1
        
        # Load game-ending prompt from game directory
        self.stdout.write(f"\nLoading game-ending prompt...")
        game_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        game_ending_path = os.path.join(game_dir, 'game-ending-prompt.txt')
        
        if os.path.exists(game_ending_path):
            with open(game_ending_path, 'r', encoding='utf-8') as f:
                game_ending_text = f.read().strip()
            
            prompt, created = Prompt.objects.update_or_create(
                prompt_type='game-ending',
                version=1,
                defaults={
                    'description': 'Game Ending (Death/Failure) Prompt',
                    'prompt_text': game_ending_text,
                    'is_active': True  # Auto-activate as it's the only one
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created: Game Ending Prompt (v1) [ACTIVE]"))
                created_count += 1
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Updated: Game Ending Prompt (v1) [ACTIVE]"))
                updated_count += 1
        else:
            self.stdout.write(self.style.WARNING(f"  ⚠ Game ending prompt not found at: {game_ending_path}"))
        
        self.stdout.write(self.style.SUCCESS(f"\nStory prompts reloaded successfully!"))
        self.stdout.write(self.style.SUCCESS(f"Created: {created_count}, Updated: {updated_count}"))
        if updated_count > 0:
            self.stdout.write(self.style.WARNING(f"Configurations using these prompts will now use the updated content"))
