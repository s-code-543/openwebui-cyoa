"""
Management command to load or reload all prompts from the cyoa_prompts directory.
This consolidates loading of adventure prompts, judge prompts, and system prompts.
"""
from django.core.management.base import BaseCommand
from game.models import Prompt
import os
import glob


class Command(BaseCommand):
    help = 'Load or update all prompts from the cyoa_prompts directory'

    def handle(self, *args, **options):
        # Determine prompts directory path
        if os.path.exists('/story_prompts'):
            prompts_dir = '/story_prompts'
        else:
            # Local development: 3 levels up from this file (cmds -> mgmt -> game -> cyoa-game-server -> openwebui-cyoa -> cyoa_prompts)
            # wait, commands -> management -> game -> app root.
            # file is in cyoa-game-server/game/management/commands/load_prompts.py
            # dirname(abspath) -> commands
            # dirname -> management
            # dirname -> game
            # dirname -> cyoa-game-server
            # dirname -> openwebui-cyoa
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            prompts_dir = os.path.join(project_root, 'cyoa_prompts')
        
        self.stdout.write(f"Loading prompts from: {prompts_dir}")
        
        if not os.path.exists(prompts_dir):
            self.stdout.write(self.style.ERROR(f"Directory not found: {prompts_dir}"))
            return
        
        # Find all .txt files
        txt_files = glob.glob(os.path.join(prompts_dir, '*.txt'))
        
        if not txt_files:
            self.stdout.write(self.style.WARNING(f"No .txt files found in {prompts_dir}"))
            return
        
        updated_count = 0
        created_count = 0
        
        for filepath in txt_files:
            filename = os.path.basename(filepath)
            
            # Determine prompt_type based on filename
            if filename == 'judge-prompt.txt':
                prompt_type = 'judge'
                description = 'Judge System Prompt'
                is_active_default = True
            elif filename == 'game-ending-prompt.txt':
                prompt_type = 'game-ending'
                description = 'Game Ending (Death/Failure) Prompt'
                is_active_default = True
            else:
                # Adventure prompt
                prompt_type = filename.replace('.txt', '')
                description = prompt_type.replace('-', ' ').replace('_', ' ').title()
                is_active_default = False
            
            # Read content
            with open(filepath, 'r', encoding='utf-8') as f:
                prompt_text = f.read().strip()
            
            # Update or Create
            # We assume version 1 for these file-based loads for now, or just update the latest/active one?
            # The previous scripts pinned version=1.
            
            prompt, created = Prompt.objects.update_or_create(
                prompt_type=prompt_type,
                version=1,
                defaults={
                    'description': description,
                    'prompt_text': prompt_text,
                    # Only set is_active if creating, to avoid disabling manually enabled stuff?
                    # Or just enforce default? Previous script did: 'is_active': False (or True for system)
                    'is_active': is_active_default
                }
            )
            
            status = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"  ✓ {status}: {description} (type: {prompt_type})"))
            
            if created:
                created_count += 1
            else:
                updated_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"\nPrompts processed successfully!"))
        self.stdout.write(f"Created: {created_count}, Updated: {updated_count}")
