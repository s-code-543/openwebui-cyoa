"""
Shared pytest fixtures for CYOA game server tests.

This module provides:
- Model factories for creating test data
- Mock fixtures for LLM calls
- Test client fixtures
- Sample response data
"""
import pytest
import uuid
import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

import factory
from factory.django import DjangoModelFactory
from django.test import Client
from django.contrib.auth.models import User
from django.conf import settings

from game.models import (
    Prompt, AuditLog, Configuration, APIProvider, LLMModel, 
    JudgeStep, DifficultyProfile, GameSession, ChatConversation, 
    ChatMessage, STTRecording
)


# =============================================================================
# Test Environment Fixtures
# =============================================================================

@pytest.fixture(scope='session', autouse=True)
def configure_test_environment():
    """Configure environment variables for test runs."""
    # Use localhost instead of host.docker.internal for tests running on host
    os.environ['WHISPER_API_URL'] = 'http://localhost:10300/v1/audio/transcriptions'
    os.environ['OLLAMA_URL'] = 'http://localhost:11434'
    yield
    # Cleanup is done per-test


@pytest.fixture(autouse=True)
def cleanup_test_media(request):
    """Automatically cleanup media files after each test."""
    yield
    # Cleanup runs after the test
    if hasattr(settings, 'MEDIA_ROOT'):
        media_root = Path(settings.MEDIA_ROOT)
        stt_dir = media_root / 'stt_recordings'
        if stt_dir.exists():
            # Remove all test-generated audio files but keep .gitkeep
            for audio_file in stt_dir.glob('*.wav'):
                audio_file.unlink()
            for audio_file in stt_dir.glob('*.webm'):
                audio_file.unlink()
            for audio_file in stt_dir.glob('*.mp3'):
                audio_file.unlink()
            for audio_file in stt_dir.glob('*.m4a'):
                audio_file.unlink()


# =============================================================================
# Model Factories
# =============================================================================

class APIProviderFactory(DjangoModelFactory):
    """Factory for creating test API providers."""
    class Meta:
        model = APIProvider
    
    name = factory.Sequence(lambda n: f"Test Provider {n}")
    provider_type = 'ollama'
    base_url = 'http://localhost:11434'
    api_key = ''
    is_local = True
    is_active = True


class LLMModelFactory(DjangoModelFactory):
    """Factory for creating test LLM models."""
    class Meta:
        model = LLMModel
    
    name = factory.Sequence(lambda n: f"test-model-{n}")
    model_identifier = factory.Sequence(lambda n: f"test-model-{n}:latest")
    provider = factory.SubFactory(APIProviderFactory)
    is_available = True
    capabilities = {}


class PromptFactory(DjangoModelFactory):
    """Factory for creating test prompts."""
    class Meta:
        model = Prompt
    
    prompt_type = 'adventure'
    name = factory.Sequence(lambda n: f"test-prompt-{n}")
    version = 1
    description = "Test prompt for unit tests"
    prompt_text = "You are a storyteller for a choose your own adventure game."
    file_path = ''


class DifficultyProfileFactory(DjangoModelFactory):
    """Factory for creating test difficulty profiles."""
    class Meta:
        model = DifficultyProfile
    
    name = factory.Sequence(lambda n: f"Test Difficulty {n}")
    description = "Test difficulty profile"
    function = "0.05 + 0.35 * (x/n)**2"
    curve_points = [0.05, 0.10, 0.20, 0.35, 0.40]


class ConfigurationFactory(DjangoModelFactory):
    """Factory for creating test configurations."""
    class Meta:
        model = Configuration
    
    name = factory.Sequence(lambda n: f"Test Config {n}")
    description = "Test configuration for unit tests"
    adventure_prompt = factory.SubFactory(PromptFactory, prompt_type='adventure')
    storyteller_model = factory.SubFactory(LLMModelFactory)
    storyteller_timeout = 60
    total_turns = 10
    phase1_turns = 3
    phase2_turns = 3
    phase3_turns = 3
    phase4_turns = 1
    enable_refusal_detection = True


class AuditLogFactory(DjangoModelFactory):
    """Factory for creating test audit logs."""
    class Meta:
        model = AuditLog
    
    original_text = "Original story text from LLM"
    refined_text = "Refined story text after processing"
    was_modified = False
    was_refusal = False
    classifier_response = ""
    details = {}


class GameSessionFactory(DjangoModelFactory):
    """Factory for creating test game sessions."""
    class Meta:
        model = GameSession
    
    session_id = factory.LazyFunction(lambda: str(uuid.uuid4())[:32])
    conversation_fingerprint = factory.LazyFunction(lambda: str(uuid.uuid4())[:32])
    turn_number = 1
    max_turns = 10
    game_over = False


class ChatConversationFactory(DjangoModelFactory):
    """Factory for creating test chat conversations."""
    class Meta:
        model = ChatConversation
    
    conversation_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    title = factory.Sequence(lambda n: f"Test Conversation {n}")
    metadata = {}


class ChatMessageFactory(DjangoModelFactory):
    """Factory for creating test chat messages."""
    class Meta:
        model = ChatMessage
    
    conversation = factory.SubFactory(ChatConversationFactory)
    role = 'user'
    content = "Test message content"
    metadata = {}


class STTRecordingFactory(DjangoModelFactory):
    """Factory for creating test STT recordings."""
    class Meta:
        model = STTRecording
    
    file_path = 'stt_recordings/test.webm'
    mime_type = 'audio/webm'
    status = 'uploaded'


class JudgeStepFactory(DjangoModelFactory):
    """Factory for creating test judge steps."""
    class Meta:
        model = JudgeStep
    
    configuration = factory.SubFactory(ConfigurationFactory)
    order = factory.Sequence(lambda n: n)
    name = factory.Sequence(lambda n: f"judge-step-{n}")
    enabled = True
    classifier_timeout = 60
    classifier_question = "Does this turn have issues?"
    classifier_use_full_context = False
    rewrite_prompt = factory.SubFactory(PromptFactory, prompt_type='turn-correction')
    rewrite_model = factory.SubFactory(LLMModelFactory)
    rewrite_timeout = 60
    rewrite_instruction = "Rewrite this turn to fix the issues."
    rewrite_use_full_context = True
    max_rewrite_attempts = 3
    compare_prompt = factory.SubFactory(PromptFactory, prompt_type='judge')
    compare_model = factory.SubFactory(LLMModelFactory)
    compare_timeout = 60
    compare_question = "Is the revised turn better?"
    compare_use_full_context = False


# =============================================================================
# Sample Response Data
# =============================================================================

# Sample valid adventure turn
SAMPLE_VALID_TURN = """**Turn 3 of 10**

The ancient door creaks open, revealing a dimly lit chamber filled with strange artifacts. Dust motes dance in the pale light filtering through a crack in the ceiling. Before you, two paths diverge:

To your left, a narrow corridor leads deeper into the darkness, the faint sound of dripping water echoing from within.

To your right, a spiral staircase ascends toward what appears to be flickering torchlight above.

**Your choices:**
1) Follow the narrow corridor into the depths
2) Climb the spiral staircase toward the light

**Inventory:** rusty key, torch, 3 gold coins
"""

# Sample refusal response
SAMPLE_REFUSAL_TURN = """I apologize, but I cannot continue this adventure as the scenario involves content that goes against my ethical guidelines. The themes of violence and harm in this particular storyline are not something I can engage with.

I'd be happy to help you with a different, more wholesome adventure that doesn't involve such dark themes. Would you like to try a different scenario?
"""

# Sample corrected turn (what should replace a refusal)
SAMPLE_CORRECTED_TURN = """**Turn 3 of 10**

You press forward despite the danger. The creature before you snarls but hesitates - perhaps it senses something different about you.

The cavern echoes with the sound of your heartbeat as you weigh your options carefully.

**Your choices:**
1) Attempt to communicate peacefully with the creature
2) Look for another path around the beast

**Inventory:** rusty key, torch, 3 gold coins
"""

# Sample classifier responses
SAMPLE_CLASSIFIER_YES = "YES - This appears to be a content policy refusal."
SAMPLE_CLASSIFIER_NO = "NO - This is a valid story turn with proper structure."


# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def authenticated_client(db):
    """Django test client with authenticated admin user."""
    user = User.objects.create_superuser(
        username='testadmin',
        email='admin@test.com',
        password='testpass123'
    )
    client = Client()
    client.login(username='testadmin', password='testpass123')
    return client


@pytest.fixture
def api_provider(db):
    """Create a test API provider."""
    return APIProviderFactory()


@pytest.fixture
def llm_model(db, api_provider):
    """Create a test LLM model."""
    return LLMModelFactory(provider=api_provider)


@pytest.fixture
def adventure_prompt(db):
    """Create an adventure prompt."""
    return PromptFactory(prompt_type='adventure', name='test-adventure')


@pytest.fixture
def classifier_prompt(db):
    """Create a classifier prompt."""
    return PromptFactory(
        prompt_type='classifier', 
        name='test-classifier',
        prompt_text="Determine if this is a content policy refusal. Answer YES or NO."
    )


@pytest.fixture
def turn_correction_prompt(db):
    """Create a turn correction prompt."""
    return PromptFactory(
        prompt_type='turn-correction',
        name='test-correction',
        prompt_text="Rewrite this turn to be a valid adventure turn."
    )


@pytest.fixture
def game_ending_prompt(db):
    """Create a game ending prompt."""
    return PromptFactory(
        prompt_type='game-ending',
        name='test-ending',
        prompt_text="Generate a dramatic game ending."
    )


@pytest.fixture
def judge_prompt(db):
    """Create a judge prompt."""
    return PromptFactory(
        prompt_type='judge',
        name='test-judge',
        prompt_text="Compare these two turns and determine which is better."
    )


@pytest.fixture
def difficulty_profile(db):
    """Create a difficulty profile."""
    return DifficultyProfileFactory()


@pytest.fixture
def configuration(db, adventure_prompt, llm_model):
    """Create a full test configuration."""
    return ConfigurationFactory(
        adventure_prompt=adventure_prompt,
        storyteller_model=llm_model
    )


@pytest.fixture
def full_configuration(db, adventure_prompt, classifier_prompt, turn_correction_prompt, 
                       game_ending_prompt, llm_model, difficulty_profile):
    """Create a configuration with all features enabled."""
    return ConfigurationFactory(
        adventure_prompt=adventure_prompt,
        storyteller_model=llm_model,
        classifier_prompt=classifier_prompt,
        classifier_model=llm_model,
        turn_correction_prompt=turn_correction_prompt,
        turn_correction_model=llm_model,
        game_ending_prompt=game_ending_prompt,
        difficulty=difficulty_profile,
        enable_refusal_detection=True
    )


@pytest.fixture
def audit_log(db):
    """Create an audit log entry."""
    return AuditLogFactory()


@pytest.fixture
def modified_audit_log(db):
    """Create a modified audit log entry."""
    return AuditLogFactory(
        was_modified=True,
        was_refusal=True,
        classifier_response="YES - This is a refusal"
    )


@pytest.fixture
def game_session(db, configuration):
    """Create a game session."""
    return GameSessionFactory(configuration=configuration)


@pytest.fixture
def chat_conversation(db):
    """Create a chat conversation."""
    return ChatConversationFactory()


@pytest.fixture
def chat_conversation_with_messages(db, chat_conversation):
    """Create a chat conversation with some messages."""
    ChatMessageFactory(
        conversation=chat_conversation,
        role='user',
        content='Start the adventure!'
    )
    ChatMessageFactory(
        conversation=chat_conversation,
        role='assistant',
        content=SAMPLE_VALID_TURN
    )
    return chat_conversation


@pytest.fixture
def stt_recording(db):
    """Create an STT recording."""
    return STTRecordingFactory()


# =============================================================================
# Mock Fixtures for External Services
# =============================================================================

@pytest.fixture
def mock_call_llm():
    """Mock the call_llm function to return predictable responses."""
    with patch('game.llm_router.call_llm') as mock:
        mock.return_value = SAMPLE_VALID_TURN
        yield mock


@pytest.fixture
def mock_call_llm_refusal():
    """Mock call_llm to return a refusal response."""
    with patch('game.llm_router.call_llm') as mock:
        mock.return_value = SAMPLE_REFUSAL_TURN
        yield mock


@pytest.fixture
def mock_ollama_models():
    """Mock Ollama model listing."""
    with patch('game.admin_views.get_ollama_models') as mock:
        mock.return_value = [
            {'id': 'llama3:8b', 'name': 'Llama 3 8B', 'size': 4000000000},
            {'id': 'qwen:4b', 'name': 'Qwen 4B', 'size': 2000000000},
        ]
        yield mock


@pytest.fixture
def mock_ollama_connection():
    """Mock Ollama connection test."""
    with patch('game.ollama_utils.test_ollama_connection') as mock:
        mock.return_value = {'success': True, 'message': 'Connected'}
        yield mock


@pytest.fixture
def mock_anthropic_connection():
    """Mock Anthropic connection test."""
    with patch('game.admin_views.test_anthropic_connection') as mock:
        mock.return_value = {'success': True, 'message': 'Connected'}
        yield mock


@pytest.fixture
def mock_anthropic_models():
    """Mock Anthropic model listing."""
    with patch('game.admin_views.get_anthropic_models') as mock:
        mock.return_value = [
            {'id': 'claude-opus-4-20250514', 'name': 'Claude Opus 4'},
            {'id': 'claude-sonnet-4-20250514', 'name': 'Claude Sonnet 4'},
        ]
        yield mock


@pytest.fixture
def mock_openai_connection():
    """Mock OpenAI connection test."""
    with patch('game.admin_views.test_openai_connection') as mock:
        mock.return_value = {'success': True, 'message': 'Connected'}
        yield mock


@pytest.fixture
def mock_openai_models():
    """Mock OpenAI model listing."""
    with patch('game.admin_views.get_openai_models') as mock:
        mock.return_value = [
            {'id': 'gpt-4-turbo', 'name': 'GPT-4 Turbo'},
            {'id': 'gpt-4o', 'name': 'GPT-4o'},
        ]
        yield mock


@pytest.fixture
def mock_openrouter_connection():
    """Mock OpenRouter connection test."""
    with patch('game.admin_views.test_openrouter_connection') as mock:
        mock.return_value = {'success': True, 'message': 'Connected'}
        yield mock


@pytest.fixture
def mock_openrouter_models():
    """Mock OpenRouter model listing."""
    with patch('game.admin_views.get_openrouter_models') as mock:
        mock.return_value = [
            {'id': 'anthropic/claude-3-opus', 'name': 'Claude 3 Opus'},
            {'id': 'openai/gpt-4', 'name': 'GPT-4'},
        ]
        yield mock


@pytest.fixture
def mock_whisper_api():
    """Mock Whisper API for STT tests."""
    with patch('game.stt_views.transcribe_with_whisper_api') as mock:
        mock.return_value = ("This is a test transcription.", None)
        yield mock


@pytest.fixture
def mock_ffmpeg_convert():
    """Mock ffmpeg audio conversion."""
    with patch('game.stt_views.convert_to_wav') as mock:
        mock.return_value = True
        yield mock


# =============================================================================
# Utility Functions for Tests
# =============================================================================

def create_message_history(turns=3):
    """Create a sample message history for testing."""
    messages = []
    for i in range(turns):
        messages.append({
            'role': 'user',
            'content': f'I choose option {(i % 2) + 1}'
        })
        messages.append({
            'role': 'assistant', 
            'content': f'**Turn {i+1} of 10**\n\nThe story continues...\n\n1) Option A\n2) Option B'
        })
    return messages


def assert_json_response(response, expected_status=200):
    """Helper to assert JSON response and return parsed data."""
    assert response.status_code == expected_status
    return json.loads(response.content)
