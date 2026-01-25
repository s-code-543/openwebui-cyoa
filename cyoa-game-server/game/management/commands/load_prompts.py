"""
Management command to load or reload all prompts from the cyoa_prompts directory.
Loads using a directory structure:
    cyoa_prompts/
        story_prompts/              -> prompt_type = 'adventure'
        turn_correction_prompts/    -> prompt_type = 'turn-correction'
        game_ending_prompts/        -> prompt_type = 'game-ending'
        classifier_prompts/         -> prompt_type = 'classifier'

Version is inferred from filename: name_v1.txt -> version 1, name_v2.txt -> version 2
"""
from django.core.management.base import BaseCommand
from game.models import Prompt
import os
import glob
import re


class Command(BaseCommand):
    help = 'Load or update prompts from cyoa_prompts subdirectories'

    def handle(self, *args, **options):
        # Determine prompts directory path
        if os.path.exists('/story_prompts'):
            # In container volume mount
            base_dir = '/story_prompts'
        else:
            # Local development
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            base_dir = os.path.join(project_root, 'cyoa_prompts')
        
        self.stdout.write(f"Loading prompts from base: {base_dir}")
        
        if not os.path.exists(base_dir):
            self.stdout.write(self.style.ERROR(f"Base directory not found: {base_dir}"))
            return

        total_created = 0
        total_updated = 0

        # Directory to prompt_type mapping
        dir_config = {
            'story_prompts': 'adventure',
            'turn_correction_prompts': 'turn-correction',
            'game_ending_prompts': 'game-ending',
            'classifier_prompts': 'classifier',
            'judge_prompts': 'judge',
        }
        
        for dir_name, prompt_type in dir_config.items():
            dir_path = os.path.join(base_dir, dir_name)
            if os.path.exists(dir_path):
                c, u = self.process_directory(dir_path, prompt_type, dir_name)
                total_created += c
                total_updated += u
            else:
                self.stdout.write(self.style.WARNING(f"Directory missing: {dir_path}"))

        self.stdout.write(self.style.SUCCESS(f"\nAll prompts processed! Created: {total_created}, Updated: {total_updated}"))
    
    def parse_filename(self, filename):
        """
        Parse a filename to extract the name and version.
        
        Examples:
            'haunted-house-prompt_v1.txt' -> ('haunted-house-prompt', 1)
            'correct_refusal_v2.txt' -> ('correct_refusal', 2)
            'detect_refusal_v1.txt' -> ('detect_refusal', 1)
            'old_prompt.txt' -> ('old_prompt', 1)  # No version = v1
        """
        name_no_ext = filename.replace('.txt', '')
        
        # Match _v<number> at the end of the filename
        version_match = re.search(r'_v(\d+)$', name_no_ext)
        
        if version_match:
            version = int(version_match.group(1))
            # Remove the _vN suffix to get the name
            name = name_no_ext[:version_match.start()]
        else:
            # No version suffix - treat as version 1
            version = 1
            name = name_no_ext
        
        return name, version

    def process_directory(self, directory, prompt_type, dir_name):
        """Process all .txt files in a directory."""
        files = sorted(glob.glob(os.path.join(directory, '*.txt')))
        created_count = 0
        updated_count = 0

        for filepath in files:
            filename = os.path.basename(filepath)
            
            # Parse name and version from filename
            name, version = self.parse_filename(filename)
            
            # Read content
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to read {filename}: {e}"))
                continue

            # Create description from name
            description = name.replace('-', ' ').replace('_', ' ').title()
            
            # Build relative file path for storage
            relative_path = f"{dir_name}/{filename}"

            prompt, created = Prompt.objects.update_or_create(
                prompt_type=prompt_type,
                name=name,
                version=version,
                defaults={
                    'description': description,
                    'prompt_text': content,
                    'file_path': relative_path
                }
            )
            
            action = "Created" if created else "Updated"
            self.stdout.write(f"  ✓ {action}: [{prompt_type}/{name} v{version}] {description}")
            
            if created:
                created_count += 1
            else:
                updated_count += 1
        
        return created_count, updated_count
