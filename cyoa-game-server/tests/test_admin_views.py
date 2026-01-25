"""
Tests for admin_views.py - CYOA Admin Interface

This module tests all admin view functions including:
- Dashboard view and statistics
- Audit log viewing and management
- Prompt CRUD operations
- Configuration management
- API Provider management
- LLM Model management
- Difficulty profile management
- API endpoints (markdown preview, model refresh, etc.)

Test Categories:
- Unit tests: Individual function behavior with mocked dependencies
- Integration tests: Full request/response cycle with test database
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.test import Client

from game.models import (
    Prompt, AuditLog, Configuration, APIProvider, LLMModel,
    DifficultyProfile, JudgeStep
)
from tests.conftest import (
    PromptFactory, AuditLogFactory, ConfigurationFactory,
    APIProviderFactory, LLMModelFactory, DifficultyProfileFactory,
    JudgeStepFactory
)


# =============================================================================
# Dashboard Tests
# =============================================================================

@pytest.mark.django_db
class TestDashboard:
    """Tests for the dashboard view."""
    
    def test_dashboard_loads_successfully(self, client):
        """Dashboard page loads with 200 status."""
        response = client.get('/admin/dashboard/')
        assert response.status_code == 200
    
    def test_dashboard_shows_zero_stats_when_empty(self, client):
        """Dashboard shows zero statistics when no audit logs exist."""
        response = client.get('/admin/dashboard/')
        assert response.status_code == 200
        assert 'total_requests' in response.context
        assert response.context['total_requests'] == 0
    
    def test_dashboard_calculates_correction_rate(self, client, db):
        """Dashboard correctly calculates correction rate."""
        # Create 10 audit logs, 3 modified
        for i in range(7):
            AuditLogFactory(was_modified=False)
        for i in range(3):
            AuditLogFactory(was_modified=True)
        
        response = client.get('/admin/dashboard/')
        assert response.status_code == 200
        assert response.context['total_requests'] == 10
        assert response.context['total_corrections'] == 3
        assert response.context['correction_rate'] == '30.0'
    
    def test_dashboard_shows_recent_corrections(self, client, db):
        """Dashboard displays recent corrections in context."""
        # Create some modified audit logs
        logs = [AuditLogFactory(was_modified=True) for _ in range(5)]
        
        response = client.get('/admin/dashboard/')
        assert response.status_code == 200
        assert 'recent_corrections' in response.context
        assert len(response.context['recent_corrections']) == 5


# =============================================================================
# Audit Log Tests
# =============================================================================

@pytest.mark.django_db
class TestAuditLog:
    """Tests for audit log views."""
    
    def test_audit_log_list_loads(self, client):
        """Audit log list page loads successfully."""
        response = client.get('/admin/audit/')
        assert response.status_code == 200
    
    def test_audit_log_displays_entries(self, client, db):
        """Audit log page displays log entries."""
        logs = [AuditLogFactory() for _ in range(5)]
        
        response = client.get('/admin/audit/')
        assert response.status_code == 200
        assert 'logs' in response.context
        assert len(response.context['logs']) == 5
    
    def test_audit_log_filter_modified_only(self, client, db):
        """Audit log can filter to show only modified entries."""
        AuditLogFactory(was_modified=False)
        AuditLogFactory(was_modified=False)
        AuditLogFactory(was_modified=True)
        
        response = client.get('/admin/audit/?modified_only=true')
        assert response.status_code == 200
        assert len(response.context['logs']) == 1
        assert response.context['show_modified_only'] is True
    
    def test_audit_log_detail_view(self, client, db):
        """Audit log detail page displays specific log entry."""
        log = AuditLogFactory(
            original_text="Original text",
            refined_text="Refined text",
            was_modified=True
        )
        
        response = client.get(f'/admin/audit/{log.id}/')
        assert response.status_code == 200
        assert response.context['log'].id == log.id
    
    def test_audit_log_detail_404_for_nonexistent(self, client, db):
        """Audit log detail returns 404 for non-existent entry."""
        response = client.get('/admin/audit/99999/')
        assert response.status_code == 404


# =============================================================================
# Prompt Management Tests
# =============================================================================

@pytest.mark.django_db
class TestPromptList:
    """Tests for prompt listing."""
    
    def test_prompt_list_loads(self, client):
        """Prompt list page loads successfully."""
        response = client.get('/admin/prompts/')
        assert response.status_code == 200
    
    def test_prompt_list_groups_by_type(self, client, db):
        """Prompts are grouped by type in the listing."""
        PromptFactory(prompt_type='adventure', name='adventure1')
        PromptFactory(prompt_type='classifier', name='classifier1')
        PromptFactory(prompt_type='judge', name='judge1')
        
        response = client.get('/admin/prompts/')
        assert response.status_code == 200
        assert 'prompts_by_type' in response.context
    
    def test_prompt_list_shows_versions(self, client, db):
        """Multiple versions of the same prompt are grouped together."""
        PromptFactory(prompt_type='adventure', name='test-story', version=1)
        PromptFactory(prompt_type='adventure', name='test-story', version=2)
        PromptFactory(prompt_type='adventure', name='test-story', version=3)
        
        response = client.get('/admin/prompts/')
        assert response.status_code == 200


@pytest.mark.django_db
class TestPromptEditor:
    """Tests for prompt editing."""
    
    def test_prompt_editor_new_loads(self, client):
        """New prompt editor page loads successfully."""
        response = client.get('/admin/prompts/new/')
        assert response.status_code == 200
        assert response.context['prompt'] is None
    
    def test_prompt_editor_existing_loads(self, client, db):
        """Editor loads for existing prompt."""
        prompt = PromptFactory()
        
        response = client.get(f'/admin/prompts/{prompt.id}/')
        assert response.status_code == 200
        assert response.context['prompt'].id == prompt.id
    
    def test_prompt_editor_shows_versions(self, client, db):
        """Editor shows version selector for existing prompts."""
        prompt1 = PromptFactory(prompt_type='adventure', name='test', version=1)
        prompt2 = PromptFactory(prompt_type='adventure', name='test', version=2)
        
        response = client.get(f'/admin/prompts/{prompt2.id}/')
        assert response.status_code == 200
        assert len(response.context['versions']) == 2
    
    def test_create_new_prompt(self, client, db):
        """Create a brand new prompt."""
        response = client.post('/admin/prompts/new/', {
            'action': 'create',
            'prompt_type': 'adventure',
            'name': 'new-adventure',
            'description': 'A new adventure prompt',
            'prompt_text': 'You are a storyteller...',
        })
        
        # Should redirect after creation
        assert response.status_code == 302
        
        # Verify prompt was created
        prompt = Prompt.objects.get(name='new-adventure')
        assert prompt.prompt_type == 'adventure'
        assert prompt.version == 1
    
    def test_create_prompt_increments_version(self, client, db):
        """Creating a prompt with existing name increments version."""
        PromptFactory(prompt_type='adventure', name='existing', version=1)
        
        response = client.post('/admin/prompts/new/', {
            'action': 'create',
            'prompt_type': 'adventure',
            'name': 'existing',
            'description': 'New version',
            'prompt_text': 'Updated content...',
        })
        
        assert response.status_code == 302
        prompt = Prompt.objects.filter(name='existing').order_by('-version').first()
        assert prompt.version == 2
    
    def test_save_existing_prompt(self, client, db):
        """Save changes to an existing prompt."""
        prompt = PromptFactory(description='Old description')
        
        response = client.post(f'/admin/prompts/{prompt.id}/', {
            'action': 'save',
            'description': 'New description',
            'prompt_text': 'Updated text',
        })
        
        assert response.status_code == 302
        prompt.refresh_from_db()
        assert prompt.description == 'New description'
    
    def test_save_new_version(self, client, db):
        """Save as new version creates new prompt entry."""
        prompt = PromptFactory(prompt_type='adventure', name='test', version=1)
        
        response = client.post(f'/admin/prompts/{prompt.id}/', {
            'action': 'save_new_version',
            'description': 'Version 2 description',
            'prompt_text': 'Version 2 content',
        })
        
        assert response.status_code == 302
        new_prompt = Prompt.objects.filter(name='test').order_by('-version').first()
        assert new_prompt.version == 2
        assert new_prompt.description == 'Version 2 description'
    
    def test_create_prompt_requires_name(self, client, db):
        """Creating a prompt without name shows error."""
        response = client.post('/admin/prompts/new/', {
            'action': 'create',
            'prompt_type': 'adventure',
            'name': '',
            'prompt_text': 'Some content',
        })
        
        # Should not redirect (stays on page with error)
        assert response.status_code == 200


# =============================================================================
# Configuration Management Tests
# =============================================================================

@pytest.mark.django_db
class TestConfigList:
    """Tests for configuration listing."""
    
    def test_config_list_loads(self, client, mock_ollama_models):
        """Configuration list page loads successfully."""
        response = client.get('/admin/configurations/')
        assert response.status_code == 200
    
    def test_config_list_shows_configurations(self, client, db, configuration, mock_ollama_models):
        """Configuration list displays existing configurations."""
        response = client.get('/admin/configurations/')
        assert response.status_code == 200
        assert len(response.context['configurations']) >= 1


@pytest.mark.django_db
class TestConfigEditor:
    """Tests for configuration editing."""
    
    def test_config_editor_new_loads(self, client, mock_ollama_models):
        """New configuration editor loads successfully."""
        response = client.get('/admin/configurations/new/')
        assert response.status_code == 200
        assert response.context['config'] is None
    
    def test_config_editor_existing_loads(self, client, db, configuration, mock_ollama_models):
        """Configuration editor loads for existing config."""
        response = client.get(f'/admin/configurations/{configuration.id}/')
        assert response.status_code == 200
        assert response.context['config'].id == configuration.id
    
    def test_config_editor_shows_available_prompts(self, client, db, mock_ollama_models):
        """Config editor shows available prompts by type."""
        PromptFactory(prompt_type='adventure')
        PromptFactory(prompt_type='classifier')
        PromptFactory(prompt_type='turn-correction')
        
        response = client.get('/admin/configurations/new/')
        assert response.status_code == 200
        assert 'adventure_prompts' in response.context
        assert 'classifier_prompts' in response.context
    
    def test_config_editor_shows_judge_steps(self, client, db, configuration, mock_ollama_models):
        """Config editor shows judge steps for existing config."""
        JudgeStepFactory(configuration=configuration)
        JudgeStepFactory(configuration=configuration)
        
        response = client.get(f'/admin/configurations/{configuration.id}/')
        assert response.status_code == 200
        assert len(response.context['judge_steps']) == 2


# =============================================================================
# API Provider Management Tests
# =============================================================================

@pytest.mark.django_db
class TestProviderList:
    """Tests for API provider listing."""
    
    def test_provider_list_loads(self, client):
        """Provider list page loads successfully."""
        response = client.get('/admin/providers/')
        assert response.status_code == 200
    
    def test_provider_list_shows_providers(self, client, db, api_provider):
        """Provider list displays existing providers."""
        response = client.get('/admin/providers/')
        assert response.status_code == 200
        assert len(response.context['providers']) >= 1


@pytest.mark.django_db
class TestProviderEditor:
    """Tests for API provider editing."""
    
    def test_provider_editor_new_loads(self, client):
        """New provider editor loads successfully."""
        response = client.get('/admin/providers/new/')
        assert response.status_code == 200
    
    def test_provider_editor_existing_loads(self, client, db, api_provider):
        """Provider editor loads for existing provider."""
        response = client.get(f'/admin/providers/{api_provider.id}/')
        assert response.status_code == 200
        assert response.context['provider'].id == api_provider.id


@pytest.mark.django_db
class TestProviderConnectionTest:
    """Tests for provider connection testing API."""
    
    def test_test_ollama_connection(self, client, mock_ollama_connection):
        """Test Ollama connection API endpoint."""
        response = client.post(
            '/admin/api/test-provider/',
            data=json.dumps({
                'provider_type': 'ollama',
                'base_url': 'http://localhost:11434',
                'api_key': ''
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
    
    def test_test_anthropic_connection(self, client, mock_anthropic_connection):
        """Test Anthropic connection API endpoint."""
        response = client.post(
            '/admin/api/test-provider/',
            data=json.dumps({
                'provider_type': 'anthropic',
                'base_url': '',
                'api_key': 'test-key'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
    
    def test_test_openai_connection(self, client, mock_openai_connection):
        """Test OpenAI connection API endpoint."""
        response = client.post(
            '/admin/api/test-provider/',
            data=json.dumps({
                'provider_type': 'openai',
                'base_url': '',
                'api_key': 'test-key'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
    
    def test_test_openrouter_connection(self, client, mock_openrouter_connection):
        """Test OpenRouter connection API endpoint."""
        response = client.post(
            '/admin/api/test-provider/',
            data=json.dumps({
                'provider_type': 'openrouter',
                'base_url': '',
                'api_key': 'test-key'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True


# =============================================================================
# LLM Model Management Tests
# =============================================================================

@pytest.mark.django_db
class TestModelList:
    """Tests for LLM model listing."""
    
    def test_model_list_loads(self, client):
        """Model list page loads successfully."""
        response = client.get('/admin/models/')
        assert response.status_code == 200
    
    def test_model_list_shows_models(self, client, db, llm_model):
        """Model list displays existing models."""
        response = client.get('/admin/models/')
        assert response.status_code == 200
        assert len(response.context['models']) >= 1


@pytest.mark.django_db
class TestBrowseProviderModels:
    """Tests for browsing available models from a provider."""
    
    def test_browse_ollama_models(self, client, db, api_provider, mock_ollama_models):
        """Browse models from Ollama provider."""
        api_provider.provider_type = 'ollama'
        api_provider.save()
        
        response = client.get(f'/admin/models/browse/{api_provider.id}/')
        assert response.status_code == 200
        assert 'available_models' in response.context
    
    def test_browse_anthropic_models(self, client, db, mock_anthropic_models):
        """Browse models from Anthropic provider."""
        provider = APIProviderFactory(provider_type='anthropic', api_key='test-key')
        
        response = client.get(f'/admin/models/browse/{provider.id}/')
        assert response.status_code == 200
    
    def test_browse_openai_models(self, client, db, mock_openai_models):
        """Browse models from OpenAI provider."""
        provider = APIProviderFactory(provider_type='openai', api_key='test-key')
        
        response = client.get(f'/admin/models/browse/{provider.id}/')
        assert response.status_code == 200
    
    def test_browse_openrouter_models(self, client, db, mock_openrouter_models):
        """Browse models from OpenRouter provider."""
        provider = APIProviderFactory(provider_type='openrouter', api_key='test-key')
        
        response = client.get(f'/admin/models/browse/{provider.id}/')
        assert response.status_code == 200


@pytest.mark.django_db
class TestImportModels:
    """Tests for importing models from providers."""
    
    def test_import_models_success(self, client, db, api_provider, mock_ollama_models):
        """Import selected models from provider."""
        response = client.post(
            '/admin/models/import/',
            data=json.dumps({
                'provider_id': api_provider.id,
                'model_ids': ['llama3:8b', 'qwen:4b']
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert data['imported'] == 2
        
        # Verify models were created
        assert LLMModel.objects.filter(provider=api_provider).count() == 2
    
    def test_import_models_missing_provider(self, client, db):
        """Import models fails with missing provider ID."""
        response = client.post(
            '/admin/models/import/',
            data=json.dumps({
                'provider_id': None,
                'model_ids': ['test']
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'error' in data


@pytest.mark.django_db
class TestRemoveModels:
    """Tests for removing models."""
    
    def test_remove_models_success(self, client, db, api_provider):
        """Remove selected models from database."""
        model1 = LLMModelFactory(provider=api_provider, model_identifier='model1')
        model2 = LLMModelFactory(provider=api_provider, model_identifier='model2')
        
        response = client.post(
            '/admin/models/remove/',
            data=json.dumps({
                'provider_id': api_provider.id,
                'model_ids': ['model1']
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        
        # Verify only one model remains
        assert LLMModel.objects.filter(provider=api_provider).count() == 1


@pytest.mark.django_db
class TestDeleteModel:
    """Tests for deleting individual models."""
    
    def test_delete_model_success(self, client, db, llm_model):
        """Delete a single model."""
        model_id = llm_model.id
        
        response = client.post(f'/admin/models/{model_id}/delete/')
        assert response.status_code == 302  # Redirect after delete
        
        # Verify model was deleted
        assert not LLMModel.objects.filter(id=model_id).exists()
    
    def test_delete_model_in_use_fails(self, client, db, configuration):
        """Cannot delete a model that is in use by a configuration."""
        model = configuration.storyteller_model
        
        response = client.post(f'/admin/models/{model.id}/delete/')
        # Should redirect with error message
        assert response.status_code == 302
        
        # Model should still exist
        assert LLMModel.objects.filter(id=model.id).exists()


# =============================================================================
# Difficulty Profile Management Tests
# =============================================================================

@pytest.mark.django_db
class TestDifficultyList:
    """Tests for difficulty profile listing."""
    
    def test_difficulty_list_loads(self, client):
        """Difficulty list page loads successfully."""
        response = client.get('/admin/difficulty/')
        assert response.status_code == 200
    
    def test_difficulty_list_shows_profiles(self, client, db, difficulty_profile):
        """Difficulty list displays existing profiles."""
        response = client.get('/admin/difficulty/')
        assert response.status_code == 200
        assert len(response.context['difficulties']) >= 1


@pytest.mark.django_db
class TestDifficultyEditor:
    """Tests for difficulty profile editing."""
    
    def test_difficulty_editor_new_loads(self, client):
        """New difficulty editor loads successfully."""
        response = client.get('/admin/difficulty/new/')
        assert response.status_code == 200
    
    def test_difficulty_editor_existing_loads(self, client, db, difficulty_profile):
        """Difficulty editor loads for existing profile."""
        response = client.get(f'/admin/difficulty/{difficulty_profile.id}/')
        assert response.status_code == 200
        assert response.context['difficulty'].id == difficulty_profile.id
    
    def test_create_difficulty_profile(self, client, db):
        """Create a new difficulty profile."""
        response = client.post('/admin/difficulty/new/', {
            'action': 'save',
            'name': 'Hard Mode',
            'description': 'Very difficult',
            'function': '0.1 + 0.5 * (x/n)**2',
        })
        
        assert response.status_code == 302
        assert DifficultyProfile.objects.filter(name='Hard Mode').exists()
    
    def test_update_difficulty_profile(self, client, db, difficulty_profile):
        """Update an existing difficulty profile."""
        response = client.post(f'/admin/difficulty/{difficulty_profile.id}/', {
            'action': 'save',
            'name': difficulty_profile.name,
            'description': 'Updated description',
            'function': '0.2 + 0.3 * (x/n)',
        })
        
        assert response.status_code == 302
        difficulty_profile.refresh_from_db()
        assert difficulty_profile.description == 'Updated description'


# =============================================================================
# API Endpoint Tests
# =============================================================================

@pytest.mark.django_db
class TestPreviewMarkdown:
    """Tests for markdown preview API."""
    
    def test_preview_markdown_basic(self, client):
        """Preview markdown converts to HTML."""
        response = client.post('/admin/api/preview-markdown/', {
            'text': '# Hello World\n\nThis is **bold** text.'
        })
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert '<h1>' in data['html']
        assert '<strong>bold</strong>' in data['html']
    
    def test_preview_markdown_code_blocks(self, client):
        """Preview markdown handles code blocks."""
        response = client.post('/admin/api/preview-markdown/', {
            'text': '```python\nprint("hello")\n```'
        })
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'print' in data['html']
    
    def test_preview_markdown_empty(self, client):
        """Preview markdown handles empty input."""
        response = client.post('/admin/api/preview-markdown/', {
            'text': ''
        })
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['html'] == ''


@pytest.mark.django_db
class TestRefreshModels:
    """Tests for model refresh API."""
    
    def test_refresh_models_ollama(self, client, mock_ollama_models):
        """Refresh models from Ollama."""
        response = client.post('/admin/api/refresh-models/')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'models' in data
        assert 'llama3:8b' in data['models']


@pytest.mark.django_db
class TestClearAuditLog:
    """Tests for clearing audit log."""
    
    def test_clear_audit_log_success(self, client, db):
        """Clear all audit log entries."""
        AuditLogFactory()
        AuditLogFactory()
        AuditLogFactory()
        
        assert AuditLog.objects.count() == 3
        
        response = client.post('/admin/api/clear-audit-log/')
        assert response.status_code == 302  # Redirect
        assert AuditLog.objects.count() == 0


@pytest.mark.django_db
class TestResetStatistics:
    """Tests for resetting statistics."""
    
    def test_reset_statistics_clears_audit_log(self, client, db):
        """Reset statistics clears the audit log."""
        AuditLogFactory()
        AuditLogFactory()
        
        response = client.post('/admin/api/reset-statistics/')
        assert response.status_code == 302  # Redirect
        assert AuditLog.objects.count() == 0


# =============================================================================
# Login and Authentication Tests
# =============================================================================

@pytest.mark.django_db
class TestLoginView:
    """Tests for login functionality."""
    
    def test_login_page_loads(self, client):
        """Login page loads successfully."""
        response = client.get('/admin/dashboard/')
        # In DEBUG mode, should load without redirect
        # (due to debug_login_bypass decorator)
        assert response.status_code == 200
    
    def test_login_redirects_authenticated_user(self, client, authenticated_client):
        """Authenticated users accessing login are redirected."""
        # Using the authenticated_client fixture
        response = authenticated_client.get('/admin/')
        assert response.status_code == 302


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

@pytest.mark.django_db
class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_nonexistent_prompt_returns_404(self, client):
        """Accessing non-existent prompt returns 404."""
        response = client.get('/admin/prompts/99999/')
        assert response.status_code == 404
    
    def test_nonexistent_config_returns_404(self, client, mock_ollama_models):
        """Accessing non-existent configuration returns 404."""
        response = client.get('/admin/configurations/99999/')
        assert response.status_code == 404
    
    def test_nonexistent_provider_returns_404(self, client):
        """Accessing non-existent provider returns 404."""
        response = client.get('/admin/providers/99999/')
        assert response.status_code == 404
    
    def test_nonexistent_difficulty_returns_404(self, client):
        """Accessing non-existent difficulty returns 404."""
        response = client.get('/admin/difficulty/99999/')
        assert response.status_code == 404


# =============================================================================
# Integration Tests - Full Request Flows
# =============================================================================

@pytest.mark.django_db
@pytest.mark.integration
class TestFullPromptWorkflow:
    """Integration tests for complete prompt management workflow."""
    
    def test_create_edit_version_prompt_workflow(self, client, db):
        """Full workflow: create, edit, then create new version of a prompt."""
        # Step 1: Create new prompt
        response = client.post('/admin/prompts/new/', {
            'action': 'create',
            'prompt_type': 'adventure',
            'name': 'workflow-test',
            'description': 'Version 1',
            'prompt_text': 'Original content',
        })
        assert response.status_code == 302
        
        prompt = Prompt.objects.get(name='workflow-test')
        assert prompt.version == 1
        
        # Step 2: Edit the prompt
        response = client.post(f'/admin/prompts/{prompt.id}/', {
            'action': 'save',
            'description': 'Updated v1',
            'prompt_text': 'Updated content',
        })
        assert response.status_code == 302
        
        prompt.refresh_from_db()
        assert prompt.description == 'Updated v1'
        
        # Step 3: Create new version
        response = client.post(f'/admin/prompts/{prompt.id}/', {
            'action': 'save_new_version',
            'description': 'Version 2',
            'prompt_text': 'V2 content',
        })
        assert response.status_code == 302
        
        # Verify we have 2 versions
        versions = Prompt.objects.filter(name='workflow-test').order_by('version')
        assert versions.count() == 2
        assert versions[0].version == 1
        assert versions[1].version == 2


@pytest.mark.django_db
@pytest.mark.integration
class TestFullProviderModelWorkflow:
    """Integration tests for provider and model management workflow."""
    
    def test_create_provider_import_models_workflow(self, client, db, mock_ollama_connection, mock_ollama_models):
        """Full workflow: create provider, test connection, import models."""
        # Step 1: Create provider
        response = client.post('/admin/providers/new/', {
            'action': 'save',
            'name': 'Test Ollama',
            'provider_type': 'ollama',
            'base_url': 'http://localhost:11434',
            'is_local': 'on',
            'is_active': 'on',
        })
        assert response.status_code == 302
        
        provider = APIProvider.objects.get(name='Test Ollama')
        
        # Step 2: Test connection
        response = client.post(
            '/admin/api/test-provider/',
            data=json.dumps({
                'provider_type': 'ollama',
                'base_url': 'http://localhost:11434',
                'api_key': '',
                'provider_id': provider.id
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        
        # Step 3: Import models
        response = client.post(
            '/admin/models/import/',
            data=json.dumps({
                'provider_id': provider.id,
                'model_ids': ['llama3:8b']
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        
        # Verify model was imported
        model = LLMModel.objects.get(provider=provider, model_identifier='llama3:8b')
        assert model.is_available is True
