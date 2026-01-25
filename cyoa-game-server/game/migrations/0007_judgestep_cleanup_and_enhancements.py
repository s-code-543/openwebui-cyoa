# Generated migration for JudgeStep model cleanup and enhancements

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0006_make_turn_correction_nullable'),
    ]

    operations = [
        # Add new classifier fields
        migrations.AddField(
            model_name='judgestep',
            name='classifier_prompt',
            field=models.ForeignKey(blank=True, help_text='Classifier prompt (optional - if omitted, always proceeds to rewrite)', limit_choices_to={'prompt_type': 'classifier'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_classifier', to='game.prompt'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='classifier_model',
            field=models.ForeignKey(blank=True, help_text='Model for classification', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_classifier_model', to='game.llmmodel'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='classifier_timeout',
            field=models.IntegerField(default=10, help_text='Timeout in seconds for classification'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='classifier_question',
            field=models.TextField(default='Does this turn have issues?', help_text='Question to ask classifier about the turn'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='classifier_use_full_context',
            field=models.BooleanField(default=False, help_text='Use full message history (true) or just turn text (false)'),
        ),
        
        # Add missing context control fields
        migrations.AddField(
            model_name='judgestep',
            name='rewrite_use_full_context',
            field=models.BooleanField(default=True, help_text='Use full message history (true) or just turn text (false)'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='max_rewrite_attempts',
            field=models.IntegerField(default=3, help_text='Maximum rewrite attempts before giving up'),
        ),
        migrations.AddField(
            model_name='judgestep',
            name='compare_use_full_context',
            field=models.BooleanField(default=False, help_text='Use full message history (true) or just the two turns (false)'),
        ),
        
        # Remove deprecated judge_ fields
        migrations.RemoveField(
            model_name='judgestep',
            name='judge_prompt',
        ),
        migrations.RemoveField(
            model_name='judgestep',
            name='judge_model',
        ),
        migrations.RemoveField(
            model_name='judgestep',
            name='judge_timeout',
        ),
    ]
