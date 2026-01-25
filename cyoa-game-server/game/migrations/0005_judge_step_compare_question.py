from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0004_judge_steps_and_audit_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='judgestep',
            name='compare_question',
            field=models.TextField(default='Is the revised turn better than the original?', help_text='Question asked to compare original vs rewritten turn'),
        ),
    ]
