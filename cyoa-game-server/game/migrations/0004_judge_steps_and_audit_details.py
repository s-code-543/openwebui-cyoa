from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0003_prompt_file_path_and_category_consolidation'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='details',
            field=models.JSONField(blank=True, default=dict, help_text='Structured details for judge pipelines or other processing'),
        ),
        migrations.CreateModel(
            name='JudgeStep',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField(default=0, help_text='Execution order (lower runs first)')),
                ('name', models.CharField(default='judge', help_text="Short label for this judge step (e.g., 'difficulty')", max_length=100)),
                ('enabled', models.BooleanField(default=True, help_text='Enable this judge step')),
                ('judge_timeout', models.IntegerField(default=15, help_text='Timeout in seconds for judge evaluation')),
                ('rewrite_timeout', models.IntegerField(default=30, help_text='Timeout in seconds for rewrite generation')),
                ('rewrite_instruction', models.TextField(blank=True, help_text='User instruction appended when requesting a rewrite')),
                ('compare_timeout', models.IntegerField(default=15, help_text='Timeout in seconds for comparison')),
                ('compare_model', models.ForeignKey(help_text='Model to use for comparison', on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_comparator', to='game.llmmodel')),
                ('compare_prompt', models.ForeignKey(help_text='Prompt to compare original vs rewritten turn', limit_choices_to={'prompt_type': 'judge'}, on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_comparator', to='game.prompt')),
                ('configuration', models.ForeignKey(help_text='Configuration this judge step belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='judge_steps', to='game.configuration')),
                ('judge_model', models.ForeignKey(help_text='Model to use for judge evaluation', on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_evaluator', to='game.llmmodel')),
                ('judge_prompt', models.ForeignKey(help_text='Prompt to evaluate the current turn', limit_choices_to={'prompt_type': 'judge'}, on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_evaluator', to='game.prompt')),
                ('rewrite_model', models.ForeignKey(help_text='Model to use for rewrite', on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_rewriter', to='game.llmmodel')),
                ('rewrite_prompt', models.ForeignKey(help_text='Prompt to rewrite the turn if judge fails', limit_choices_to={'prompt_type': 'turn-correction'}, on_delete=django.db.models.deletion.PROTECT, related_name='judge_steps_as_rewriter', to='game.prompt')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
    ]
