# CYOA Game Server Testing Framework

## Overview

This testing framework provides comprehensive test coverage for the CYOA (Choose Your Own Adventure) LLM game server. It uses **pytest** with **pytest-django** as the industry-standard testing framework.

## Quick Start

```bash
# Install dependencies
pip3 install pytest pytest-django pytest-cov pytest-mock factory-boy freezegun responses

# Run all tests
cd cyoa-game-server
./run_tests.sh

# Run with coverage
./run_tests.sh --cov

# Run specific test file
./run_tests.sh tests/test_admin_views.py

# Run specific test class
./run_tests.sh -k "TestDashboard"

# Run only unit tests
./run_tests.sh -m unit

# Run only integration tests  
./run_tests.sh -m integration
```

## Test Structure

```
cyoa-game-server/
├── pytest.ini                 # Pytest configuration
├── setup.cfg                  # Coverage configuration
├── run_tests.sh              # Test runner script
└── tests/
    ├── __init__.py
    ├── conftest.py           # Shared fixtures and factories
    ├── test_admin_views.py   # Admin interface tests
    ├── test_chat_views.py    # Chat API tests
    ├── test_stt_views.py     # Speech-to-text tests
    ├── test_judge_pipeline.py # Judge pipeline tests
    └── fixtures/
        ├── __init__.py
        ├── llm_responses.json # Sample LLM responses
        └── audio_utils.py     # Audio file generation
```

## Key Components

### Model Factories (`conftest.py`)

Factory Boy factories for creating test data:

- `APIProviderFactory` - API provider instances
- `LLMModelFactory` - LLM model configurations  
- `PromptFactory` - Various prompt types
- `ConfigurationFactory` - Game configurations
- `AuditLogFactory` - Audit log entries
- `GameSessionFactory` - Game session state
- `ChatConversationFactory` - Chat conversations
- `ChatMessageFactory` - Individual messages
- `STTRecordingFactory` - Audio recordings
- `JudgeStepFactory` - Judge pipeline steps
- `DifficultyProfileFactory` - Difficulty profiles

### Mock Fixtures

Pre-configured mocks for external services:

- `mock_call_llm` - Mocks LLM API calls
- `mock_ollama_models` - Mocks Ollama model listing
- `mock_ollama_connection` - Mocks Ollama connection test
- `mock_anthropic_connection` - Mocks Anthropic connection
- `mock_anthropic_models` - Mocks Anthropic model listing
- `mock_openai_connection` - Mocks OpenAI connection
- `mock_openai_models` - Mocks OpenAI model listing
- `mock_openrouter_connection` - Mocks OpenRouter connection
- `mock_openrouter_models` - Mocks OpenRouter model listing
- `mock_whisper_api` - Mocks Whisper transcription
- `mock_ffmpeg_convert` - Mocks audio conversion

### Sample Data

Sample LLM responses for testing:

- `SAMPLE_VALID_TURN` - Valid adventure turn with choices
- `SAMPLE_REFUSAL_TURN` - Content policy refusal response
- `SAMPLE_CORRECTED_TURN` - Corrected turn after refusal
- `SAMPLE_CLASSIFIER_YES` - Classifier positive response
- `SAMPLE_CLASSIFIER_NO` - Classifier negative response

## Test Categories

### Unit Tests (`@pytest.mark.unit`)

Test individual functions in isolation:

- `extract_game_state()` parsing
- `_parse_boolean_response()` logic
- `_build_context_messages()` construction
- `convert_to_wav()` with mocked subprocess
- `transcribe_with_whisper_api()` with mocked requests

### Integration Tests (`@pytest.mark.integration`)

Test full request/response flows:

- Complete game workflow (start → play → end)
- Full STT flow (upload → transcribe → retrieve → discard)
- Provider → model import workflow
- Prompt creation → versioning workflow

## Test Files

### `test_admin_views.py`

Tests for the admin interface including:

- Dashboard statistics
- Audit log viewing/filtering
- Prompt CRUD operations
- Configuration management
- Provider/model management
- Difficulty profiles
- API endpoints (markdown preview, etc.)

### `test_chat_views.py`

Tests for the chat API including:

- Conversation creation
- Message sending with mocked LLM
- Game state extraction
- Refusal detection/correction
- Judge pipeline execution
- Conversation history retrieval

### `test_stt_views.py`

Tests for speech-to-text including:

- Audio file upload
- Transcription with mocked Whisper
- Recording status retrieval
- Recording discard/cleanup
- Error handling

### `test_judge_pipeline.py`

Tests for the judge pipeline including:

- Classifier phase
- Rewriter phase with retries
- Comparator phase
- Multi-step pipelines
- Error handling

## Writing New Tests

### Example Test Structure

```python
@pytest.mark.django_db
class TestFeatureName:
    """Tests for feature description."""
    
    def test_basic_functionality(self, client, db, configuration):
        """Test the happy path."""
        # Setup
        # Action
        # Assert
    
    def test_error_handling(self, client, db):
        """Test error cases."""
        pass
    
    @patch('game.module.external_call')
    def test_with_mock(self, mock_call, client, db):
        """Test with mocked external dependency."""
        mock_call.return_value = "mocked response"
        # ...
```

### Using Factories

```python
# Create a basic model
prompt = PromptFactory()

# Create with specific attributes
prompt = PromptFactory(
    prompt_type='adventure',
    name='my-adventure',
    version=2
)

# Create related objects
config = ConfigurationFactory(
    adventure_prompt=PromptFactory(prompt_type='adventure'),
    storyteller_model=LLMModelFactory()
)
```

### Mocking LLM Calls

```python
@patch('game.chat_views.call_llm')
@patch('game.chat_views.process_potential_refusal')
@patch('game.chat_views.run_judge_pipeline')
def test_chat_flow(self, mock_judge, mock_refusal, mock_llm, client, db):
    mock_llm.return_value = SAMPLE_VALID_TURN
    mock_refusal.return_value = {
        'final_turn': SAMPLE_VALID_TURN,
        'was_refusal': False,
        'classifier_response': '',
        'was_corrected': False
    }
    mock_judge.return_value = {
        'final_turn': SAMPLE_VALID_TURN,
        'was_modified': False,
        'steps': []
    }
    # ... test code
```

## Coverage Reports

Generate HTML coverage reports:

```bash
./run_tests.sh --cov
# Open htmlcov/index.html in browser
```

Coverage targets:
- Aim for >80% coverage on critical paths
- Focus on business logic over boilerplate
- Exclude migrations and generated code

## Continuous Integration

Add to CI/CD pipeline:

```yaml
# Example GitHub Actions
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
    - name: Run tests
      run: |
        cd cyoa-game-server
        ./run_tests.sh --cov
```

## Troubleshooting

### Common Issues

1. **Database not created**: Ensure `@pytest.mark.django_db` decorator is present
2. **Mock not applied**: Check mock path matches actual import location
3. **Factory errors**: Ensure all required foreign keys have subfactories

### Debug Mode

```bash
# Run with verbose output
./run_tests.sh -vvv

# Stop on first failure
./run_tests.sh -x

# Show print statements
./run_tests.sh -s

# Run specific test with debugging
./run_tests.sh -k "test_name" -vvv -s
```
