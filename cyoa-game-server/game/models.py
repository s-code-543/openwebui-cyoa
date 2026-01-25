"""
Models for CYOA game server.
"""
from django.db import models
from django.utils import timezone
import hashlib
import uuid


class Prompt(models.Model):
    """
    Store different versions of prompts for the game.
    prompt_type categories:
    - 'adventure': Story/adventure prompts for storytelling
    - 'turn-correction': Prompts for correcting refused turns (both regular and game-ending)
    - 'game-ending': Prompts for generating death/failure scenes
    - 'classifier': Prompts for detecting refusals
    - 'judge': Prompts for evaluating and comparing turn quality
    
    Each prompt has its own title/name for identification within its type.
    """
    
    # User-friendly display names for prompt types
    PROMPT_TYPE_DISPLAY = {
        'adventure': 'Adventure Prompts',
        'turn-correction': 'Turn Correction Prompts',
        'game-ending': 'Game Ending Prompts',
        'classifier': 'Classifier Prompts',
        'judge': 'Judge Prompts',
    }
    
    prompt_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Category: adventure, turn-correction, game-ending, classifier, judge"
    )
    name = models.CharField(
        max_length=100,
        db_index=True,
        default='default',
        help_text="Descriptive name for this prompt (e.g., 'haunted-house', 'correct_refusal')"
    )
    version = models.IntegerField(
        help_text="Version number (1, 2, 3, ...)"
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="User-friendly description of this version"
    )
    prompt_text = models.TextField(
        help_text="The actual prompt content"
    )
    file_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Path to the source .txt file for this prompt (relative to cyoa_prompts/)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['prompt_type', 'name', 'version']
        ordering = ['prompt_type', 'name', '-version']
        indexes = [
            models.Index(fields=['prompt_type', 'name']),
        ]
    
    def __str__(self):
        return f"{self.prompt_type}/{self.name} v{self.version}"
    
    @classmethod
    def get_type_display_name(cls, prompt_type):
        """Get user-friendly display name for a prompt type."""
        return cls.PROMPT_TYPE_DISPLAY.get(prompt_type, prompt_type.replace('-', ' ').title())
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """
    Track corrections made by the judge to storyteller outputs.
    """
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    original_text = models.TextField(
        help_text="Original output from storyteller LLM"
    )
    refined_text = models.TextField(
        help_text="Final output after judge review"
    )
    was_modified = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if judge made changes, False if passed through unchanged"
    )
    prompt_used = models.ForeignKey(
        Prompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Which judge prompt was active during this request"
    )
    # Refusal detection fields
    was_refusal = models.BooleanField(
        default=False,
        help_text="True if this was detected as a refusal"
    )
    classifier_response = models.TextField(
        blank=True,
        help_text="Raw response from classifier model"
    )
    correction_prompt_used = models.ForeignKey(
        Prompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='correction_logs',
        help_text="Judge prompt used for correction (if refusal was detected)"
    )
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured details for judge pipelines or other processing"
    )
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'was_modified']),
        ]
    
    def __str__(self):
        modified = "MODIFIED" if self.was_modified else "UNCHANGED"
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {modified}"


class Configuration(models.Model):
    """
    Store preset configurations combining adventure prompt, models, and judge prompt.
    Only one configuration can be active at a time.
    """
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Name for this configuration preset"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this configuration"
    )
    adventure_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_adventure',
        limit_choices_to={'prompt_type': 'adventure'},
        help_text="Adventure/story prompt to use"
    )
    storyteller_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='configs_as_storyteller',
        null=True,
        help_text="Model to use for story generation"
    )
    storyteller_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for storyteller generation (default: 60)"
    )
    turn_correction_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_turn_correction',
        limit_choices_to={'prompt_type': 'turn-correction'},
        null=True,
        blank=True,
        help_text="Turn correction prompt for regenerating refused turns (only needed if refusal detection enabled)"
    )
    turn_correction_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='configs_as_turn_correction',
        null=True,
        blank=True,
        help_text="Model to use for turn correction (only needed if refusal detection enabled)"
    )
    turn_correction_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for turn correction (default: 60)"
    )
    game_ending_turn_correction_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_game_ending_turn_correction',
        limit_choices_to={'prompt_type': 'turn-correction'},
        null=True,
        blank=True,
        help_text="Turn correction prompt specifically for game-ending turns (optional, falls back to turn_correction_prompt)"
    )
    game_ending_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_game_ending',
        limit_choices_to={'prompt_type': 'game-ending'},
        null=True,
        blank=True,
        help_text="Prompt to use when game ends due to death/failure"
    )
    difficulty = models.ForeignKey(
        'DifficultyProfile',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Difficulty profile for death probability curve"
    )
    total_turns = models.IntegerField(
        default=10,
        choices=[(5, '5 turns'), (10, '10 turns'), (15, '15 turns'), (20, '20 turns')],
        help_text="Total number of turns in the adventure"
    )
    phase1_turns = models.IntegerField(
        default=3,
        help_text="Turns for Phase 1: Introduction/Exposition/Story Building"
    )
    phase2_turns = models.IntegerField(
        default=3,
        help_text="Turns for Phase 2: Victory/Loss Conditions"
    )
    phase3_turns = models.IntegerField(
        default=3,
        help_text="Turns for Phase 3: Progress/Narrative Twists"
    )
    phase4_turns = models.IntegerField(
        default=1,
        help_text="Turns for Phase 4: Finale/Conclusion Setup"
    )
    # Refusal detection system
    enable_refusal_detection = models.BooleanField(
        default=True,
        help_text="Enable automatic refusal detection and correction"
    )
    classifier_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='configs_as_classifier',
        null=True,
        blank=True,
        help_text="Model to use for refusal classification"
    )
    classifier_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_classifier',
        limit_choices_to={'prompt_type': 'classifier'},
        null=True,
        blank=True,
        help_text="Prompt to use for detecting refusals"
    )
    classifier_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for classifier (default: 60)"
    )
    classifier_question = models.TextField(
        default="Is this a content policy refusal?",
        help_text="Question to ask the classifier along with the story turn text"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return self.name
    
    @staticmethod
    def get_default_pacing(total_turns):
        """
        Get default pacing for a given number of turns.
        Returns tuple of (phase1, phase2, phase3, phase4)
        """
        pacing_defaults = {
            5: (1, 1, 2, 1),
            10: (3, 3, 3, 1),
            15: (4, 5, 4, 2),
            20: (5, 6, 6, 3),
        }
        return pacing_defaults.get(total_turns, (3, 3, 3, 1))
    
    def get_pacing_dict(self):
        """Return pacing information as a dictionary for template substitution."""
        return {
            'TOTAL_TURNS': self.total_turns,
            'PHASE1_TURNS': self.phase1_turns,
            'PHASE2_TURNS': self.phase2_turns,
            'PHASE3_TURNS': self.phase3_turns,
            'PHASE4_TURNS': self.phase4_turns,
            'PHASE1_END': self.phase1_turns,
            'PHASE2_END': self.phase1_turns + self.phase2_turns,
            'PHASE3_END': self.phase1_turns + self.phase2_turns + self.phase3_turns,
            'PHASE4_END': self.total_turns,
        }
    @classmethod
    def wait_for_response(cls, cache_key, timeout=30.0, poll_interval=0.5):
        """
        Poll for ANY cached response created AFTER we started waiting.
        SIMPLIFIED: There's never more than one simultaneous call, so just grab the latest.
        Cache collisions (wrong game) are better than timeouts (no game).
        """
        import time
        start_time = time.time()
        # Allow 2-second grace period for responses created just before we started
        wait_start = timezone.now() - timezone.timedelta(seconds=2)
        print(f"[CACHE] Waiting for responses created after {wait_start.strftime('%H:%M:%S')}")
        
        while (time.time() - start_time) < timeout:
            # Get the most recent entry created after we started waiting (minus grace period)
            latest = cls.objects.filter(created_at__gte=wait_start).order_by('-created_at').first()
            if latest:
                age = (timezone.now() - latest.created_at).total_seconds()
                print(f"[CACHE] ✓ Found response {latest.cache_key} ({age:.1f}s old, {len(latest.response_text)} chars)")
                return latest.response_text
            time.sleep(poll_interval)
        print(f"[CACHE] ✗ Timeout - no responses created since {wait_start.strftime('%H:%M:%S')}")
        return None
    
    @classmethod
    def cleanup_old_entries(cls, max_age_seconds=3600):
        """
        Delete cache entries older than max_age_seconds.
        Should be called periodically (e.g., via management command or cron).
        """
        cutoff = timezone.now() - timezone.timedelta(seconds=max_age_seconds)
        deleted_count, _ = cls.objects.filter(created_at__lt=cutoff).delete()
        return deleted_count


class JudgeStep(models.Model):
    """
    Configurable judge pipeline step for post-processing story turns.
    Each step evaluates a turn, optionally rewrites it, then compares the result.
    """
    configuration = models.ForeignKey(
        Configuration,
        on_delete=models.CASCADE,
        related_name='judge_steps',
        help_text="Configuration this judge step belongs to"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Execution order (lower runs first)"
    )
    name = models.CharField(
        max_length=100,
        default='judge',
        help_text="Short label for this judge step (e.g., 'difficulty')"
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Enable this judge step"
    )
    
    # === CLASSIFIER PHASE ===
    # Evaluates single turn: "Does this need fixing?" (optional - skip to always rewrite)
    classifier_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='judge_steps_as_classifier',
        limit_choices_to={'prompt_type': 'classifier'},
        null=True,
        blank=True,
        help_text="Classifier prompt (optional - if omitted, always proceeds to rewrite)"
    )
    classifier_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='judge_steps_as_classifier',
        null=True,
        blank=True,
        help_text="Model for classification"
    )
    classifier_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for classification"
    )
    classifier_question = models.TextField(
        default="Does this turn have issues that make it invalid?",
        help_text="Question to ask classifier about the turn"
    )
    classifier_use_full_context = models.BooleanField(
        default=False,
        help_text="Use full message history (true) or just turn text (false)"
    )
    
    # === REWRITER PHASE ===
    # Corrects/rewrites the turn using context
    rewrite_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='judge_steps_as_rewriter',
        limit_choices_to={'prompt_type': 'turn-correction'},
        help_text="Turn correction prompt for rewriting"
    )
    rewrite_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='judge_steps_as_rewriter',
        help_text="Model for rewriting turns"
    )
    rewrite_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for rewrite generation"
    )
    rewrite_instruction = models.TextField(
        default="Re-write this text to be a valid choose your own adventure turn following all the rules:",
        blank=True,
        help_text="Additional instruction appended to rewrite request"
    )
    rewrite_use_full_context = models.BooleanField(
        default=True,
        help_text="Use full message history (true) or just turn text (false)"
    )
    max_rewrite_attempts = models.IntegerField(
        default=3,
        help_text="Maximum rewrite attempts before giving up"
    )
    
    # === COMPARE PHASE ===
    # Judges original vs rewritten: "Is the rewrite better?"
    compare_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='judge_steps_as_comparator',
        limit_choices_to={'prompt_type': 'judge'},
        help_text="Judge prompt to compare original vs rewritten turn"
    )
    compare_model = models.ForeignKey(
        'LLMModel',
        on_delete=models.PROTECT,
        related_name='judge_steps_as_comparator',
        help_text="Model for comparing turns"
    )
    compare_timeout = models.IntegerField(
        default=60,
        help_text="Timeout in seconds for comparison"
    )
    compare_question = models.TextField(
        default="Is the revised turn better and more valid than the original?",
        help_text="Question to ask when comparing original vs rewritten turn"
    )
    compare_use_full_context = models.BooleanField(
        default=False,
        help_text="Use full message history (true) or just the two turns (false)"
    )

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"{self.configuration.name} - {self.name} ({status})"


class APIProvider(models.Model):
    """
    External API provider configurations (external Ollama, Anthropic, etc.)
    """
    PROVIDER_TYPES = [
        ('ollama', 'Ollama Server'),
        ('anthropic', 'Anthropic (Claude)'),
        ('openai', 'OpenAI (GPT)'),
        ('openrouter', 'OpenRouter'),
    ]
    
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Friendly name for this provider (e.g., 'Office Ollama', 'My Anthropic')"
    )
    provider_type = models.CharField(
        max_length=50,
        choices=PROVIDER_TYPES,
        help_text="Type of API provider"
    )
    base_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Base URL for API (e.g., 'http://192.168.1.100:11434' for Ollama)"
    )
    api_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="API key for authentication (if required)"
    )
    is_local = models.BooleanField(
        default=False,
        help_text="True if this connects to localhost (use localhost instead of docker network name)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this provider is currently active"
    )
    last_tested = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time connection was successfully tested"
    )
    test_status = models.CharField(
        max_length=500,
        blank=True,
        help_text="Result of last connection test"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['provider_type', 'name']
    
    def __str__(self):
        status = " ✓" if self.is_active else " ✗"
        return f"{self.name} ({self.provider_type}){status}"


class LLMModel(models.Model):
    """
    Registered LLM models (from any provider) with routing information.
    Replaces name-based routing logic with explicit database configuration.
    """
    
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Display name for this model (shown in config dropdowns)"
    )
    model_identifier = models.CharField(
        max_length=200,
        help_text="Backend model identifier (e.g., 'qwen3:4b', 'claude-opus-4')"
    )
    provider = models.ForeignKey(
        APIProvider,
        on_delete=models.CASCADE,
        help_text="Provider hosting this model"
    )
    is_available = models.BooleanField(
        default=True,
        help_text="Whether this model is currently available for use"
    )
    capabilities = models.JSONField(
        default=dict,
        blank=True,
        help_text="Model capabilities and metadata"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['provider__name', 'name']
    
    def __str__(self):
        status = "✓" if self.is_available else "✗"
        return f"{self.provider.name}: {self.name} {status}"
    
    def get_routing_info(self):
        """
        Return routing information for call_llm to use.
        """
        if not self.provider:
            raise ValueError(f"Model {self.name} has no provider configured")
        
        if self.provider.provider_type == 'ollama':
            return {
                'type': 'ollama',
                'model': self.model_identifier,
                'base_url': self.provider.base_url
            }
        elif self.provider.provider_type == 'anthropic':
            return {
                'type': 'anthropic',
                'model': self.model_identifier,
                'api_key': self.provider.api_key
            }
        elif self.provider.provider_type == 'openai':
            return {
                'type': 'openai',
                'model': self.model_identifier,
                'api_key': self.provider.api_key
            }
        elif self.provider.provider_type == 'openrouter':
            return {
                'type': 'openrouter',
                'model': self.model_identifier,
                'api_key': self.provider.api_key
            }
        else:
            raise ValueError(f"Unknown provider type: {self.provider.provider_type}")


class DifficultyProfile(models.Model):
    """
    Difficulty curve configuration for CYOA games.
    Stores death probability as a function of game progress.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Name of this difficulty profile (e.g., 'Easy', 'Brutal')"
    )
    description = models.TextField(
        blank=True,
        help_text="Description of this difficulty curve"
    )
    
    # Store the difficulty function as a Python expression
    # Variables available: x (current turn), n (total turns)
    # Returns probability between 0.0 and 1.0
    function = models.TextField(
        help_text="Python expression: returns probability. Variables: x (turn), n (max_turns). Example: '0.05 + 0.35 * (x/n)**2'"
    )
    
    # Optional: store the curve points for UI display (JSON)
    # Format: [0.0, 0.1, 0.2, 0.3, 0.4] for 0%, 25%, 50%, 75%, 100% progress
    curve_points = models.JSONField(
        null=True,
        blank=True,
        help_text="Array of 5 probability values for 0%, 25%, 50%, 75%, 100% progress"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def evaluate(self, current_turn: int, max_turns: int) -> float:
        """
        Evaluate the difficulty function for given turn.
        Returns probability between 0.0 and 1.0.
        """
        try:
            x = current_turn
            n = max_turns
            # Safe eval with only math operations
            result = eval(self.function, {"__builtins__": {}}, {"x": x, "n": n, "min": min, "max": max})
            return float(max(0.0, min(1.0, result)))  # Clamp to [0, 1]
        except Exception as e:
            print(f"[DIFFICULTY] Error evaluating function '{self.function}': {e}")
            return 0.0
    
    @classmethod
    def from_curve_points(cls, points: list) -> str:
        """
        Convert 5 curve points to a piecewise linear function string.
        Points represent probabilities at 0%, 25%, 50%, 75%, 100% progress.
        Returns a Python expression string.
        """
        if len(points) != 5:
            raise ValueError("Must provide exactly 5 curve points")
        
        # Create piecewise linear interpolation
        # For simplicity, we'll use if/else chains
        p0, p1, p2, p3, p4 = points
        
        return f"""(
    {p0} if x == 0 else
    {p0} + ({p1} - {p0}) * (x / (n * 0.25)) if x / n <= 0.25 else
    {p1} + ({p2} - {p1}) * ((x / n - 0.25) / 0.25) if x / n <= 0.50 else
    {p2} + ({p3} - {p2}) * ((x / n - 0.50) / 0.25) if x / n <= 0.75 else
    {p3} + ({p4} - {p3}) * ((x / n - 0.75) / 0.25)
)"""


class GameSession(models.Model):
    """
    Per-session game state for CYOA adventures.
    Tracks progress, turn count, and game over status.
    """
    session_id = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Unique session identifier from OpenWebUI filter"
    )
    
    conversation_fingerprint = models.CharField(
        max_length=32,
        db_index=True,
        null=True,
        blank=True,
        help_text="Hash of first user + first assistant message for lookup when session ID is stripped"
    )
    
    # Link to the configuration used for this session
    configuration = models.ForeignKey(
        'Configuration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Configuration snapshot when session started"
    )
    
    # Game state
    turn_number = models.IntegerField(
        default=0,
        help_text="Current turn number (counts user messages after first assistant response)"
    )
    max_turns = models.IntegerField(
        default=20,
        help_text="Maximum turns for this game"
    )
    game_over = models.BooleanField(
        default=False,
        help_text="Whether this game has ended"
    )
    
    # Last death roll for debugging
    last_death_roll = models.FloatField(
        null=True,
        blank=True,
        help_text="Last random roll for death check (0.0-1.0)"
    )
    last_death_probability = models.FloatField(
        null=True,
        blank=True,
        help_text="Death probability on last turn"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        status = "ENDED" if self.game_over else f"Turn {self.turn_number}/{self.max_turns}"
        return f"Session {self.session_id[:8]}... - {status}"


class ChatConversation(models.Model):
    """
    Represents a chat conversation with UUID and metadata.
    """
    conversation_id = models.CharField(
        max_length=36,
        unique=True,
        db_index=True,
        help_text="UUID for this conversation"
    )
    
    title = models.CharField(
        max_length=255,
        blank=True,
        default="New Conversation",
        help_text="Human-readable title for this conversation"
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata (inventory, game state, etc.)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.title} ({self.conversation_id[:8]}...)"


class ChatMessage(models.Model):
    """
    Individual message within a conversation.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        help_text="The conversation this message belongs to"
    )
    
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        help_text="Who sent this message"
    )
    
    content = models.TextField(
        help_text="The message content"
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata for this message"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]
    
    def __str__(self):
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"{self.role}: {preview}"


class STTRecording(models.Model):
    """
    Store audio recordings for speech-to-text transcription.
    Tracks upload, transcription status, and transcript text.
    """
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('transcribed', 'Transcribed'),
        ('failed', 'Failed'),
        ('deleted', 'Deleted'),
    ]
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the recording"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the recording was uploaded"
    )
    
    file_path = models.CharField(
        max_length=500,
        help_text="Path to the stored audio file relative to MEDIA_ROOT"
    )
    
    mime_type = models.CharField(
        max_length=100,
        default='audio/webm',
        help_text="MIME type of the uploaded audio"
    )
    
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Duration of the recording in seconds"
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='uploaded',
        db_index=True,
        help_text="Current status of the recording"
    )
    
    transcript_text = models.TextField(
        blank=True,
        null=True,
        help_text="Transcribed text from the audio"
    )
    
    error_text = models.TextField(
        blank=True,
        null=True,
        help_text="Error message if transcription failed"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"Recording {self.id} - {self.status}"
