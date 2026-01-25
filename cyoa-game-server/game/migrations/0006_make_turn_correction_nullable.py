# Generated manually to make turn correction fields nullable
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0005_judge_step_compare_question'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configuration',
            name='turn_correction_prompt',
            field=models.ForeignKey(
                blank=True,
                help_text='Turn correction prompt for regenerating refused turns (only needed if refusal detection enabled)',
                limit_choices_to={'prompt_type': 'turn-correction'},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='configs_as_turn_correction',
                to='game.prompt'
            ),
        ),
        migrations.AlterField(
            model_name='configuration',
            name='turn_correction_model',
            field=models.ForeignKey(
                blank=True,
                help_text='Model to use for turn correction (only needed if refusal detection enabled)',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='configs_as_turn_correction',
                to='game.llmmodel'
            ),
        ),
    ]
