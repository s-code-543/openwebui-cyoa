"""
URL configuration for admin interface.
"""
from django.urls import path
from . import admin_views

app_name = 'admin'

urlpatterns = [
    path('dashboard/', admin_views.dashboard, name='dashboard'),
    path('audit/', admin_views.audit_log, name='audit_log'),
    path('audit/<int:log_id>/', admin_views.audit_detail, name='audit_detail'),
    path('prompts/', admin_views.prompt_list, name='prompt_list'),
    path('prompts/new/', admin_views.prompt_editor, name='prompt_new'),
    path('prompts/<int:prompt_id>/', admin_views.prompt_editor, name='prompt_editor'),
    path('configurations/', admin_views.config_list, name='config_list'),
    path('configurations/new/', admin_views.config_editor, name='config_new'),
    path('configurations/<int:config_id>/', admin_views.config_editor, name='config_editor'),
    
    # API Provider Management
    path('providers/', admin_views.provider_list, name='provider_list'),
    path('providers/new/', admin_views.provider_editor, name='provider_new'),
    path('providers/<int:provider_id>/', admin_views.provider_editor, name='provider_editor'),
    
    # LLM Model Management
    path('models/', admin_views.model_list, name='model_list'),
    path('models/browse/<int:provider_id>/', admin_views.browse_provider_models, name='browse_provider_models'),
    path('models/import/', admin_views.import_models, name='import_models'),
    
    # API endpoints
    path('api/preview-markdown/', admin_views.preview_markdown, name='preview_markdown'),
    path('api/refresh-models/', admin_views.refresh_models, name='refresh_models'),
    path('api/test-provider/', admin_views.test_provider_connection, name='test_provider'),
    path('api/clear-audit-log/', admin_views.clear_audit_log, name='clear_audit_log'),
    path('api/reset-statistics/', admin_views.reset_statistics, name='reset_statistics'),
]
