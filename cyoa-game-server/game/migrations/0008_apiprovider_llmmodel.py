# Generated manually for API Provider and LLM Model management

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0007_configuration_pacing'),
    ]

    operations = [
        migrations.CreateModel(
            name='APIProvider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text="Friendly name for this provider (e.g., 'Office Ollama', 'My Anthropic')", max_length=200, unique=True)),
                ('provider_type', models.CharField(choices=[('ollama', 'Ollama Server'), ('anthropic', 'Anthropic (Claude)')], help_text='Type of API provider', max_length=50)),
                ('base_url', models.CharField(blank=True, help_text="Base URL for API (e.g., 'http://192.168.1.100:11434' for Ollama)", max_length=500)),
                ('api_key', models.CharField(blank=True, help_text='API key for authentication (if required)', max_length=500)),
                ('is_active', models.BooleanField(default=True, help_text='Whether this provider is currently active')),
                ('last_tested', models.DateTimeField(blank=True, help_text='Last time connection was successfully tested', null=True)),
                ('test_status', models.CharField(blank=True, help_text='Result of last connection test', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['provider_type', 'name'],
            },
        ),
        migrations.CreateModel(
            name='LLMModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Display name for this model (shown in config dropdowns)', max_length=200, unique=True)),
                ('model_identifier', models.CharField(help_text="Backend model identifier (e.g., 'qwen3:4b', 'claude-opus-4')", max_length=200)),
                ('source', models.CharField(choices=[('local_ollama', 'Local Ollama'), ('external', 'External Provider')], help_text='Where this model is hosted', max_length=50)),
                ('is_available', models.BooleanField(default=True, help_text='Whether this model is currently available for use')),
                ('capabilities', models.JSONField(blank=True, default=dict, help_text='Model capabilities and metadata')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('provider', models.ForeignKey(blank=True, help_text="External provider (if source is 'external')", null=True, on_delete=django.db.models.deletion.CASCADE, to='game.apiprovider')),
            ],
            options={
                'ordering': ['source', 'name'],
            },
        ),
    ]
