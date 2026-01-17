"""
Models for CYOA game server.
"""
from django.db import models
from django.utils import timezone
import hashlib


class Prompt(models.Model):
    """
    Store different versions of prompts for the game.
    prompt_type can be 'judge' or any adventure name (e.g., 'arctic-alien', 'haunted-house').
    Each prompt_type has its own independent versioning (v1, v2, v3...).
    """
    
    prompt_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Type of prompt: 'judge' or adventure name (e.g., 'arctic-alien', 'haunted-house')"
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
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this prompt is currently active for API calls"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['prompt_type', 'version']
        ordering = ['prompt_type', '-version']
        indexes = [
            models.Index(fields=['prompt_type', 'is_active']),
        ]
    
    def __str__(self):
        active = " [ACTIVE]" if self.is_active else ""
        return f"{self.prompt_type} v{self.version}{active}"
    
    def save(self, *args, **kwargs):
        # If this prompt is being set as active, deactivate all other prompts of the same type
        if self.is_active:
            Prompt.objects.filter(
                prompt_type=self.prompt_type,
                is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
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
        help_text="Adventure/story prompt to use (any non-judge prompt)"
    )
    storyteller_model = models.CharField(
        max_length=100,
        help_text="Model to use for story generation (e.g., qwen3:4b)"
    )
    storyteller_timeout = models.IntegerField(
        default=30,
        help_text="Timeout in seconds for storyteller generation (default: 30)"
    )
    judge_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_judge',
        limit_choices_to={'prompt_type': 'judge'},
        help_text="Judge prompt to use for validation"
    )
    judge_model = models.CharField(
        max_length=100,
        help_text="Model to use for judge validation (e.g., claude-haiku-4-5)"
    )
    judge_timeout = models.IntegerField(
        default=30,
        help_text="Timeout in seconds for judge validation (default: 30)"
    )
    game_ending_prompt = models.ForeignKey(
        Prompt,
        on_delete=models.PROTECT,
        related_name='configs_as_game_ending',
        limit_choices_to={'prompt_type': 'game-ending'},
        null=True,
        blank=True,
        help_text="Prompt to use when game ends due to death/failure (optional, uses active if not set)"
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
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this configuration is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', '-updated_at']
        indexes = [
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        active = " [ACTIVE]" if self.is_active else ""
        return f"{self.name}{active}"
    
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
    
    def save(self, *args, **kwargs):
        # If this configuration is being set as active, deactivate all others
        if self.is_active:
            Configuration.objects.filter(
                is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class ResponseCache(models.Model):
    """
    Database-backed cache for synchronizing base and moderated responses.
    Replaces in-memory cache for persistence and multi-instance support.
    """
    cache_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Cache key (session_hash-turn_number)"
    )
    response_text = models.TextField(
        help_text="The cached response from the base storyteller"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When this cache entry was created"
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['cache_key', 'created_at']),
        ]
    
    def __str__(self):
        age = (timezone.now() - self.created_at).total_seconds()
        preview = self.response_text[:50] + "..." if len(self.response_text) > 50 else self.response_text
        return f"{self.cache_key} ({age:.1f}s ago) - {preview}"
    
    @classmethod
    def generate_key(cls, messages, system_prompt=None):
        """
        Generate a cache key from messages.
        Uses hash of all message content to ensure unique keys per conversation state.
        """
        # Combine all message content into a single string
        content_parts = []
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            content_parts.append(f"{role}:{content}")
        
        # Include system prompt if provided to differentiate adventures
        if system_prompt:
            content_parts.append(f"system:{system_prompt}")
        
        combined = "|".join(content_parts)
        cache_hash = hashlib.sha256(combined.encode()).hexdigest()[:12]
        return cache_hash
    
    @classmethod
    def set_response(cls, cache_key, response_text):
        """Store or update a cached response."""
        cls.objects.update_or_create(
            cache_key=cache_key,
            defaults={'response_text': response_text}
        )
    
    @classmethod
    def get_response(cls, cache_key, max_age_seconds=60):
        """
        Retrieve a cached response if it exists and isn't too old.
        Returns None if not found or expired.
        """
        try:
            cache_entry = cls.objects.get(cache_key=cache_key)
            age = (timezone.now() - cache_entry.created_at).total_seconds()
            if age > max_age_seconds:
                print(f"[CACHE] Entry {cache_key} expired ({age:.1f}s > {max_age_seconds}s)")
                cache_entry.delete()
                return None
            return cache_entry.response_text
        except cls.DoesNotExist:
            return None
    
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


class APIProvider(models.Model):
    """
    External API provider configurations (external Ollama, Anthropic, etc.)
    """
    PROVIDER_TYPES = [
        ('ollama', 'Ollama Server'),
        ('anthropic', 'Anthropic (Claude)'),
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
    Registered LLM models (local or external) with routing information.
    Replaces name-based routing logic with explicit database configuration.
    """
    MODEL_SOURCES = [
        ('local_ollama', 'Local Ollama'),
        ('external', 'External Provider'),
    ]
    
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Display name for this model (shown in config dropdowns)"
    )
    model_identifier = models.CharField(
        max_length=200,
        help_text="Backend model identifier (e.g., 'qwen3:4b', 'claude-opus-4')"
    )
    source = models.CharField(
        max_length=50,
        choices=MODEL_SOURCES,
        help_text="Where this model is hosted"
    )
    provider = models.ForeignKey(
        APIProvider,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="External provider (if source is 'external')"
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
        ordering = ['source', 'name']
    
    def __str__(self):
        status = "✓" if self.is_available else "✗"
        source_icon = "🖥️" if self.source == 'local_ollama' else "🌐"
        return f"{source_icon} {self.name} {status}"
    
    def get_routing_info(self):
        """
        Return routing information for call_llm to use.
        """
        if self.source == 'local_ollama':
            return {
                'type': 'local_ollama',
                'model': self.model_identifier
            }
        elif self.source == 'external' and self.provider:
            return {
                'type': self.provider.provider_type,
                'model': self.model_identifier,
                'base_url': self.provider.base_url,
                'api_key': self.provider.api_key
            }
        else:
            raise ValueError(f"Cannot determine routing for model {self.name}")


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

