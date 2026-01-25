# Generated migration for prompt model changes

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0002_configuration_classifier_question'),
    ]

    operations = [
        # Remove the prompt_type is_active index FIRST (before dropping the field)
        migrations.RemoveIndex(
            model_name='prompt',
            name='game_prompt_prompt__e8e48e_idx',
        ),
        # Add file_path field to Prompt model
        migrations.AddField(
            model_name='prompt',
            name='file_path',
            field=models.CharField(blank=True, help_text='Path to the source .txt file for this prompt (relative to cyoa_prompts/)', max_length=500),
        ),
        # Remove is_active field from Prompt model (after removing the index)
        migrations.RemoveField(
            model_name='prompt',
            name='is_active',
        ),
        # Update game_ending_turn_correction_prompt to be nullable
        migrations.AlterField(
            model_name='configuration',
            name='game_ending_turn_correction_prompt',
            field=models.ForeignKey(blank=True, help_text='Turn correction prompt specifically for game-ending turns (optional, falls back to turn_correction_prompt)', limit_choices_to={'prompt_type': 'turn-correction'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='configs_as_game_ending_turn_correction', to='game.prompt'),
        ),
    ]
