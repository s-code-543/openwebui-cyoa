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
from django.db.models.deletion import ProtectedError
from django.conf import settings
from django.utils import timezone
from functools import wraps
from .models import Prompt, AuditLog, Configuration, APIProvider, LLMModel, JudgeStep
from .ollama_utils import get_ollama_models, test_ollama_connection
from .anthropic_utils import test_anthropic_connection, get_anthropic_models
from .openai_utils import test_openai_connection, get_openai_models
from .openrouter_utils import test_openrouter_connection, get_openrouter_models
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
    
    # Recent corrections
    recent_corrections = AuditLog.objects.filter(was_modified=True)[:10]
    
    context = {
        'total_requests': total_requests,
        'total_corrections': total_corrections,
        'correction_rate': f'{correction_rate:.1f}',
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
    List all prompts grouped by type, then by name, with versions collapsed.
    """
    # Get all unique prompt types dynamically
    prompt_types = Prompt.objects.values_list('prompt_type', flat=True).distinct().order_by('prompt_type')
    
    # Structure: { type_display_name: { 'type_code': code, 'prompts': { name: [versions] } } }
    prompts_by_type = {}
    
    for prompt_type in prompt_types:
        display_name = Prompt.get_type_display_name(prompt_type)
        prompts = Prompt.objects.filter(prompt_type=prompt_type).order_by('name', '-version')
        
        # Group by name
        prompts_by_name = {}
        for prompt in prompts:
            if prompt.name not in prompts_by_name:
                prompts_by_name[prompt.name] = []
            prompts_by_name[prompt.name].append(prompt)
        
        prompts_by_type[display_name] = {
            'type_code': prompt_type,
            'prompts_by_name': prompts_by_name,
        }
    
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
            # Create new version of the same prompt name
            if prompt:
                max_version = Prompt.objects.filter(
                    prompt_type=prompt.prompt_type,
                    name=prompt.name
                ).order_by('-version').first().version
                
                new_prompt = Prompt.objects.create(
                    prompt_type=prompt.prompt_type,
                    name=prompt.name,
                    version=max_version + 1,
                    description=request.POST.get('description', ''),
                    prompt_text=request.POST.get('prompt_text', ''),
                )
                messages.success(request, f'Created new version: {new_prompt}')
                return redirect('admin:prompt_editor', prompt_id=new_prompt.id)
        
        elif action == 'create':
            # Create brand new prompt
            prompt_type = request.POST.get('prompt_type')
            name = request.POST.get('name', '').strip()
            
            if not name:
                messages.error(request, 'Prompt name is required')
            else:
                # Check if a prompt with this name already exists for version handling
                existing = Prompt.objects.filter(
                    prompt_type=prompt_type,
                    name=name
                ).order_by('-version').first()
                next_version = (existing.version + 1) if existing else 1
                
                new_prompt = Prompt.objects.create(
                    prompt_type=prompt_type,
                    name=name,
                    version=next_version,
                    description=request.POST.get('description', ''),
                    prompt_text=request.POST.get('prompt_text', ''),
                )
                messages.success(request, f'Created {new_prompt}')
                return redirect('admin:prompt_editor', prompt_id=new_prompt.id)
        
        elif action == 'save_to_disk':
            # Write prompt to file on disk
            if prompt:
                try:
                    result = save_prompt_to_disk(prompt)
                    messages.success(request, result)
                except Exception as e:
                    messages.error(request, f'Failed to save to disk: {e}')
                return redirect('admin:prompt_editor', prompt_id=prompt.id)
    
    # Get all versions of the same prompt name for version selector
    versions = []
    if prompt:
        versions = Prompt.objects.filter(
            prompt_type=prompt.prompt_type,
            name=prompt.name
        ).order_by('-version')
    
    # Define available prompt types
    prompt_type_choices = [
        ('adventure', 'Adventure Prompt'),
        ('turn-correction', 'Turn Correction Prompt'),
        ('game-ending', 'Game Ending Prompt'),
        ('classifier', 'Classifier Prompt'),
        ('judge', 'Judge Prompt'),
    ]
    
    context = {
        'prompt': prompt,
        'versions': versions,
        'prompt_types': prompt_type_choices,
    }
    return render(request, 'cyoa_admin/prompt_editor.html', context)


def save_prompt_to_disk(prompt):
    """
    Write a prompt to its corresponding .txt file on disk.
    Creates the file if it doesn't exist, or overwrites if it does.
    Returns a success message.
    """
    import os
    
    # Determine base directory
    if os.path.exists('/story_prompts'):
        base_dir = '/story_prompts'
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        base_dir = os.path.join(project_root, 'cyoa_prompts')
    
    # Map prompt type to directory
    type_to_dir = {
        'adventure': 'story_prompts',
        'turn-correction': 'turn_correction_prompts',
        'game-ending': 'game_ending_prompts',
        'classifier': 'classifier_prompts',
        'judge': 'judge_prompts',
    }
    
    dir_name = type_to_dir.get(prompt.prompt_type)
    if not dir_name:
        raise ValueError(f"Unknown prompt type: {prompt.prompt_type}")
    
    # Build filename with version
    filename = f"{prompt.name}_v{prompt.version}.txt"
    filepath = os.path.join(base_dir, dir_name, filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Write content
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(prompt.prompt_text)
    
    # Update file_path in model
    relative_path = f"{dir_name}/{filename}"
    prompt.file_path = relative_path
    prompt.save(update_fields=['file_path'])
    
    return f'Saved to {relative_path}'


@debug_login_bypass
@require_http_methods(["POST"])
def preview_markdown(request):
    """
    API endpoint to preview markdown.
    """
    text = request.POST.get('text', '')
    if not text.strip():
        html = ''
    else:
        html = markdown2.markdown(text, extras=['fenced-code-blocks', 'tables'])
    return JsonResponse({'html': html})


@debug_login_bypass
def config_list(request):
    """
    List all configurations.
    """
    configurations = Configuration.objects.all()
    
    context = {
        'configurations': configurations,
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
    
    # Get all models from database (imported from providers)
    external_models = LLMModel.objects.filter(
        is_available=True
    ).select_related('provider')
    
    # Get available prompts by type
    adventure_prompts = Prompt.objects.filter(prompt_type='adventure').order_by('name', '-version')
    turn_correction_prompts = Prompt.objects.filter(prompt_type='turn-correction').order_by('name', '-version')
    game_ending_prompts = Prompt.objects.filter(prompt_type='game-ending').order_by('name', '-version')
    classifier_prompts = Prompt.objects.filter(prompt_type='classifier').order_by('name', '-version')
    judge_prompts = Prompt.objects.filter(prompt_type='judge').order_by('name', '-version')
    
    # Get difficulty profiles
    from .models import DifficultyProfile
    difficulties = DifficultyProfile.objects.all()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'delete':
            if config:
                config_name = config.name
                config.delete()
                messages.success(request, f'Configuration "{config_name}" deleted')
                return redirect('admin:config_list')
        
        if action == 'save':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            adventure_prompt_id = request.POST.get('adventure_prompt')
            storyteller_model_id = request.POST.get('storyteller_model')
            storyteller_timeout = request.POST.get('storyteller_timeout', '30')
            turn_correction_prompt_id = request.POST.get('turn_correction_prompt')
            turn_correction_model_id = request.POST.get('turn_correction_model')
            turn_correction_timeout = request.POST.get('turn_correction_timeout', '30')
            game_ending_turn_correction_prompt_id = request.POST.get('game_ending_turn_correction_prompt') or None
            game_ending_prompt_id = request.POST.get('game_ending_prompt')
            difficulty_id = request.POST.get('difficulty') or None
            total_turns = request.POST.get('total_turns', '10')
            phase1_turns = request.POST.get('phase1_turns', '3')
            phase2_turns = request.POST.get('phase2_turns', '3')
            phase3_turns = request.POST.get('phase3_turns', '3')
            phase4_turns = request.POST.get('phase4_turns', '1')
            enable_refusal_detection = request.POST.get('enable_refusal_detection') == '1'
            classifier_prompt_id = request.POST.get('classifier_prompt') or None
            classifier_model_id = request.POST.get('classifier_model') or None
            classifier_timeout = request.POST.get('classifier_timeout', '10')
            classifier_question = request.POST.get('classifier_question', 'Is this a content policy refusal?')

            judge_steps_count = int(request.POST.get('judge_steps_count', '0') or 0)
            judge_steps_data = []
            for idx in range(judge_steps_count):
                prefix = f"judge_steps-{idx}-"
                step_id = request.POST.get(prefix + 'id') or None
                deleted = request.POST.get(prefix + 'deleted') == '1'
                if deleted:
                    judge_steps_data.append({'id': step_id, 'deleted': True})
                    continue
                judge_steps_data.append({
                    'id': step_id,
                    'deleted': False,
                    'order': idx,
                    'name': request.POST.get(prefix + 'name', '').strip() or f"Step {idx + 1}",
                    'enabled': request.POST.get(prefix + 'enabled') == '1',
                    # Classifier phase (optional)
                    'classifier_prompt_id': request.POST.get(prefix + 'classifier_prompt') or None,
                    'classifier_model_id': request.POST.get(prefix + 'classifier_model') or None,
                    'classifier_timeout': request.POST.get(prefix + 'classifier_timeout', '10'),
                    'classifier_question': request.POST.get(prefix + 'classifier_question', 'Does this turn have issues?').strip(),
                    'classifier_use_full_context': request.POST.get(prefix + 'classifier_use_full_context') == '1',
                    # Rewrite phase
                    'rewrite_prompt_id': request.POST.get(prefix + 'rewrite_prompt') or None,
                    'rewrite_model_id': request.POST.get(prefix + 'rewrite_model') or None,
                    'rewrite_timeout': request.POST.get(prefix + 'rewrite_timeout', '30'),
                    'rewrite_instruction': request.POST.get(prefix + 'rewrite_instruction', '').strip(),
                    'rewrite_use_full_context': request.POST.get(prefix + 'rewrite_use_full_context') == '1',
                    'max_rewrite_attempts': request.POST.get(prefix + 'max_rewrite_attempts', '3'),
                    # Compare phase
                    'compare_prompt_id': request.POST.get(prefix + 'compare_prompt') or None,
                    'compare_model_id': request.POST.get(prefix + 'compare_model') or None,
                    'compare_timeout': request.POST.get(prefix + 'compare_timeout', '15'),
                    'compare_question': request.POST.get(prefix + 'compare_question', 'Is the revised turn better than the original?').strip(),
                    'compare_use_full_context': request.POST.get(prefix + 'compare_use_full_context') == '1',
                })
            
            # Build list of missing required fields
            missing_fields = []
            if not name:
                missing_fields.append('Configuration Name')
            if not adventure_prompt_id:
                missing_fields.append('Adventure Prompt')
            if not storyteller_model_id:
                missing_fields.append('Storyteller Model')
            if not game_ending_prompt_id:
                missing_fields.append('Game Ending Prompt')
            
            # Only validate refusal detection fields if enabled
            if enable_refusal_detection:
                if not turn_correction_prompt_id:
                    missing_fields.append('Turn Correction Prompt')
                if not turn_correction_model_id:
                    missing_fields.append('Turn Correction Model')
                if not classifier_prompt_id:
                    missing_fields.append('Classifier Prompt')
                if not classifier_model_id:
                    missing_fields.append('Classifier Model')
            
            if missing_fields:
                error_msg = 'Missing required fields: ' + ', '.join(missing_fields)
                messages.error(request, error_msg)
            else:
                try:
                    adventure_prompt = Prompt.objects.get(pk=adventure_prompt_id)
                    game_ending_prompt = Prompt.objects.get(pk=game_ending_prompt_id)
                    storyteller_model = LLMModel.objects.get(pk=storyteller_model_id)
                    
                    # Only fetch refusal detection related objects if enabled
                    if enable_refusal_detection:
                        turn_correction_prompt = Prompt.objects.get(pk=turn_correction_prompt_id)
                        turn_correction_model = LLMModel.objects.get(pk=turn_correction_model_id)
                        classifier_prompt = Prompt.objects.get(pk=classifier_prompt_id)
                        classifier_model = LLMModel.objects.get(pk=classifier_model_id)
                    else:
                        # Set to None when disabled
                        turn_correction_prompt = None
                        turn_correction_model = None
                        classifier_prompt = None
                        classifier_model = None
                    
                    game_ending_turn_correction_prompt = Prompt.objects.get(pk=game_ending_turn_correction_prompt_id) if game_ending_turn_correction_prompt_id else None
                    difficulty = DifficultyProfile.objects.get(pk=difficulty_id) if difficulty_id else None
                    storyteller_timeout_int = int(storyteller_timeout)
                    turn_correction_timeout_int = int(turn_correction_timeout)
                    classifier_timeout_int = int(classifier_timeout)
                    total_turns_int = int(total_turns)
                    phase1_turns_int = int(phase1_turns)
                    phase2_turns_int = int(phase2_turns)
                    phase3_turns_int = int(phase3_turns)
                    phase4_turns_int = int(phase4_turns)

                    for step in judge_steps_data:
                        if step.get('deleted'):
                            continue
                        # Classifier is optional, but rewrite and compare are required
                        required_fields = [
                            step.get('rewrite_prompt_id'),
                            step.get('rewrite_model_id'),
                            step.get('compare_prompt_id'),
                            step.get('compare_model_id')
                        ]
                        if any(field is None for field in required_fields):
                            raise ValueError('Judge steps require rewrite and compare settings (classifier is optional)')
                    
                    if config:
                        # Update existing
                        config.name = name
                        config.description = description
                        config.adventure_prompt = adventure_prompt
                        config.storyteller_model = storyteller_model
                        config.storyteller_timeout = storyteller_timeout_int
                        config.turn_correction_prompt = turn_correction_prompt
                        config.turn_correction_model = turn_correction_model
                        config.turn_correction_timeout = turn_correction_timeout_int
                        config.game_ending_turn_correction_prompt = game_ending_turn_correction_prompt
                        config.game_ending_prompt = game_ending_prompt
                        config.difficulty = difficulty
                        config.total_turns = total_turns_int
                        config.phase1_turns = phase1_turns_int
                        config.phase2_turns = phase2_turns_int
                        config.phase3_turns = phase3_turns_int
                        config.phase4_turns = phase4_turns_int
                        config.enable_refusal_detection = enable_refusal_detection
                        config.classifier_prompt = classifier_prompt
                        config.classifier_model = classifier_model
                        config.classifier_timeout = classifier_timeout_int
                        config.classifier_question = classifier_question
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
                            turn_correction_prompt=turn_correction_prompt,
                            turn_correction_model=turn_correction_model,
                            turn_correction_timeout=turn_correction_timeout_int,
                            game_ending_turn_correction_prompt=game_ending_turn_correction_prompt,
                            game_ending_prompt=game_ending_prompt,
                            difficulty=difficulty,
                            total_turns=total_turns_int,
                            phase1_turns=phase1_turns_int,
                            phase2_turns=phase2_turns_int,
                            phase3_turns=phase3_turns_int,
                            phase4_turns=phase4_turns_int,
                            enable_refusal_detection=enable_refusal_detection,
                            classifier_prompt=classifier_prompt,
                            classifier_model=classifier_model,
                            classifier_timeout=classifier_timeout_int,
                            classifier_question=classifier_question
                        )
                        messages.success(request, f'Configuration "{name}" created')

                    # Sync judge steps
                    existing_steps = {str(step.id): step for step in JudgeStep.objects.filter(configuration=config)}
                    seen_ids = set()
                    for step in judge_steps_data:
                        step_id = step.get('id')
                        if step.get('deleted'):
                            if step_id and step_id in existing_steps:
                                existing_steps[step_id].delete()
                            continue

                        # Fetch required objects
                        rewrite_prompt = Prompt.objects.get(pk=step['rewrite_prompt_id'])
                        compare_prompt = Prompt.objects.get(pk=step['compare_prompt_id'])
                        rewrite_model = LLMModel.objects.get(pk=step['rewrite_model_id'])
                        compare_model = LLMModel.objects.get(pk=step['compare_model_id'])
                        
                        # Fetch optional classifier objects
                        classifier_prompt = Prompt.objects.get(pk=step['classifier_prompt_id']) if step['classifier_prompt_id'] else None
                        classifier_model = LLMModel.objects.get(pk=step['classifier_model_id']) if step['classifier_model_id'] else None

                        if step_id and step_id in existing_steps:
                            judge_step = existing_steps[step_id]
                        else:
                            judge_step = JudgeStep(configuration=config)

                        judge_step.order = step['order']
                        judge_step.name = step['name']
                        judge_step.enabled = step['enabled']
                        
                        # Classifier phase (optional)
                        judge_step.classifier_prompt = classifier_prompt
                        judge_step.classifier_model = classifier_model
                        judge_step.classifier_timeout = int(step['classifier_timeout'])
                        judge_step.classifier_question = step['classifier_question']
                        judge_step.classifier_use_full_context = step['classifier_use_full_context']
                        
                        # Rewrite phase
                        judge_step.rewrite_prompt = rewrite_prompt
                        judge_step.rewrite_model = rewrite_model
                        judge_step.rewrite_timeout = int(step['rewrite_timeout'])
                        judge_step.rewrite_instruction = step['rewrite_instruction']
                        judge_step.rewrite_use_full_context = step['rewrite_use_full_context']
                        judge_step.max_rewrite_attempts = int(step['max_rewrite_attempts'])
                        
                        # Compare phase
                        judge_step.compare_prompt = compare_prompt
                        judge_step.compare_model = compare_model
                        judge_step.compare_timeout = int(step['compare_timeout'])
                        judge_step.compare_question = step['compare_question']
                        judge_step.compare_use_full_context = step['compare_use_full_context']
                        
                        judge_step.save()

                        if step_id:
                            seen_ids.add(step_id)
                        else:
                            seen_ids.add(str(judge_step.id))

                    # Remove any steps not present in the form
                    for existing_id, existing_step in existing_steps.items():
                        if existing_id not in seen_ids:
                            existing_step.delete()
                    
                    return redirect('admin:config_editor', config_id=config.id)
                except Prompt.DoesNotExist:
                    messages.error(request, 'Invalid prompt selection')
                except LLMModel.DoesNotExist:
                    messages.error(request, 'Invalid model selection')
                except ValueError:
                    messages.error(request, 'Invalid timeout value or judge step configuration')
    
    # Preserve form data on validation errors
    form_data = None
    if request.method == 'POST' and messages.get_messages(request):
        # If there are error messages, preserve the POST data
        form_data = request.POST
    
    context = {
        'config': config,
        'all_models': LLMModel.objects.all().order_by('provider__name', 'name'),
        'adventure_prompts': adventure_prompts,
        'turn_correction_prompts': turn_correction_prompts,
        'game_ending_prompts': game_ending_prompts,
        'classifier_prompts': classifier_prompts,
        'difficulties': difficulties,
        'judge_prompts': judge_prompts,
        'judge_steps': JudgeStep.objects.filter(configuration=config).order_by('order', 'id') if config else [],
        'form_data': form_data,
    }
    return render(request, 'cyoa_admin/config_editor.html', context)


@debug_login_bypass
@require_http_methods(["POST"])
def refresh_models(request):
    """
    API endpoint to refresh Ollama models list.
    """
    models = get_ollama_models()
    model_names = [model.get('id', model.get('name')) for model in models]
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
                result = test_ollama_connection(base_url)
            elif provider_type == 'anthropic':
                result = test_anthropic_connection(api_key)
            elif provider_type == 'openai':
                result = test_openai_connection(api_key)
            elif provider_type == 'openrouter':
                result = test_openrouter_connection(api_key)
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
        result = test_ollama_connection(base_url)
    elif provider_type == 'anthropic':
        result = test_anthropic_connection(api_key)
    elif provider_type == 'openai':
        result = test_openai_connection(api_key)
    elif provider_type == 'openrouter':
        result = test_openrouter_connection(api_key)
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
@require_http_methods(["POST"])
def delete_model(request, model_id):
    """
    Delete a single model.
    """
    try:
        model = LLMModel.objects.get(pk=model_id)
        model_name = model.name
        model.delete()
        
        messages.success(request, f'Model "{model_name}" deleted successfully')
        return redirect('admin:model_list')
    except LLMModel.DoesNotExist:
        messages.error(request, 'Model not found')
        return redirect('admin:model_list')
    except ProtectedError as e:
        # Model is still referenced by configurations or judge steps
        model = LLMModel.objects.get(pk=model_id)
        
        # Find all configurations using this model
        configs_using = []
        
        # Check direct configuration references
        for config in Configuration.objects.filter(
            Q(storyteller_model=model) |
            Q(turn_correction_model=model) |
            Q(classifier_model=model)
        ).distinct():
            roles = []
            if config.storyteller_model == model:
                roles.append('storyteller')
            if config.turn_correction_model == model:
                roles.append('turn correction')
            if config.classifier_model == model:
                roles.append('classifier')
            configs_using.append(f'"{config.name}" ({", ".join(roles)})')
        
        # Check judge steps
        judge_steps = JudgeStep.objects.filter(
            Q(classifier_model=model) |
            Q(rewrite_model=model) |
            Q(compare_model=model)
        ).select_related('configuration')
        
        for step in judge_steps:
            roles = []
            if step.classifier_model == model:
                roles.append(f'judge step "{step.name}" classifier')
            if step.rewrite_model == model:
                roles.append(f'judge step "{step.name}" rewriter')
            if step.compare_model == model:
                roles.append(f'judge step "{step.name}" comparator')
            
            config_entry = f'"{step.configuration.name}" ({", ".join(roles)})'
            if config_entry not in configs_using:
                configs_using.append(config_entry)
        
        if configs_using:
            configs_list = ', '.join(configs_using)
            message = (
                f'Cannot delete model "{model.name}" because it is currently used by: {configs_list}. '
                f'Please update or delete these configurations first.'
            )
        else:
            message = f'Cannot delete model "{model.name}" because it is still referenced by other objects.'
        
        messages.error(request, message)
        return redirect('admin:model_list')
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error deleting model: {str(e)}'
        })


@debug_login_bypass
def browse_provider_models(request, provider_id):
    """
    Browse available models from a provider and select which to import.
    """
    provider = get_object_or_404(APIProvider, pk=provider_id)
    
    # Fetch models from provider
    available_models = []
    if provider.provider_type == 'ollama':
        available_models = get_ollama_models(provider.base_url)
    elif provider.provider_type == 'anthropic':
        available_models = get_anthropic_models(provider.api_key)
    elif provider.provider_type == 'openai':
        available_models = get_openai_models(provider.api_key)
    elif provider.provider_type == 'openrouter':
        available_models = get_openrouter_models(provider.api_key)
    
    # Get already imported models for this provider
    imported_model_ids = set(
        LLMModel.objects.filter(provider=provider)
        .values_list('model_identifier', flat=True)
    )
    
    # Mark which models are already imported
    for model in available_models:
        model['imported'] = model['id'] in imported_model_ids
    
    # Serialize models to JSON for template
    import json
    models_json = json.dumps(available_models)
    
    context = {
        'provider': provider,
        'available_models': available_models,
        'models_json': models_json,
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
        return JsonResponse({'success': False, 'error': 'Missing provider or models', 'message': 'Missing provider or models'})
    
    try:
        provider = APIProvider.objects.get(pk=provider_id)
        
        # Fetch full model list from provider
        if provider.provider_type == 'ollama':
            available_models = get_ollama_models(provider.base_url)
        elif provider.provider_type == 'anthropic':
            available_models = get_anthropic_models(provider.api_key)
        elif provider.provider_type == 'openai':
            available_models = get_openai_models(provider.api_key)
        elif provider.provider_type == 'openrouter':
            available_models = get_openrouter_models(provider.api_key)
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
            'message': f'Imported {imported_count} models from {provider.name}',
            'imported': imported_count
        })
    
    except APIProvider.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Provider not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@debug_login_bypass
@require_http_methods(["POST"])
def remove_models(request):
    """
    Remove selected models from the database.
    """
    import json
    data = json.loads(request.body)
    
    provider_id = data.get('provider_id')
    model_ids = data.get('model_ids', [])
    
    if not provider_id or not model_ids:
        return JsonResponse({'success': False, 'message': 'Missing provider or models'})
    
    try:
        provider = APIProvider.objects.get(pk=provider_id)
        
        # Delete models with the specified model identifiers
        deleted_count, _ = LLMModel.objects.filter(
            provider=provider,
            model_identifier__in=model_ids
        ).delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Removed {deleted_count} models from {provider.name}'
        })
    
    except APIProvider.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Provider not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@debug_login_bypass
@require_http_methods(["POST"])
def sync_provider_models(request, provider_id):
    """
    Scan provider for valid models and remove any that are no longer available.
    Also marks existing models as available/unavailable based on current provider state.
    """
    try:
        provider = APIProvider.objects.get(pk=provider_id)
        
        # Fetch current models from provider
        if provider.provider_type == 'ollama':
            available_models = get_ollama_models(provider.base_url)
        elif provider.provider_type == 'anthropic':
            available_models = get_anthropic_models(provider.api_key)
        elif provider.provider_type == 'openai':
            available_models = get_openai_models(provider.api_key)
        elif provider.provider_type == 'openrouter':
            available_models = get_openrouter_models(provider.api_key)
        else:
            return JsonResponse({'success': False, 'message': 'Unknown provider type'})
        
        if not available_models:
            return JsonResponse({
                'success': False,
                'message': f'Could not fetch models from {provider.name}. Provider may be unavailable.'
            })
        
        # Get set of valid model identifiers from provider
        valid_model_ids = {model['id'] for model in available_models}
        
        # Get all existing models for this provider
        existing_models = LLMModel.objects.filter(provider=provider)
        
        # Remove models that are no longer available from provider
        removed_count = 0
        updated_count = 0
        for model in existing_models:
            if model.model_identifier not in valid_model_ids:
                model.delete()
                removed_count += 1
            elif not model.is_available:
                # Re-enable models that are now available
                model.is_available = True
                model.save()
                updated_count += 1
        
        message_parts = []
        if removed_count > 0:
            message_parts.append(f'removed {removed_count} invalid models')
        if updated_count > 0:
            message_parts.append(f'updated {updated_count} models')
        
        if message_parts:
            message = f'Sync complete: {" and ".join(message_parts)}'
        else:
            message = 'All models are in sync with provider'
        
        return JsonResponse({
            'success': True,
            'message': message,
            'removed_count': removed_count,
            'updated_count': updated_count
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
        
        # Fallback: if function is still None, try getting it directly
        if not function:
            function = request.POST.get('function')
        
        # Create or update
        if difficulty:
            difficulty.name = name
            difficulty.description = description
            if function:  # Only update if function is provided
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

