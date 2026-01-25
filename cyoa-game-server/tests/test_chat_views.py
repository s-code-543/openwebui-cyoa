"""
Tests for chat_views.py - CYOA Chat Interface

This module tests all chat API endpoints including:
- Conversation creation
- Message sending and LLM integration
- Game state extraction
- Refusal detection and correction
- Judge pipeline execution
- Conversation history retrieval

Test Categories:
- Unit tests: Individual function behavior with mocked LLM
- Integration tests: Full request/response cycle with mocked external services
"""
import pytest
import json
import uuid
from unittest.mock import patch, MagicMock
from django.test import Client

from game.models import (
    ChatConversation, ChatMessage, GameSession, Configuration,
    AuditLog
)
from game.chat_views import extract_game_state
from tests.conftest import (
    ChatConversationFactory, ChatMessageFactory, ConfigurationFactory,
    GameSessionFactory, PromptFactory, LLMModelFactory, APIProviderFactory,
    SAMPLE_VALID_TURN, SAMPLE_REFUSAL_TURN, SAMPLE_CORRECTED_TURN,
    SAMPLE_CLASSIFIER_YES, SAMPLE_CLASSIFIER_NO
)


# =============================================================================
# Sample Response Data (loaded from fixtures or defined inline)
# =============================================================================

SAMPLE_TURN_3_OF_10 = """**Turn 3 of 10**

The ancient door creaks open, revealing a dimly lit chamber filled with strange artifacts. Dust motes dance in the pale light filtering through a crack in the ceiling.

**Your choices:**
1) Follow the narrow corridor into the depths
2) Climb the spiral staircase toward the light

**Inventory:** rusty key, torch, 3 gold coins
"""

SAMPLE_TURN_1_OF_10 = """**Turn 1 of 10**

You awaken in a cold, damp cell. The stone walls are covered with moss, and the only light comes from a small barred window high above.

**Your choices:**
1) Grab the key and try to unlock the cell door
2) Call out to whoever is approaching

**Inventory:** tattered clothes
"""


# =============================================================================
# extract_game_state Unit Tests
# =============================================================================

@pytest.mark.unit
class TestExtractGameState:
    """Unit tests for the extract_game_state function."""
    
    def test_extracts_turn_numbers(self):
        """Correctly extracts turn current and max from text."""
        text = "**Turn 5 of 10**\n\nSome story content."
        state = extract_game_state(text)
        
        assert state['turn_current'] == 5
        assert state['turn_max'] == 10
    
    def test_extracts_turn_with_slash_format(self):
        """Handles Turn X/Y format."""
        text = "Turn 3/15\n\nThe adventure continues."
        state = extract_game_state(text)
        
        assert state['turn_current'] == 3
        assert state['turn_max'] == 15
    
    def test_extracts_choices_with_parenthesis(self):
        """Extracts choices formatted with parentheses."""
        text = """Turn 1 of 10
        
Some story.

1) Go left into the cave
2) Go right toward the mountain"""
        
        state = extract_game_state(text)
        
        assert 'Go left into the cave' in state['choice1']
        assert 'Go right toward the mountain' in state['choice2']
    
    def test_extracts_choices_with_period(self):
        """Extracts choices formatted with periods."""
        text = """Turn 1 of 10
        
Some story.

1. Enter the dark forest
2. Follow the river downstream"""
        
        state = extract_game_state(text)
        
        assert 'Enter the dark forest' in state['choice1']
        assert 'Follow the river downstream' in state['choice2']
    
    def test_handles_missing_turn_info(self):
        """Returns defaults when turn info is missing."""
        text = "Some story without turn numbers."
        state = extract_game_state(text)
        
        assert state['turn_current'] == 0
        assert state['turn_max'] == 20  # Default
    
    def test_handles_missing_choices(self):
        """Returns empty strings when choices are missing."""
        text = "Turn 5 of 10\n\nStory with no choices."
        state = extract_game_state(text)
        
        assert state['choice1'] == ''
        assert state['choice2'] == ''
    
    def test_handles_multiline_choices(self):
        """Handles choices that span multiple lines."""
        text = """Turn 2 of 10

The path splits.

1) Take the left path which leads
   through the dark forest
2) Take the right path toward
   the sunny meadow"""
        
        state = extract_game_state(text)
        
        assert 'left path' in state['choice1']
        assert 'right path' in state['choice2']
    
    def test_returns_inventory_list(self):
        """Returns an inventory list in state."""
        text = "Turn 1 of 10\n\n1) Option A\n2) Option B"
        state = extract_game_state(text)
        
        assert 'inventory' in state
        assert isinstance(state['inventory'], list)


# =============================================================================
# New Conversation API Tests
# =============================================================================

@pytest.mark.django_db
class TestNewConversationAPI:
    """Tests for the chat_api_new_conversation endpoint."""
    
    def test_creates_new_conversation(self, client):
        """POST /chat/api/new creates a new conversation."""
        response = client.post(
            '/chat/api/new',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert 'conversation_id' in data
        assert 'title' in data
        assert 'created_at' in data
        
        # Verify UUID format
        uuid.UUID(data['conversation_id'])
    
    def test_creates_conversation_with_config(self, client, db, configuration):
        """Creates conversation linked to specific configuration."""
        response = client.post(
            '/chat/api/new',
            data=json.dumps({'config_id': configuration.id}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        # Title should be config name
        assert data['title'] == configuration.name
        
        # Verify config_id stored in metadata
        conv = ChatConversation.objects.get(conversation_id=data['conversation_id'])
        assert conv.metadata.get('config_id') == configuration.id
    
    def test_handles_invalid_config_id(self, client, db):
        """Gracefully handles non-existent config_id."""
        response = client.post(
            '/chat/api/new',
            data=json.dumps({'config_id': 99999}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'conversation_id' in data
    
    def test_creates_conversation_with_empty_body(self, client):
        """Works with empty request body."""
        response = client.post('/chat/api/new', content_type='application/json')
        
        assert response.status_code == 200


# =============================================================================
# Send Message API Tests
# =============================================================================

@pytest.mark.django_db
class TestSendMessageAPI:
    """Tests for the chat_api_send_message endpoint."""
    
    def test_requires_conversation_id(self, client):
        """Returns error if conversation_id missing."""
        response = client.post(
            '/chat/api/send',
            data=json.dumps({'message': 'Hello'}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'error' in data
    
    def test_requires_message(self, client, db, chat_conversation):
        """Returns error if message missing."""
        response = client.post(
            '/chat/api/send',
            data=json.dumps({'conversation_id': chat_conversation.conversation_id}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_sends_message_and_gets_response(
        self, mock_judge, mock_refusal, mock_llm, 
        client, db, full_configuration
    ):
        """Successfully sends message and receives LLM response."""
        mock_llm.return_value = SAMPLE_TURN_1_OF_10
        mock_refusal.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_modified': False,
            'steps': []
        }
        
        # Create conversation with config
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Start the adventure!'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert 'message' in data
        assert data['message']['role'] == 'assistant'
        assert 'Turn 1 of 10' in data['message']['content']
        assert 'state' in data
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_extracts_game_state_from_response(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Extracts and returns game state from LLM response."""
        mock_llm.return_value = SAMPLE_TURN_3_OF_10
        mock_refusal.return_value = {
            'final_turn': SAMPLE_TURN_3_OF_10,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_TURN_3_OF_10,
            'was_modified': False,
            'steps': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'I choose option 1'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        state = data['state']
        assert state['turn_current'] == 3
        assert state['turn_max'] == 10
        assert 'narrow corridor' in state['choice1'] or 'depths' in state['choice1']
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_creates_game_session(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Creates a GameSession for the conversation."""
        mock_llm.return_value = SAMPLE_TURN_1_OF_10
        mock_refusal.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_modified': False,
            'steps': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Begin!'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        
        # Verify game session was created
        session = GameSession.objects.get(session_id=conv.conversation_id)
        assert session.configuration == full_configuration
        assert session.game_over is False
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_saves_messages_to_conversation(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Saves both user and assistant messages."""
        mock_llm.return_value = SAMPLE_TURN_1_OF_10
        mock_refusal.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_modified': False,
            'steps': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Start adventure!'
            }),
            content_type='application/json'
        )
        
        # Verify messages were saved
        messages = ChatMessage.objects.filter(conversation=conv)
        assert messages.count() == 2
        
        user_msg = messages.filter(role='user').first()
        assert user_msg.content == 'Start adventure!'
        
        assistant_msg = messages.filter(role='assistant').first()
        assert 'Turn 1 of 10' in assistant_msg.content
    
    def test_returns_error_without_config(self, client, db):
        """Returns error when no configuration exists."""
        conv = ChatConversationFactory()
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Hello'
            }),
            content_type='application/json'
        )
        
        # Should return 500 because no storyteller model configured
        assert response.status_code == 500


# =============================================================================
# Refusal Detection Tests
# =============================================================================

@pytest.mark.django_db
class TestRefusalDetection:
    """Tests for refusal detection and correction flow."""
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_detects_and_corrects_refusal(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Detects refusal and returns corrected response."""
        mock_llm.return_value = SAMPLE_REFUSAL_TURN
        mock_refusal.return_value = {
            'final_turn': SAMPLE_CORRECTED_TURN,
            'was_refusal': True,
            'classifier_response': SAMPLE_CLASSIFIER_YES,
            'was_corrected': True
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_CORRECTED_TURN,
            'was_modified': False,
            'steps': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'I attack the monster!'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        # Response should contain refusal info
        assert data['message']['refusal_info'] is not None
        assert data['message']['refusal_info']['was_refusal'] is True
        assert data['message']['refusal_info']['was_corrected'] is True
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_refusal_creates_audit_log(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Refusal detection creates audit log entry."""
        mock_llm.return_value = SAMPLE_REFUSAL_TURN
        mock_refusal.return_value = {
            'final_turn': SAMPLE_CORRECTED_TURN,
            'was_refusal': True,
            'classifier_response': SAMPLE_CLASSIFIER_YES,
            'was_corrected': True
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_CORRECTED_TURN,
            'was_modified': False,
            'steps': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Attack!'
            }),
            content_type='application/json'
        )
        
        # Check audit log was created
        audit = AuditLog.objects.filter(was_refusal=True).first()
        assert audit is not None
        assert audit.was_modified is True
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_turn_1_refusal_blocks_game(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Turn 1 refusal blocks the game with error message."""
        mock_llm.return_value = SAMPLE_REFUSAL_TURN
        mock_refusal.return_value = {
            'final_turn': SAMPLE_REFUSAL_TURN,
            'was_refusal': True,
            'classifier_response': SAMPLE_CLASSIFIER_YES,
            'was_corrected': False,
            'turn_1_refusal': True,
            'all_attempts_failed': False,
            'attempts': []
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Start violent adventure!'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert data.get('game_blocked') is True
        assert 'petulant child' in data['message']['content']


# =============================================================================
# Judge Pipeline Tests  
# =============================================================================

@pytest.mark.django_db
class TestJudgePipeline:
    """Tests for judge pipeline execution in chat."""
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_runs_judge_pipeline(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Judge pipeline runs after refusal processing."""
        mock_llm.return_value = SAMPLE_TURN_1_OF_10
        mock_refusal.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': SAMPLE_TURN_1_OF_10,
            'was_modified': False,
            'steps': [{'step_id': 1, 'name': 'test', 'final_used': 'original'}]
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        response = client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Begin'
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        # Judge pipeline should have been called
        mock_judge.assert_called_once()
        
        # Judge info should be in response
        assert data['message']['judge_info'] is not None
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_judge_modification_creates_audit(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Judge modifications create audit log entries."""
        original = "**Turn 1 of 10**\n\nOriginal content\n\n1) A\n2) B"
        modified = "**Turn 1 of 10**\n\nModified content\n\n1) A\n2) B"
        
        mock_llm.return_value = original
        mock_refusal.return_value = {
            'final_turn': original,
            'was_refusal': False,
            'classifier_response': '',
            'was_corrected': False
        }
        mock_judge.return_value = {
            'final_turn': modified,
            'was_modified': True,
            'steps': [{'step_id': 1, 'name': 'test', 'final_used': 'rewrite'}]
        }
        
        conv = ChatConversationFactory(metadata={'config_id': full_configuration.id})
        
        client.post(
            '/chat/api/send',
            data=json.dumps({
                'conversation_id': conv.conversation_id,
                'message': 'Go'
            }),
            content_type='application/json'
        )
        
        # Check audit log
        audit = AuditLog.objects.filter(was_modified=True, was_refusal=False).first()
        assert audit is not None


# =============================================================================
# Get Conversation API Tests
# =============================================================================

@pytest.mark.django_db
class TestGetConversationAPI:
    """Tests for the chat_api_get_conversation endpoint."""
    
    def test_retrieves_conversation(self, client, db, chat_conversation_with_messages):
        """GET returns conversation with messages."""
        conv = chat_conversation_with_messages
        
        response = client.get(f'/chat/api/conversation/{conv.conversation_id}')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert data['conversation_id'] == conv.conversation_id
        assert data['title'] == conv.title
        assert 'messages' in data
        assert len(data['messages']) == 2
    
    def test_returns_404_for_missing(self, client, db):
        """Returns 404 for non-existent conversation."""
        response = client.get('/chat/api/conversation/nonexistent-uuid')
        
        assert response.status_code == 404
    
    def test_messages_ordered_by_time(self, client, db, chat_conversation):
        """Messages are returned in chronological order."""
        # Create messages
        ChatMessageFactory(conversation=chat_conversation, role='user', content='First')
        ChatMessageFactory(conversation=chat_conversation, role='assistant', content='Second')
        ChatMessageFactory(conversation=chat_conversation, role='user', content='Third')
        
        response = client.get(f'/chat/api/conversation/{chat_conversation.conversation_id}')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert data['messages'][0]['content'] == 'First'
        assert data['messages'][1]['content'] == 'Second'
        assert data['messages'][2]['content'] == 'Third'


# =============================================================================
# List Conversations API Tests
# =============================================================================

@pytest.mark.django_db
class TestListConversationsAPI:
    """Tests for the chat_api_list_conversations endpoint."""
    
    def test_lists_conversations(self, client, db):
        """GET returns list of conversations."""
        ChatConversationFactory()
        ChatConversationFactory()
        ChatConversationFactory()
        
        response = client.get('/chat/api/conversations')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert 'conversations' in data
        assert len(data['conversations']) == 3
    
    def test_includes_message_count(self, client, db, chat_conversation_with_messages):
        """Includes message count in listing."""
        response = client.get('/chat/api/conversations')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        conv_data = next(
            c for c in data['conversations'] 
            if c['conversation_id'] == chat_conversation_with_messages.conversation_id
        )
        assert conv_data['message_count'] == 2
    
    def test_limits_to_50_conversations(self, client, db):
        """Limits results to 50 conversations."""
        for _ in range(60):
            ChatConversationFactory()
        
        response = client.get('/chat/api/conversations')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        
        assert len(data['conversations']) == 50


# =============================================================================
# Delete Conversation API Tests
# =============================================================================

@pytest.mark.django_db
class TestDeleteConversationAPI:
    """Tests for the chat_api_delete_conversation endpoint."""
    
    def test_marks_game_as_over(self, client, db, game_session):
        """DELETE marks the game session as over."""
        assert game_session.game_over is False
        
        response = client.post(f'/chat/api/delete/{game_session.session_id}')
        
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        
        game_session.refresh_from_db()
        assert game_session.game_over is True
    
    def test_returns_404_for_missing(self, client, db):
        """Returns 404 for non-existent game."""
        response = client.post('/chat/api/delete/nonexistent-id')
        
        assert response.status_code == 404


# =============================================================================
# Home Page Tests
# =============================================================================

@pytest.mark.django_db
class TestHomePage:
    """Tests for the home_page view."""
    
    def test_home_page_loads(self, client):
        """Home page loads successfully."""
        response = client.get('/')
        assert response.status_code == 200
    
    def test_shows_recent_games(self, client, db, configuration):
        """Home page shows recent incomplete games."""
        conv = ChatConversationFactory()
        GameSessionFactory(
            session_id=conv.conversation_id,
            configuration=configuration,
            game_over=False,
            turn_number=5
        )
        
        response = client.get('/')
        assert response.status_code == 200
        assert 'recent_games' in response.context
    
    def test_shows_configurations(self, client, db, configuration):
        """Home page shows available configurations."""
        response = client.get('/')
        assert response.status_code == 200
        assert 'configurations' in response.context
        assert len(response.context['configurations']) >= 1


# =============================================================================
# Chat Page Tests
# =============================================================================

@pytest.mark.django_db
class TestChatPage:
    """Tests for the chat_page view."""
    
    def test_chat_page_loads(self, client):
        """Chat page loads successfully."""
        response = client.get('/chat/')
        assert response.status_code == 200


# =============================================================================
# Integration Tests - Full Game Flow
# =============================================================================

@pytest.mark.django_db
@pytest.mark.integration
class TestFullGameFlow:
    """Integration tests for complete game scenarios."""
    
    @patch('game.chat_views.call_llm')
    @patch('game.chat_views.process_potential_refusal')
    @patch('game.chat_views.run_judge_pipeline')
    def test_complete_game_flow(
        self, mock_judge, mock_refusal, mock_llm,
        client, db, full_configuration
    ):
        """Tests a complete game from start to finish."""
        # Setup mocks for multi-turn game
        turns = [
            "**Turn 1 of 3**\n\nStart!\n\n1) Go\n2) Stay",
            "**Turn 2 of 3**\n\nMiddle!\n\n1) Left\n2) Right",
            "**Turn 3 of 3**\n\nEnd!\n\n**VICTORY!**",
        ]
        mock_llm.side_effect = turns
        mock_refusal.side_effect = [
            {'final_turn': t, 'was_refusal': False, 'classifier_response': '', 'was_corrected': False}
            for t in turns
        ]
        mock_judge.side_effect = [
            {'final_turn': t, 'was_modified': False, 'steps': []}
            for t in turns
        ]
        
        # Update config to 3 turns
        full_configuration.total_turns = 3
        full_configuration.save()
        
        # Create conversation
        create_response = client.post(
            '/chat/api/new',
            data=json.dumps({'config_id': full_configuration.id}),
            content_type='application/json'
        )
        conv_id = json.loads(create_response.content)['conversation_id']
        
        # Turn 1
        r1 = client.post(
            '/chat/api/send',
            data=json.dumps({'conversation_id': conv_id, 'message': 'Start!'}),
            content_type='application/json'
        )
        assert r1.status_code == 200
        d1 = json.loads(r1.content)
        assert d1['state']['turn_current'] == 1
        
        # Turn 2
        r2 = client.post(
            '/chat/api/send',
            data=json.dumps({'conversation_id': conv_id, 'message': '1'}),
            content_type='application/json'
        )
        assert r2.status_code == 200
        d2 = json.loads(r2.content)
        assert d2['state']['turn_current'] == 2
        
        # Turn 3 (final)
        r3 = client.post(
            '/chat/api/send',
            data=json.dumps({'conversation_id': conv_id, 'message': '2'}),
            content_type='application/json'
        )
        assert r3.status_code == 200
        d3 = json.loads(r3.content)
        assert d3['state']['turn_current'] == 3
        
        # Verify game ended
        session = GameSession.objects.get(session_id=conv_id)
        assert session.game_over is True
        
        # Verify all messages saved
        conv = ChatConversation.objects.get(conversation_id=conv_id)
        assert conv.messages.count() == 6  # 3 user + 3 assistant
