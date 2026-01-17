"""
Chat views for the CYOA frontend.
"""
import uuid
import json
import re
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ChatConversation, ChatMessage, GameSession, Configuration
from .llm_router import call_llm
from .config_utils import get_active_configuration, apply_pacing_template
from .difficulty_utils import calculate_phase_ends, calculate_turn_number, should_trigger_death


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
    turn_match = re.search(r'Turn\s+(\d+)\s+(?:of|/)\s+(\d+)', text, re.IGNORECASE)
    if turn_match:
        state['turn_current'] = int(turn_match.group(1))
        state['turn_max'] = int(turn_match.group(2))
    
    # Extract choices like "1) text" and "2) text"
    # Look for patterns like "1) some action" and "2) another action"
    choice_pattern = r'^\s*(\d+)\)\s*(.+?)(?=\s*\d+\)|$)'
    matches = list(re.finditer(choice_pattern, text, re.MULTILINE))
    
    if len(matches) >= 2:
        # Get the text for choices 1 and 2
        for match in matches:
            choice_num = int(match.group(1))
            choice_text = match.group(2).strip()
            
            if choice_num == 1:
                state['choice1'] = choice_text
            elif choice_num == 2:
                state['choice2'] = choice_text
    
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
        model = config.storyteller_model if config else "qwen3:30b"
        
        print(f"[CHAT] Calling LLM with model: {model}")
        
        # Call LLM (using storyteller model from config)
        llm_response = call_llm(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            timeout=60
        )
        
        # Save assistant response
        assistant_msg = ChatMessage.objects.create(
            conversation=conversation,
            role='assistant',
            content=llm_response
        )
        
        # Extract game state from response
        game_state = extract_game_state(llm_response)
        
        # Mark game as complete if we've reached max turns or game ending
        if game_state['turn_current'] >= game_session.max_turns or game_session.game_over:
            game_session.game_over = True
            game_session.save()
            print(f"[CHAT] Game marked as complete")
        
        return JsonResponse({
            'message': {
                'role': assistant_msg.role,
                'content': assistant_msg.content,
                'created_at': assistant_msg.created_at.isoformat()
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
