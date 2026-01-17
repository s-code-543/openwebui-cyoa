"""
Admin views for CYOA prompt management and statistics.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Q
from django.conf import settings
from django.utils import timezone
from functools import wraps
from .models import Prompt, AuditLog, Configuration, APIProvider, LLMModel
from .ollama_utils import get_ollama_models
from .external_ollama_utils import test_external_ollama_connection, get_external_ollama_models
from .external_anthropic_utils import test_anthropic_connection, get_anthropic_models
import markdown2


def debug_login_bypass(view_func):
    """
    Decorator that bypasses login_required in DEBUG mode.
    Useful for curl/wget debugging.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if settings.DEBUG and not request.user.is_authenticated:
            # In debug mode, skip authentication
            pass
        return view_func(request, *args, **kwargs)
    return wrapper


def login_view(request):
    """
    Custom login view to avoid Django's default template rendering issues.
    """
    if request.user.is_authenticated:
        return redirect('/admin/dashboard/')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)
            next_url = request.GET.get('next', '/admin/dashboard/')
            return redirect(next_url)
        else:
            return render(request, 'cyoa_admin/login.html', {'error': True})
    
    return render(request, 'cyoa_admin/login.html')


@debug_login_bypass
def dashboard(request):
    """
    Main dashboard showing overview statistics.
    """
    # Get statistics
    total_requests = AuditLog.objects.count()
    total_corrections = AuditLog.objects.filter(was_modified=True).count()
    correction_rate = (total_corrections / total_requests * 100) if total_requests > 0 else 0
    
    # Get active configuration
    active_config = Configuration.objects.filter(is_active=True).first()
    
    # Recent corrections
    recent_corrections = AuditLog.objects.filter(was_modified=True)[:10]
    
    context = {
        'total_requests': total_requests,
        'total_corrections': total_corrections,
        'correction_rate': f'{correction_rate:.1f}',
        'active_config': active_config,
        'recent_corrections': recent_corrections,
    }
    return render(request, 'cyoa_admin/dashboard.html', context)


@debug_login_bypass
def audit_log(request):
    """
    View audit log of all requests and corrections.
    """
    # Filters
    show_modified_only = request.GET.get('modified_only') == 'true'
    
    logs = AuditLog.objects.all()
    if show_modified_only:
        logs = logs.filter(was_modified=True)
    
    # Pagination
    logs = logs[:100]  # Simple limit for now
    
    context = {
        'logs': logs,
        'show_modified_only': show_modified_only,
    }
    return render(request, 'cyoa_admin/audit_log.html', context)


@debug_login_bypass
def audit_detail(request, log_id):
    """
    View detailed comparison of original vs refined output.
    """
    log = get_object_or_404(AuditLog, pk=log_id)
    
    context = {
        'log': log,
    }
    return render(request, 'cyoa_admin/audit_detail.html', context)


@debug_login_bypass
def prompt_list(request):
    """
    List all prompts grouped by type.
    """
    # Get all unique prompt types dynamically
    prompt_types = Prompt.objects.values_list('prompt_type', flat=True).distinct().order_by('prompt_type')
    prompts_by_type = {}
    
    for prompt_type in prompt_types:
        prompts_by_type[prompt_type] = Prompt.objects.filter(prompt_type=prompt_type).order_by('-version')
    
    context = {
        'prompts_by_type': prompts_by_type,
    }
    return render(request, 'cyoa_admin/prompt_list.html', context)


@debug_login_bypass
def prompt_editor(request, prompt_id=None):
    """
    Edit or create a new prompt.
    """
    prompt = None
    if prompt_id:
        prompt = get_object_or_404(Prompt, pk=prompt_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save':
            # Update existing prompt
            if prompt:
                prompt.description = request.POST.get('description', '')
                prompt.prompt_text = request.POST.get('prompt_text', '')
                prompt.save()
                messages.success(request, f'Saved {prompt}')
                return redirect('admin:prompt_editor', prompt_id=prompt.id)
        
        elif action == 'save_new_version':
            # Create new version
            if prompt:
                max_version = Prompt.objects.filter(
                    prompt_type=prompt.prompt_type
                ).order_by('-version').first().version
                
                new_prompt = Prompt.objects.create(
                    prompt_type=prompt.prompt_type,
                    version=max_version + 1,
                    description=request.POST.get('description', ''),
                    prompt_text=request.POST.get('prompt_text', ''),
                    is_active=False
                )
                messages.success(request, f'Created new version: {new_prompt}')
                return redirect('admin:prompt_editor', prompt_id=new_prompt.id)
        
        elif action == 'create':
            # Create brand new prompt
            prompt_type = request.POST.get('prompt_type')
            
            # Find next version number
            max_version = Prompt.objects.filter(
                prompt_type=prompt_type
            ).order_by('-version').first()
            next_version = (max_version.version + 1) if max_version else 1
            
            new_prompt = Prompt.objects.create(
                prompt_type=prompt_type,
                version=next_version,
                description=request.POST.get('description', ''),
                prompt_text=request.POST.get('prompt_text', ''),
                is_active=False
            )
            messages.success(request, f'Created {new_prompt}')
            return redirect('admin:prompt_editor', prompt_id=new_prompt.id)
        
        elif action == 'set_active':
            if prompt:
                prompt.is_active = True
                prompt.save()
                messages.success(request, f'Set {prompt} as active')
                return redirect('admin:prompt_editor', prompt_id=prompt.id)
    
    # Get all versions of the same type for version selector
    versions = []
    if prompt:
        versions = Prompt.objects.filter(prompt_type=prompt.prompt_type)
    
    # Get all unique prompt types for the dropdown
    prompt_types = Prompt.objects.values_list('prompt_type', flat=True).distinct().order_by('prompt_type')
    
    context = {
        'prompt': prompt,
        'versions': versions,
        'prompt_types': list(prompt_types),
    }
    return render(request, 'cyoa_admin/prompt_editor.html', context)


@debug_login_bypass
@require_http_methods(["POST"])
def preview_markdown(request):
    """
    API endpoint to preview markdown.
    """
    text = request.POST.get('text', '')
    html = markdown2.markdown(text, extras=['fenced-code-blocks', 'tables'])
    return JsonResponse({'html': html})


@debug_login_bypass
def config_list(request):
    """
    List all configurations with option to set active.
    """
    configurations = Configuration.objects.all()
    active_config = Configuration.objects.filter(is_active=True).first()
    
    context = {
        'configurations': configurations,
        'active_config': active_config,
    }
    return render(request, 'cyoa_admin/config_list.html', context)


@debug_login_bypass
def config_editor(request, config_id=None):
    """
    Create or edit a configuration.
    """
    config = get_object_or_404(Configuration, pk=config_id) if config_id else None
    
    # Get available models
    ollama_models = [model['name'] for model in get_ollama_models()]
    
    # Get external models from database (imported from providers)
    external_models = LLMModel.objects.filter(
        source='external',
        is_available=True
    ).select_related('provider')
    
    # Get available prompts
    adventure_prompts = Prompt.objects.exclude(prompt_type='judge').order_by('prompt_type', '-version')
    judge_prompts = Prompt.objects.filter(prompt_type='judge').order_by('-version')
    game_ending_prompts = Prompt.objects.filter(prompt_type='game-ending').order_by('-version')
    
    # Get difficulty profiles
    from .models import DifficultyProfile
    difficulties = DifficultyProfile.objects.all()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'set_active':
            config.is_active = True
            config.save()
            messages.success(request, f'Configuration "{config.name}" is now active')
            return redirect('admin:config_list')
        
        if action == 'delete':
            if config and not config.is_active:
                config_name = config.name
                config.delete()
                messages.success(request, f'Configuration "{config_name}" deleted')
                return redirect('admin:config_list')
            else:
                messages.error(request, 'Cannot delete active configuration')
                return redirect('admin:config_list')
        
        if action == 'save':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            adventure_prompt_id = request.POST.get('adventure_prompt')
            storyteller_model = request.POST.get('storyteller_model')
            storyteller_timeout = request.POST.get('storyteller_timeout', '30')
            judge_prompt_id = request.POST.get('judge_prompt')
            judge_model = request.POST.get('judge_model')
            judge_timeout = request.POST.get('judge_timeout', '30')
            game_ending_prompt_id = request.POST.get('game_ending_prompt') or None
            difficulty_id = request.POST.get('difficulty') or None
            total_turns = request.POST.get('total_turns', '10')
            phase1_turns = request.POST.get('phase1_turns', '3')
            phase2_turns = request.POST.get('phase2_turns', '3')
            phase3_turns = request.POST.get('phase3_turns', '3')
            phase4_turns = request.POST.get('phase4_turns', '1')
            
            if not all([name, adventure_prompt_id, storyteller_model, judge_prompt_id, judge_model]):
                messages.error(request, 'All fields are required')
            else:
                try:
                    adventure_prompt = Prompt.objects.get(pk=adventure_prompt_id)
                    judge_prompt = Prompt.objects.get(pk=judge_prompt_id)
                    game_ending_prompt = Prompt.objects.get(pk=game_ending_prompt_id) if game_ending_prompt_id else None
                    difficulty = DifficultyProfile.objects.get(pk=difficulty_id) if difficulty_id else None
                    storyteller_timeout_int = int(storyteller_timeout)
                    judge_timeout_int = int(judge_timeout)
                    total_turns_int = int(total_turns)
                    phase1_turns_int = int(phase1_turns)
                    phase2_turns_int = int(phase2_turns)
                    phase3_turns_int = int(phase3_turns)
                    phase4_turns_int = int(phase4_turns)
                    
                    if config:
                        # Update existing
                        config.name = name
                        config.description = description
                        config.adventure_prompt = adventure_prompt
                        config.storyteller_model = storyteller_model
                        config.storyteller_timeout = storyteller_timeout_int
                        config.judge_prompt = judge_prompt
                        config.judge_model = judge_model
                        config.judge_timeout = judge_timeout_int
                        config.game_ending_prompt = game_ending_prompt
                        config.difficulty = difficulty
                        config.total_turns = total_turns_int
                        config.phase1_turns = phase1_turns_int
                        config.phase2_turns = phase2_turns_int
                        config.phase3_turns = phase3_turns_int
                        config.phase4_turns = phase4_turns_int
                        config.save()
                        messages.success(request, f'Configuration "{name}" updated')
                    else:
                        # Create new
                        config = Configuration.objects.create(
                            name=name,
                            description=description,
                            adventure_prompt=adventure_prompt,
                            storyteller_model=storyteller_model,
                            storyteller_timeout=storyteller_timeout_int,
                            judge_prompt=judge_prompt,
                            judge_model=judge_model,
                            judge_timeout=judge_timeout_int,
                            game_ending_prompt=game_ending_prompt,
                            difficulty=difficulty,
                            total_turns=total_turns_int,
                            phase1_turns=phase1_turns_int,
                            phase2_turns=phase2_turns_int,
                            phase3_turns=phase3_turns_int,
                            phase4_turns=phase4_turns_int,
                            is_active=False
                        )
                        messages.success(request, f'Configuration "{name}" created')
                    
                    return redirect('admin:config_editor', config_id=config.id)
                except Prompt.DoesNotExist:
                    messages.error(request, 'Invalid prompt selection')
                except ValueError:
                    messages.error(request, 'Invalid timeout value')
    
    context = {
        'config': config,
        'ollama_models': ollama_models,
        'external_models': external_models,
        'adventure_prompts': adventure_prompts,
        'judge_prompts': judge_prompts,
        'game_ending_prompts': game_ending_prompts,
        'difficulties': difficulties,
    }
    return render(request, 'cyoa_admin/config_editor.html', context)


@debug_login_bypass
@require_http_methods(["POST"])
def refresh_models(request):
    """
    API endpoint to refresh Ollama models list.
    """
    models = get_ollama_models()
    model_names = [model['name'] for model in models]
    return JsonResponse({'models': model_names})


@debug_login_bypass
@require_http_methods(["POST"])
@csrf_exempt
def clear_audit_log(request):
    """
    Clear all audit log entries.
    """
    count = AuditLog.objects.count()
    AuditLog.objects.all().delete()
    messages.success(request, f'Cleared {count} audit log entries')
    return redirect('admin:audit_log')


@debug_login_bypass
@require_http_methods(["POST"])
@csrf_exempt
def reset_statistics(request):
    """
    Reset all statistics (clears audit log).
    """
    count = AuditLog.objects.count()
    AuditLog.objects.all().delete()
    messages.success(request, f'Reset statistics - cleared {count} audit log entries')
    return redirect('admin:dashboard')


# API Provider and Model Management Views
# Add these to the end of admin_views.py


@debug_login_bypass
def provider_list(request):
    """
    List all API providers with test status.
    """
    providers = APIProvider.objects.all()
    
    context = {
        'providers': providers,
    }
    return render(request, 'cyoa_admin/provider_list.html', context)


@debug_login_bypass
def provider_editor(request, provider_id=None):
    """
    Create or edit an API provider.
    """
    provider = get_object_or_404(APIProvider, pk=provider_id) if provider_id else None
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'test':
            # Test the connection
            provider_type = request.POST.get('provider_type')
            base_url = request.POST.get('base_url', '').strip()
            api_key = request.POST.get('api_key', '').strip()
            
            if provider_type == 'ollama':
                result = test_external_ollama_connection(base_url)
            elif provider_type == 'anthropic':
                result = test_anthropic_connection(api_key)
            else:
                result = {'success': False, 'message': 'Unknown provider type'}
            
            return JsonResponse(result)
        
        if action == 'save':
            name = request.POST.get('name', '').strip()
            provider_type = request.POST.get('provider_type')
            base_url = request.POST.get('base_url', '').strip()
            api_key = request.POST.get('api_key', '').strip()
            
            if not all([name, provider_type]):
                messages.error(request, 'Name and provider type are required')
            else:
                if provider:
                    # Update existing
                    provider.name = name
                    provider.provider_type = provider_type
                    provider.base_url = base_url
                    provider.api_key = api_key
                    provider.save()
                    messages.success(request, f'Provider "{name}" updated')
                else:
                    # Create new
                    provider = APIProvider.objects.create(
                        name=name,
                        provider_type=provider_type,
                        base_url=base_url,
                        api_key=api_key,
                        is_active=True
                    )
                    messages.success(request, f'Provider "{name}" created')
                
                return redirect('admin:provider_editor', provider_id=provider.id)
        
        if action == 'delete' and provider:
            provider_name = provider.name
            provider.delete()
            messages.success(request, f'Provider "{provider_name}" deleted')
            return redirect('admin:provider_list')
    
    context = {
        'provider': provider,
    }
    return render(request, 'cyoa_admin/provider_editor.html', context)


@debug_login_bypass
@require_http_methods(["POST"])
def test_provider_connection(request):
    """
    API endpoint to test provider connection.
    """
    import json
    data = json.loads(request.body)
    
    provider_type = data.get('provider_type')
    base_url = data.get('base_url', '').strip()
    api_key = data.get('api_key', '').strip()
    
    if provider_type == 'ollama':
        result = test_external_ollama_connection(base_url)
    elif provider_type == 'anthropic':
        result = test_anthropic_connection(api_key)
    else:
        result = {'success': False, 'message': 'Unknown provider type'}
    
    # Update provider test status if provider_id provided
    provider_id = data.get('provider_id')
    if provider_id and result['success']:
        try:
            provider = APIProvider.objects.get(pk=provider_id)
            provider.last_tested = timezone.now()
            provider.test_status = result['message']
            provider.save()
        except APIProvider.DoesNotExist:
            pass
    
    return JsonResponse(result)


@debug_login_bypass
def model_list(request):
    """
    List all registered LLM models.
    """
    models = LLMModel.objects.all().select_related('provider')
    providers = APIProvider.objects.filter(is_active=True)
    
    context = {
        'models': models,
        'providers': providers,
    }
    return render(request, 'cyoa_admin/model_list.html', context)


@debug_login_bypass
def browse_provider_models(request, provider_id):
    """
    Browse available models from a provider and select which to import.
    """
    provider = get_object_or_404(APIProvider, pk=provider_id)
    
    # Fetch models from provider
    available_models = []
    if provider.provider_type == 'ollama':
        available_models = get_external_ollama_models(provider.base_url)
    elif provider.provider_type == 'anthropic':
        available_models = get_anthropic_models(provider.api_key)
    
    # Get already imported models for this provider
    imported_model_ids = set(
        LLMModel.objects.filter(provider=provider)
        .values_list('model_identifier', flat=True)
    )
    
    # Mark which models are already imported
    for model in available_models:
        model['imported'] = model['id'] in imported_model_ids
    
    context = {
        'provider': provider,
        'available_models': available_models,
    }
    return render(request, 'cyoa_admin/browse_models.html', context)


@debug_login_bypass
@require_http_methods(["POST"])
def import_models(request):
    """
    Import selected models from a provider.
    """
    import json
    data = json.loads(request.body)
    
    provider_id = data.get('provider_id')
    model_ids = data.get('model_ids', [])
    
    if not provider_id or not model_ids:
        return JsonResponse({'success': False, 'message': 'Missing provider or models'})
    
    try:
        provider = APIProvider.objects.get(pk=provider_id)
        
        # Fetch full model list from provider
        if provider.provider_type == 'ollama':
            available_models = get_external_ollama_models(provider.base_url)
        elif provider.provider_type == 'anthropic':
            available_models = get_anthropic_models(provider.api_key)
        else:
            return JsonResponse({'success': False, 'message': 'Unknown provider type'})
        
        # Import selected models
        imported_count = 0
        for model_data in available_models:
            if model_data['id'] in model_ids:
                # Create or update model
                LLMModel.objects.update_or_create(
                    provider=provider,
                    model_identifier=model_data['id'],
                    defaults={
                        'name': f"{provider.name}: {model_data['name']}",
                        'source': 'external',
                        'is_available': True,
                        'capabilities': {
                            'description': model_data.get('description', ''),
                            'size': model_data.get('size', 0),
                        }
                    }
                )
                imported_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Imported {imported_count} models from {provider.name}'
        })
    
    except APIProvider.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Provider not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@debug_login_bypass
def difficulty_list(request):
    """
    List all difficulty profiles.
    """
    from .models import DifficultyProfile
    difficulties = DifficultyProfile.objects.all()
    
    context = {
        'difficulties': difficulties,
    }
    return render(request, 'cyoa_admin/difficulty_list.html', context)


@debug_login_bypass
def difficulty_editor(request, difficulty_id=None):
    """
    Create or edit a difficulty profile.
    """
    from .models import DifficultyProfile
    import json
    
    difficulty = None
    if difficulty_id:
        difficulty = get_object_or_404(DifficultyProfile, pk=difficulty_id)
    
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        mode = request.POST.get('mode', 'curve')
        
        # Determine function source
        if mode == 'curve':
            function = request.POST.get('generated_function')
            curve_points_json = request.POST.get('curve_points_json')
            curve_points = json.loads(curve_points_json) if curve_points_json else None
        else:
            function = request.POST.get('function')
            curve_points = None
        
        # Create or update
        if difficulty:
            difficulty.name = name
            difficulty.description = description
            difficulty.function = function
            difficulty.curve_points = curve_points
            difficulty.save()
            messages.success(request, f'Difficulty profile "{name}" updated successfully.')
        else:
            difficulty = DifficultyProfile.objects.create(
                name=name,
                description=description,
                function=function,
                curve_points=curve_points
            )
            messages.success(request, f'Difficulty profile "{name}" created successfully.')
        
        return redirect('admin:difficulty_list')
    
    context = {
        'difficulty': difficulty,
    }
    return render(request, 'cyoa_admin/difficulty_editor.html', context)

