"""
Chat views for the CYOA frontend.
"""
import uuid
import json
import re
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ChatConversation, ChatMessage, GameSession, Configuration, AuditLog
from .llm_router import call_llm
from .config_utils import get_active_configuration, apply_pacing_template
from .difficulty_utils import calculate_phase_ends, calculate_turn_number, should_trigger_death
from .refusal_detector import process_potential_refusal
from .judge_pipeline import run_judge_pipeline


def home_page(request):
    """
    Home page showing recent games and available configurations.
    """
    # Get recent incomplete games (last 5)
    recent_games = []
    conversations = ChatConversation.objects.order_by('-updated_at')[:10]
    
    for conv in conversations:
        try:
            game_session = GameSession.objects.get(session_id=conv.conversation_id)
            if not game_session.game_over:
                recent_games.append({
                    'conversation_id': conv.conversation_id,
                    'title': conv.title,
                    'turn_number': game_session.turn_number,
                    'max_turns': game_session.max_turns,
                    'updated_at': conv.updated_at
                })
                if len(recent_games) >= 5:
                    break
        except GameSession.DoesNotExist:
            pass
    
    # Get all configurations
    configurations = Configuration.objects.all()
    
    return render(request, 'home.html', {
        'recent_games': recent_games,
        'configurations': configurations
    })


def chat_page(request):
    """
    Main chat page view.
    """
    return render(request, 'chat/chat_page.html')


def extract_game_state(text):
    """
    Extract turn info and choices from LLM response.
    Returns dict with turn_current, turn_max, choice1, choice2.
    """
    state = {
        'turn_current': 0,
        'turn_max': 20,
        'choice1': '',
        'choice2': '',
        'inventory': []
    }
    
    # Extract "Turn X of Y" or "Turn X/Y"
    turn_match = re.search(r'Turn\s+(\d+)\s*(?:of|/)\s*(\d+)', text, re.IGNORECASE)
    if turn_match:
        state['turn_current'] = int(turn_match.group(1))
        state['turn_max'] = int(turn_match.group(2))
    
    # Extract choices - look for "1) ..." or "1. ..." patterns
    # Split into lines and look for numbered choices
    lines = text.split('\n')
    current_choice = None
    choice_texts = {}
    
    for line in lines:
        # Check if line starts with a choice number (handles both "1)" and "1.")
        choice_match = re.match(r'^\s*(\d+)[.)\]]\s*(.+)', line)
        if choice_match:
            choice_num = int(choice_match.group(1))
            choice_text = choice_match.group(2).strip()
            if choice_num in [1, 2]:
                current_choice = choice_num
                choice_texts[choice_num] = choice_text
        elif current_choice and line.strip() and not re.match(r'^\s*\d+[.)\]]', line):
            # Continuation of current choice (multi-line)
            choice_texts[current_choice] += ' ' + line.strip()
    
    # Assign to state
    if 1 in choice_texts:
        state['choice1'] = choice_texts[1]
    if 2 in choice_texts:
        state['choice2'] = choice_texts[2]
    
    # Debug output
    print(f"[EXTRACT_STATE] Turn: {state['turn_current']}/{state['turn_max']}")
    print(f"[EXTRACT_STATE] Choice 1: {state['choice1'][:50] if state['choice1'] else 'NOT FOUND'}")
    print(f"[EXTRACT_STATE] Choice 2: {state['choice2'][:50] if state['choice2'] else 'NOT FOUND'}")
    
    return state


@csrf_exempt
@require_http_methods(["POST"])
def chat_api_new_conversation(request):
    """
    Create a new conversation and return its UUID.
    Accepts optional config_id in body to use specific configuration.
    """
    try:
        body = json.loads(request.body) if request.body else {}
        config_id = body.get('config_id')
        
        conversation_id = str(uuid.uuid4())
        
        # Get config name for title
        title = "New Adventure"
        if config_id:
            try:
                config = Configuration.objects.get(id=config_id)
                title = config.name
            except Configuration.DoesNotExist:
                pass
        
        conversation = ChatConversation.objects.create(
            conversation_id=conversation_id,
            title=title,
            metadata={'config_id': config_id} if config_id else {}
        )
        
        return JsonResponse({
            'conversation_id': conversation.conversation_id,
            'title': conversation.title,
            'created_at': conversation.created_at.isoformat()
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def chat_api_send_message(request):
    """
    Send a message to the LLM and get a response.
    """
    try:
        body = json.loads(request.body)
        conversation_id = body.get('conversation_id')
        user_message = body.get('message', '').strip()
        
        if not conversation_id or not user_message:
            return JsonResponse({'error': 'conversation_id and message required'}, status=400)
        
        # Get or create conversation
        conversation, created = ChatConversation.objects.get_or_create(
            conversation_id=conversation_id,
            defaults={'title': 'New Adventure'}
        )
        
        # Save user message
        ChatMessage.objects.create(
            conversation=conversation,
            role='user',
            content=user_message
        )
        
        # Build message history for LLM (last 20 messages for context)
        messages = []
        for msg in conversation.messages.all().order_by('-created_at')[:20][::-1]:
            messages.append({
                'role': msg.role,
                'content': msg.content
            })
        
        # Get configuration (from conversation metadata or active)
        config = None
        config_id = conversation.metadata.get('config_id') if conversation.metadata else None
        if config_id:
            try:
                config = Configuration.objects.get(id=config_id)
                print(f"[CHAT] Using conversation's config: {config.name}")
            except Configuration.DoesNotExist:
                print(f"[CHAT] Config {config_id} not found, using active")
                config = get_active_configuration()
        else:
            config = get_active_configuration()
        
        # Calculate turn number
        turn_number = calculate_turn_number(messages)
        print(f"[CHAT] This is turn {turn_number}")
        
        # Get or create game session for this conversation
        max_turns = config.total_turns if config else 20
        game_session, created = GameSession.objects.get_or_create(
            session_id=conversation.conversation_id,
            defaults={
                'conversation_fingerprint': conversation.conversation_id,
                'configuration': config,
                'max_turns': max_turns,
                'turn_number': turn_number
            }
        )
        if created:
            print(f"[CHAT] Created new game session: {game_session.session_id}")
        else:
            # Update turn number
            game_session.turn_number = turn_number
            game_session.save()
        
        # Check if death should trigger (difficulty engine)
        use_game_ending_prompt = False
        if config and config.difficulty:
            use_game_ending_prompt = should_trigger_death(
                turn_number=turn_number,
                max_turns=game_session.max_turns,
                difficulty_profile=config.difficulty,
                game_session=game_session
            )
            
            if use_game_ending_prompt:
                print(f"[CHAT] ☠️  Death triggered! Using game-ending prompt")
                game_session.game_over = True
                game_session.save()
        
        # Get adventure prompt as system message (or game-ending prompt if death triggered)
        system_prompt = None
        if config:
            if use_game_ending_prompt and config.game_ending_prompt:
                # Use game-ending prompt for death scenes
                system_prompt = config.game_ending_prompt.prompt_text
                print(f"[CHAT] Using game-ending prompt: {len(system_prompt)} chars")
            elif config.adventure_prompt:
                # Use normal adventure prompt with template replacement
                system_prompt = apply_pacing_template(
                    config.adventure_prompt.prompt_text,
                    config
                )
                print(f"[CHAT] Applied pacing template to adventure prompt")
        
        # Determine model to use
        if not config or not config.storyteller_model:
            return JsonResponse({'error': 'No storyteller model configured'}, status=500)
        
        print(f"[CHAT] Calling LLM with model: {config.storyteller_model.name}")
        
        # Call LLM (using storyteller model from config)
        llm_response = call_llm(
            messages=messages,
            system_prompt=system_prompt,
            llm_model=config.storyteller_model,
            timeout=60
        )
        
        # Process potential refusal (only if not a game-ending turn)
        final_response = llm_response
        refusal_info = {
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False,
            'original_text': '',
            'turn_1_refusal': False,
            'all_attempts_failed': False,
            'attempts': []
        }
        
        if config:
            refusal_result = process_potential_refusal(
                messages=messages,
                story_turn=llm_response,
                config=config,
                user_message=user_message,
                is_game_ending=use_game_ending_prompt,
                turn_number=turn_number,
                max_retries=3
            )
            
            final_response = refusal_result['final_turn']
            refusal_info = {
                'was_refusal': refusal_result['was_refusal'],
                'classifier_response': refusal_result['classifier_response'],
                'was_corrected': refusal_result['was_corrected'],
                'original_text': llm_response if refusal_result['was_refusal'] else '',
                'turn_1_refusal': refusal_result.get('turn_1_refusal', False),
                'all_attempts_failed': refusal_result.get('all_attempts_failed', False),
                'attempts': refusal_result.get('attempts', [])
            }
            
            # Log to audit if refusal was detected (before early returns)
            if refusal_info['was_refusal']:
                AuditLog.objects.create(
                    original_text=llm_response,
                    refined_text=final_response,
                    was_modified=refusal_info['was_corrected'],
                    was_refusal=True,
                    classifier_response=refusal_info['classifier_response'],
                    prompt_used=config.classifier_prompt,
                    correction_prompt_used=config.turn_correction_prompt if refusal_info['was_corrected'] else None
                )
                print(f"[CHAT] Refusal logged to audit (corrected={refusal_info['was_corrected']})")
            
            # Handle turn 1 refusal - save error message and return
            if refusal_info['turn_1_refusal']:
                error_text = "The AI is a petulant child and refused to play your game. Sorry about that, try again but maybe tone it down like 10%"
                assistant_msg = ChatMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=error_text,
                    metadata={
                        'is_error': True,
                        'refusal_info': refusal_info
                    }
                )
                return JsonResponse({
                    'message': {
                        'role': assistant_msg.role,
                        'content': assistant_msg.content,
                        'created_at': assistant_msg.created_at.isoformat(),
                        'refusal_info': refusal_info,
                        'is_error': True
                    },
                    'state': {
                        'inventory': [],
                        'turn_current': 0,
                        'turn_max': max_turns,
                        'choice1': '',
                        'choice2': ''
                    },
                    'game_blocked': True
                })
            
            # Handle all attempts failed (turn 2+) - save error message and return
            if refusal_info['all_attempts_failed']:
                error_text = "The AI is a petulant child and refused to play your game. Sorry about that, try again but maybe tone it down like 10%"
                assistant_msg = ChatMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=error_text,
                    metadata={
                        'is_error': True,
                        'refusal_info': refusal_info
                    }
                )
                return JsonResponse({
                    'message': {
                        'role': assistant_msg.role,
                        'content': assistant_msg.content,
                        'created_at': assistant_msg.created_at.isoformat(),
                        'refusal_info': refusal_info,
                        'is_error': True
                    },
                    'state': extract_game_state(messages[-1]['content'] if messages else ''),
                    'game_blocked': True
                })
            
        # Run judge pipeline (post-refusal corrections)
        judge_info = None
        if config:
            judge_input_turn = final_response
            judge_result = run_judge_pipeline(messages, final_response, config)
            if judge_result.get('steps'):
                final_response = judge_result['final_turn']
                judge_info = judge_result
                judge_steps = list(config.judge_steps.all().order_by('order', 'id'))
                # Use first step's classifier prompt if available, otherwise compare prompt
                first_step_prompt = None
                if judge_steps:
                    first_step_prompt = judge_steps[0].classifier_prompt or judge_steps[0].compare_prompt
                AuditLog.objects.create(
                    original_text=judge_input_turn,
                    refined_text=final_response,
                    was_modified=judge_result.get('was_modified', False),
                    was_refusal=False,
                    prompt_used=first_step_prompt,
                    details=judge_result
                )

        # Save assistant response (using final response after refusal/judge processing)
        assistant_msg = ChatMessage.objects.create(
            conversation=conversation,
            role='assistant',
            content=final_response,
            metadata={
                'refusal_info': refusal_info if refusal_info['was_refusal'] else None,
                'judge_info': judge_info
            }
        )
        
        # Extract game state from response
        game_state = extract_game_state(final_response)
        
        # Mark game as complete if we've reached max turns or game ending
        if game_state['turn_current'] >= game_session.max_turns or game_session.game_over:
            game_session.game_over = True
            game_session.save()
            print(f"[CHAT] Game marked as complete")
        
        return JsonResponse({
            'message': {
                'role': assistant_msg.role,
                'content': assistant_msg.content,
                'created_at': assistant_msg.created_at.isoformat(),
                'refusal_info': refusal_info if refusal_info['was_refusal'] else None,
                'judge_info': judge_info
            },
            'state': game_state
        })
    except Exception as e:
        print(f"[CHAT ERROR] {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def chat_api_get_conversation(request, conversation_id):
    """
    Get conversation history.
    """
    try:
        conversation = get_object_or_404(ChatConversation, conversation_id=conversation_id)
        
        messages_data = []
        for msg in conversation.messages.all():
            messages_data.append({
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at.isoformat(),
                'metadata': msg.metadata
            })
        
        return JsonResponse({
            'conversation_id': conversation.conversation_id,
            'title': conversation.title,
            'metadata': conversation.metadata,
            'messages': messages_data,
            'created_at': conversation.created_at.isoformat(),
            'updated_at': conversation.updated_at.isoformat()
        })
    except Http404:
        return JsonResponse({'error': 'Conversation not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def chat_api_list_conversations(request):
    """
    List all conversations.
    """
    try:
        conversations = ChatConversation.objects.all()[:50]  # Latest 50
        
        conversations_data = []
        for conv in conversations:
            message_count = conv.messages.count()
            last_message = conv.messages.last()
            
            conversations_data.append({
                'conversation_id': conv.conversation_id,
                'title': conv.title,
                'message_count': message_count,
                'last_message': last_message.content[:100] if last_message else None,
                'created_at': conv.created_at.isoformat(),
                'updated_at': conv.updated_at.isoformat()
            })
        
        return JsonResponse({'conversations': conversations_data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def chat_api_delete_conversation(request, conversation_id):
    """
    Delete a conversation by marking its game session as over.
    """
    try:
        # Mark game session as over
        game_session = GameSession.objects.get(session_id=conversation_id)
        game_session.game_over = True
        game_session.save()
        
        return JsonResponse({'success': True})
    except GameSession.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
