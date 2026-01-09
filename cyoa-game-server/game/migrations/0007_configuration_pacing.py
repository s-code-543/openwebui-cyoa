# Generated manually for turn-based pacing configuration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0006_configuration_storyteller_timeout'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuration',
            name='total_turns',
            field=models.IntegerField(choices=[(5, '5 turns'), (10, '10 turns'), (15, '15 turns'), (20, '20 turns')], default=10, help_text='Total number of turns in the adventure'),
        ),
        migrations.AddField(
            model_name='configuration',
            name='phase1_turns',
            field=models.IntegerField(default=3, help_text='Turns for Phase 1: Introduction/Exposition/Story Building'),
        ),
        migrations.AddField(
            model_name='configuration',
            name='phase2_turns',
            field=models.IntegerField(default=3, help_text='Turns for Phase 2: Victory/Loss Conditions'),
        ),
        migrations.AddField(
            model_name='configuration',
            name='phase3_turns',
            field=models.IntegerField(default=3, help_text='Turns for Phase 3: Progress/Narrative Twists'),
        ),
        migrations.AddField(
            model_name='configuration',
            name='phase4_turns',
            field=models.IntegerField(default=1, help_text='Turns for Phase 4: Finale/Conclusion Setup'),
        ),
    ]
