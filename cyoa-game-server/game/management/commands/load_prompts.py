"""
Management command to load or reload all prompts from the cyoa_prompts directory.
Loads using a directory structure:
    cyoa_prompts/
        story_prompts/              -> prompt_type = 'adventure', name = filename
        turn_correction_prompts/    -> prompt_type based on filename:
                                       'v*-game-ending*' -> 'game-ending-correction'
                                       otherwise -> 'turn-correction'
        game_ending_prompts/        -> prompt_type = 'game-ending'
        classifier_prompts/         -> prompt_type = 'classifier'
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
            # In container volume mount, but structure might differ. 
            # Assuming volume mount is at /story_prompts and mimics project struct or just flat?
            # User instructions imply we are restructuring context. 
            # If standard docker setup maps ./cyoa_prompts:/story_prompts, then folders are inside.
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

        # 1. Story Prompts
        stories_dir = os.path.join(base_dir, 'story_prompts')
        if os.path.exists(stories_dir):
            c, u = self.process_directory(stories_dir, default_type=None, is_system=False)
            total_created += c
            total_updated += u
        else:
            self.stdout.write(self.style.WARNING(f"Story dir missing: {stories_dir}"))

        # 2. Turn Correction Prompts (split into regular and game-ending)
        turn_correction_dir = os.path.join(base_dir, 'turn_correction_prompts')
        if os.path.exists(turn_correction_dir):
            c, u = self.process_turn_correction_directory(turn_correction_dir)
            total_created += c
            total_updated += u
        else:
            self.stdout.write(self.style.WARNING(f"Turn correction dir missing: {turn_correction_dir}"))

        # 3. Game Ending Prompts
        ending_dir = os.path.join(base_dir, 'game_ending_prompts')
        if os.path.exists(ending_dir):
            c, u = self.process_directory(ending_dir, default_type='game-ending', is_system=True)
            total_created += c
            total_updated += u
        else:
            self.stdout.write(self.style.WARNING(f"Ending dir missing: {ending_dir}"))

        # 4. Classifier Prompts
        classifier_dir = os.path.join(base_dir, 'classifier_prompts')
        if os.path.exists(classifier_dir):
            c, u = self.process_directory(classifier_dir, default_type='classifier', is_system=True)
            total_created += c
            total_updated += u
        else:
            self.stdout.write(self.style.WARNING(f"Classifier dir missing: {classifier_dir}"))

        self.stdout.write(self.style.SUCCESS(f"\nAll prompts processed! Created: {total_created}, Updated: {total_updated}"))
    
    def process_turn_correction_directory(self, directory):
        """Handle turn correction prompts, splitting into regular and game-ending types"""
        files = sorted(glob.glob(os.path.join(directory, '*.txt')))
        created_count = 0
        updated_count = 0

        for filepath in files:
            filename = os.path.basename(filepath)
            name_no_ext = filename.replace('.txt', '')
            
            # Read content
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to read {filename}: {e}"))
                continue

            # Determine if this is a game-ending correction prompt
            if 'game-ending' in name_no_ext.lower() or 'game_ending' in name_no_ext.lower():
                p_type = 'game-ending-correction'
            else:
                p_type = 'turn-correction'
            
            # Extract version from filename (e.g., v1-default -> version 1)
            version_match = re.search(r'v(\d+)', name_no_ext)
            version = int(version_match.group(1)) if version_match else 1
            
            # Use the name without version prefix for the 'name' field
            name = re.sub(r'^v\d+-?', '', name_no_ext)
            if not name:
                name = name_no_ext
            
            description = name.replace('-', ' ').replace('_', ' ').title()

            prompt, created = Prompt.objects.update_or_create(
                prompt_type=p_type,
                name=name,
                version=version,
                defaults={
                    'description': description,
                    'prompt_text': content,
                    'is_active': True
                }
            )
            
            action = "Created" if created else "Updated"
            self.stdout.write(f"  ✓ {action}: [{p_type}/{name} v{version}] {description}")
            
            if created:
                created_count += 1
            else:
                updated_count += 1
        
        return created_count, updated_count

    def process_directory(self, directory, default_type=None, is_system=False):
        """Generic directory processor for other prompt types"""
        files = sorted(glob.glob(os.path.join(directory, '*.txt')))
        created_count = 0
        updated_count = 0

        for filepath in files:
            filename = os.path.basename(filepath)
            name_no_ext = filename.replace('.txt', '')
            
            # Read content
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to read {filename}: {e}"))
                continue

            if default_type:
                # System prompts (game-ending, classifier)
                p_type = default_type
                # Extract version from filename (e.g., v1-standard -> version 1)
                version_match = re.search(r'v(\d+)', name_no_ext)
                version = int(version_match.group(1)) if version_match else 1
                
                # Use the name without version prefix for the 'name' field
                name = re.sub(r'^v\d+-?', '', name_no_ext)
                if not name:
                    name = name_no_ext
                
                description = name.replace('-', ' ').replace('_', ' ').title()
                is_active = True
            else:
                # Story/adventure prompts
                p_type = 'adventure'
                name = name_no_ext
                version = 1
                description = name_no_ext.replace('-', ' ').replace('_', ' ').title()
                is_active = False

            prompt, created = Prompt.objects.update_or_create(
                prompt_type=p_type,
                name=name,
                version=version,
                defaults={
                    'description': description,
                    'prompt_text': content,
                    'is_active': is_active
                }
            )
            
            action = "Created" if created else "Updated"
            self.stdout.write(f"  ✓ {action}: [{p_type}/{name} v{version}] {description}")
            
            if created:
                created_count += 1
            else:
                updated_count += 1
        
        return created_count, updated_count
