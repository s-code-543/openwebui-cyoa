"""
Tests for judge_pipeline.py - Judge Pipeline Evaluation

This module tests the judge pipeline including:
- Boolean response parsing
- Context message building
- Full pipeline execution with classifier/rewriter/comparator phases
- Retry logic and failure handling

Test Categories:
- Unit tests: Individual functions with mocked LLM calls
- Integration tests: Full pipeline execution scenarios
"""
import pytest
from unittest.mock import patch, MagicMock

from game.judge_pipeline import (
    _parse_boolean_response,
    _build_context_messages,
    run_judge_pipeline
)
from game.models import JudgeStep, Configuration, Prompt, LLMModel
from tests.conftest import (
    ConfigurationFactory, JudgeStepFactory, PromptFactory,
    LLMModelFactory, APIProviderFactory,
    SAMPLE_VALID_TURN, SAMPLE_CORRECTED_TURN
)


# =============================================================================
# Unit Tests for Helper Functions
# =============================================================================

@pytest.mark.unit
class TestParseBooleanResponse:
    """Unit tests for _parse_boolean_response function."""
    
    def test_parses_yes(self):
        """Parses 'YES' as True."""
        assert _parse_boolean_response("YES") is True
        assert _parse_boolean_response("yes") is True
        assert _parse_boolean_response("Yes") is True
    
    def test_parses_no(self):
        """Parses 'NO' as False."""
        assert _parse_boolean_response("NO") is False
        assert _parse_boolean_response("no") is False
        assert _parse_boolean_response("No") is False
    
    def test_parses_true_false(self):
        """Parses TRUE/FALSE strings."""
        assert _parse_boolean_response("TRUE") is True
        assert _parse_boolean_response("FALSE") is False
    
    def test_parses_pass_fail(self):
        """Parses PASS/FAIL strings."""
        assert _parse_boolean_response("PASS") is True
        assert _parse_boolean_response("FAIL") is False
    
    def test_parses_with_surrounding_text(self):
        """Parses responses with additional explanation text."""
        assert _parse_boolean_response("YES - This is a refusal") is True
        assert _parse_boolean_response("NO - This looks fine") is False
        assert _parse_boolean_response("The answer is YES because...") is True
    
    def test_handles_whitespace(self):
        """Handles leading/trailing whitespace."""
        assert _parse_boolean_response("  YES  ") is True
        assert _parse_boolean_response("\nNO\n") is False
    
    def test_returns_default_for_empty(self):
        """Returns default for empty or None input."""
        assert _parse_boolean_response("") is False
        assert _parse_boolean_response(None) is False
        assert _parse_boolean_response("", default=True) is True
    
    def test_returns_default_for_ambiguous(self):
        """Returns default for ambiguous responses."""
        assert _parse_boolean_response("maybe") is False
        assert _parse_boolean_response("I'm not sure") is False
        assert _parse_boolean_response("possibly", default=True) is True


@pytest.mark.unit
class TestBuildContextMessages:
    """Unit tests for _build_context_messages function."""
    
    def test_full_context_returns_messages(self):
        """With full context, returns all messages."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'}
        ]
        turn_text = "Current turn text"
        
        result = _build_context_messages(messages, turn_text, use_full_context=True)
        
        assert len(result) == 2
        assert result[0]['content'] == 'Hello'
        assert result[1]['content'] == 'Hi there'
    
    def test_no_context_returns_turn_only(self):
        """Without full context, returns only turn text."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there'}
        ]
        turn_text = "Current turn text"
        
        result = _build_context_messages(messages, turn_text, use_full_context=False)
        
        assert len(result) == 1
        assert result[0]['role'] == 'user'
        assert result[0]['content'] == turn_text
    
    def test_creates_copy_of_messages(self):
        """Creates a copy, doesn't modify original."""
        messages = [{'role': 'user', 'content': 'Original'}]
        
        result = _build_context_messages(messages, "turn", use_full_context=True)
        
        assert result is not messages


# =============================================================================
# Unit Tests for Pipeline Components
# =============================================================================

@pytest.mark.django_db
class TestJudgePipelineNoSteps:
    """Tests for pipeline with no judge steps configured."""
    
    def test_returns_original_turn_when_no_config(self):
        """Returns original turn unchanged when no config."""
        result = run_judge_pipeline([], "Original turn", None)
        
        assert result['final_turn'] == "Original turn"
        assert result['was_modified'] is False
        assert result['steps'] == []
    
    def test_returns_original_turn_when_no_steps(self, db, configuration):
        """Returns original turn unchanged when config has no judge steps."""
        # Ensure no judge steps
        JudgeStep.objects.filter(configuration=configuration).delete()
        
        result = run_judge_pipeline([], "Original turn", configuration)
        
        assert result['final_turn'] == "Original turn"
        assert result['was_modified'] is False


@pytest.mark.django_db
class TestJudgePipelineClassifier:
    """Tests for classifier phase of judge pipeline."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_skips_rewrite_when_classifier_says_no(self, mock_llm, db):
        """Skips rewrite phase if classifier returns NO."""
        # Create configuration with judge step
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        classifier_prompt = PromptFactory(prompt_type='classifier')
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-classifier',
            enabled=True,
            classifier_prompt=classifier_prompt,
            classifier_model=model,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        # Mock classifier to say NO (no correction needed)
        mock_llm.return_value = "NO - This turn is valid"
        
        result = run_judge_pipeline([], SAMPLE_VALID_TURN, config)
        
        assert result['final_turn'] == SAMPLE_VALID_TURN
        assert result['was_modified'] is False
        assert len(result['steps']) == 1
        assert result['steps'][0]['needs_correction'] is False
    
    @patch('game.judge_pipeline.call_llm')
    def test_proceeds_to_rewrite_when_classifier_says_yes(self, mock_llm, db):
        """Proceeds to rewrite when classifier returns YES."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        classifier_prompt = PromptFactory(prompt_type='classifier')
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-classifier',
            enabled=True,
            classifier_prompt=classifier_prompt,
            classifier_model=model,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        # Mock: classifier says YES, rewrite produces new turn, comparator approves
        mock_llm.side_effect = [
            "YES - Needs correction",  # Classifier
            SAMPLE_CORRECTED_TURN,      # Rewriter
            "YES - Rewrite is better"   # Comparator
        ]
        
        result = run_judge_pipeline([], "Problematic turn", config)
        
        assert result['was_modified'] is True
        assert result['final_turn'] == SAMPLE_CORRECTED_TURN


@pytest.mark.django_db
class TestJudgePipelineRewriter:
    """Tests for rewriter phase of judge pipeline."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_always_rewrites_when_no_classifier(self, mock_llm, db):
        """Always attempts rewrite when no classifier configured."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        # Judge step without classifier
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-no-classifier',
            enabled=True,
            classifier_prompt=None,
            classifier_model=None,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        mock_llm.side_effect = [
            SAMPLE_CORRECTED_TURN,  # Rewriter
            "YES"                    # Comparator
        ]
        
        result = run_judge_pipeline([], "Original", config)
        
        # Should have gone straight to rewrite
        assert result['was_modified'] is True
    
    @patch('game.judge_pipeline.call_llm')
    def test_retries_rewrite_on_rejection(self, mock_llm, db):
        """Retries rewrite if comparator rejects first attempt."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-retry',
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model,
            max_rewrite_attempts=3
        )
        
        mock_llm.side_effect = [
            "Bad rewrite",    # First rewrite
            "NO",             # First comparison - rejected
            "Better rewrite", # Second rewrite
            "YES"             # Second comparison - approved
        ]
        
        result = run_judge_pipeline([], "Original", config)
        
        assert result['was_modified'] is True
        assert result['final_turn'] == "Better rewrite"
        assert len(result['steps'][0]['attempts']) == 2
    
    @patch('game.judge_pipeline.call_llm')
    def test_keeps_original_when_all_rewrites_rejected(self, mock_llm, db):
        """Keeps original when all rewrite attempts are rejected."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-all-fail',
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model,
            max_rewrite_attempts=2
        )
        
        mock_llm.side_effect = [
            "Attempt 1",  # First rewrite
            "NO",         # First comparison - rejected
            "Attempt 2",  # Second rewrite
            "NO"          # Second comparison - rejected
        ]
        
        original = "Original turn"
        result = run_judge_pipeline([], original, config)
        
        assert result['was_modified'] is False
        assert result['final_turn'] == original
        assert result['steps'][0]['final_used'] == 'original'


@pytest.mark.django_db
class TestJudgePipelineComparator:
    """Tests for comparator phase of judge pipeline."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_uses_full_context_when_configured(self, mock_llm, db):
        """Uses full message history when compare_use_full_context is True."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-context',
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            rewrite_use_full_context=True,
            compare_prompt=compare_prompt,
            compare_model=model,
            compare_use_full_context=False
        )
        
        mock_llm.side_effect = ["Rewrite", "YES"]
        
        messages = [
            {'role': 'user', 'content': 'Previous message'},
            {'role': 'assistant', 'content': 'Previous response'}
        ]
        
        run_judge_pipeline(messages, "Current turn", config)
        
        # Check that rewriter received full context
        rewrite_call = mock_llm.call_args_list[0]
        rewrite_messages = rewrite_call[1]['messages']
        assert len(rewrite_messages) > 1  # Has context


@pytest.mark.django_db
class TestJudgePipelineMultipleSteps:
    """Tests for pipeline with multiple judge steps."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_runs_steps_in_order(self, mock_llm, db):
        """Runs judge steps in configured order."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        # Create two steps
        step1 = JudgeStep.objects.create(
            configuration=config,
            name='step-1',
            order=1,
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        step2 = JudgeStep.objects.create(
            configuration=config,
            name='step-2',
            order=2,
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        mock_llm.side_effect = [
            "Step 1 rewrite",  # Step 1 rewriter
            "YES",             # Step 1 comparator
            "Step 2 rewrite",  # Step 2 rewriter
            "YES"              # Step 2 comparator
        ]
        
        result = run_judge_pipeline([], "Original", config)
        
        assert len(result['steps']) == 2
        assert result['steps'][0]['name'] == 'step-1'
        assert result['steps'][1]['name'] == 'step-2'
        assert result['final_turn'] == "Step 2 rewrite"
    
    @patch('game.judge_pipeline.call_llm')
    def test_skips_disabled_steps(self, mock_llm, db):
        """Skips disabled judge steps."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        # One enabled, one disabled
        step1 = JudgeStep.objects.create(
            configuration=config,
            name='enabled-step',
            order=1,
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        step2 = JudgeStep.objects.create(
            configuration=config,
            name='disabled-step',
            order=2,
            enabled=False,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        mock_llm.side_effect = ["Rewrite", "YES"]
        
        result = run_judge_pipeline([], "Original", config)
        
        # Only enabled step should run
        assert len(result['steps']) == 1
        assert result['steps'][0]['name'] == 'enabled-step'
    
    @patch('game.judge_pipeline.call_llm')
    def test_passes_modified_turn_to_next_step(self, mock_llm, db):
        """Each step receives the output of the previous step."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step1 = JudgeStep.objects.create(
            configuration=config,
            name='step-1',
            order=1,
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        step2 = JudgeStep.objects.create(
            configuration=config,
            name='step-2',
            order=2,
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        # Step 1 modifies, step 2 keeps
        mock_llm.side_effect = [
            "Modified by step 1",  # Step 1 rewriter
            "YES",                  # Step 1 comparator approves
            "Would be step 2",      # Step 2 rewriter
            "NO"                    # Step 2 comparator rejects
        ]
        
        result = run_judge_pipeline([], "Original", config)
        
        # Final should be step 1's modification (step 2 rejected)
        assert result['final_turn'] == "Modified by step 1"


@pytest.mark.django_db
class TestJudgePipelineErrorHandling:
    """Tests for error handling in judge pipeline."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_handles_llm_error_gracefully(self, mock_llm, db):
        """Continues with original on LLM error."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-error',
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        mock_llm.side_effect = Exception("LLM API Error")
        
        original = "Original turn"
        result = run_judge_pipeline([], original, config)
        
        # Should fall back to original
        assert result['final_turn'] == original
        assert result['steps'][0]['error'] is not None
    
    @patch('game.judge_pipeline.call_llm')
    def test_records_error_in_step_result(self, mock_llm, db):
        """Records error details in step result."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='test-error-record',
            enabled=True,
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            compare_prompt=compare_prompt,
            compare_model=model
        )
        
        mock_llm.side_effect = Exception("Connection timeout")
        
        result = run_judge_pipeline([], "Original", config)
        
        assert 'error' in result['steps'][0]
        assert 'timeout' in result['steps'][0]['error'].lower()


# =============================================================================
# Integration Tests
# =============================================================================

@pytest.mark.django_db
@pytest.mark.integration
class TestJudgePipelineIntegration:
    """Integration tests for full judge pipeline scenarios."""
    
    @patch('game.judge_pipeline.call_llm')
    def test_complete_pipeline_with_all_phases(self, mock_llm, db):
        """Test complete pipeline with classifier, rewriter, and comparator."""
        provider = APIProviderFactory()
        model = LLMModelFactory(provider=provider)
        classifier_prompt = PromptFactory(prompt_type='classifier')
        rewrite_prompt = PromptFactory(prompt_type='turn-correction')
        compare_prompt = PromptFactory(prompt_type='judge')
        config = ConfigurationFactory()
        
        step = JudgeStep.objects.create(
            configuration=config,
            name='full-pipeline',
            enabled=True,
            classifier_prompt=classifier_prompt,
            classifier_model=model,
            classifier_question="Is this turn problematic?",
            rewrite_prompt=rewrite_prompt,
            rewrite_model=model,
            rewrite_instruction="Fix the issues",
            compare_prompt=compare_prompt,
            compare_model=model,
            compare_question="Is the rewrite better?",
            max_rewrite_attempts=2
        )
        
        # Classifier flags issue, first rewrite rejected, second approved
        mock_llm.side_effect = [
            "YES - Turn has issues",     # Classifier
            "Bad rewrite attempt",       # First rewrite
            "NO - Original was better",  # First comparison
            SAMPLE_CORRECTED_TURN,       # Second rewrite
            "YES - Much better now"      # Second comparison
        ]
        
        messages = [
            {'role': 'user', 'content': 'Start game'},
            {'role': 'assistant', 'content': 'Turn 1...'}
        ]
        
        result = run_judge_pipeline(messages, "Problematic turn", config)
        
        # Verify result
        assert result['was_modified'] is True
        assert result['final_turn'] == SAMPLE_CORRECTED_TURN
        
        # Verify step details
        step_result = result['steps'][0]
        assert step_result['needs_correction'] is True
        assert len(step_result['attempts']) == 2
        assert step_result['attempts'][0]['approved'] is False
        assert step_result['attempts'][1]['approved'] is True
        assert step_result['used_rewrite'] is True
