# Configurable Turn Pacing - Architecture Overview

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Story Prompt Files (.txt)                                  │
│  ─────────────────────────────────────────────────────────  │
│  wilderness_prompt.txt                                       │
│  arctic-alien-prompt.txt                                     │
│  haunted-house-prompt.txt                                    │
│                                                              │
│  Contains: "You are narrator for {TOTAL_TURNS}-turn game"   │
│            "Turns 1-{PHASE1_END}: Introduction"              │
│            "Turns {PHASE1_END}-{PHASE2_END}: Build tension"  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ reload_story_prompts command
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Database (Prompt model)                                     │
│  ─────────────────────────────────────────────────────────  │
│  prompt_type: "wilderness-prompt"                            │
│  version: 1                                                  │
│  prompt_text: "...{TOTAL_TURNS}...{PHASE1_END}..."          │
│  is_active: False                                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Referenced by
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Configuration Model                                         │
│  ─────────────────────────────────────────────────────────  │
│  name: "5-Turn Debug Config"                                 │
│  adventure_prompt: → Prompt(wilderness-prompt)               │
│  storyteller_model: "qwen3:4b"                               │
│  judge_model: "claude-haiku-4-5"                             │
│  total_turns: 5                                              │
│  phase1_turns: 1  ← Introduction                             │
│  phase2_turns: 1  ← Victory conditions                       │
│  phase3_turns: 2  ← Progress/twists                          │
│  phase4_turns: 1  ← Finale                                   │
│  is_active: True                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ get_pacing_dict()
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Template Substitution Dictionary                            │
│  ─────────────────────────────────────────────────────────  │
│  {                                                           │
│    'TOTAL_TURNS': 5,                                         │
│    'PHASE1_TURNS': 1,                                        │
│    'PHASE2_TURNS': 1,                                        │
│    'PHASE3_TURNS': 2,                                        │
│    'PHASE4_TURNS': 1,                                        │
│    'PHASE1_END': 1,                                          │
│    'PHASE2_END': 2,                                          │
│    'PHASE3_END': 4,                                          │
│    'PHASE4_END': 5                                           │
│  }                                                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ apply_pacing_template()
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Final System Prompt (sent to LLM)                           │
│  ─────────────────────────────────────────────────────────  │
│  "You are narrator for a 5-turn game"                        │
│  "Turns 1-1: Introduction"                                   │
│  "Turns 1-2: Build tension"                                  │
│  "Turns 2-4: Progress and twists"                            │
│  "Turn 5: Resolution"                                        │
└─────────────────────────────────────────────────────────────┘
```

## Request Flow

```
┌──────────────┐
│ OpenWebUI    │ User starts game
└──────┬───────┘
       │ POST /v1/chat/completions
       ▼
┌─────────────────────────────────────────┐
│ views.py: chat_completions()            │
│ ─────────────────────────────────────── │
│ 1. Get active configuration             │
│ 2. Extract adventure prompt             │
│ 3. apply_pacing_template()              │
│ 4. Call storyteller LLM                 │
│ 5. Call judge LLM                       │
│ 6. Return final response                │
└─────────────────────────────────────────┘
```

## Admin UI Interaction

```
┌──────────────────────────────┐
│ User opens config editor     │
└────────────┬─────────────────┘
             │
             ▼
┌──────────────────────────────────────────────┐
│ config_editor.html                           │
│ ──────────────────────────────────────────── │
│ [Game Length: 5 ▼]                           │
│                                              │
│ Phase 1: [1] turns  ← Auto-populated        │
│ Phase 2: [1] turns  ← on dropdown change    │
│ Phase 3: [2] turns                           │
│ Phase 4: [1] turns                           │
│                                              │
│ Total: 5 turns ← Live calculation           │
│                                              │
│ [Save Configuration]                         │
└────────────┬─────────────────────────────────┘
             │
             │ POST with form data
             ▼
┌──────────────────────────────────────────────┐
│ admin_views.py: config_editor()              │
│ ──────────────────────────────────────────── │
│ 1. Extract form values                       │
│ 2. Validate turn counts                      │
│ 3. Create/update Configuration               │
│ 4. Save to database                          │
└────────────┬─────────────────────────────────┘
             │
             ▼
┌──────────────────────────────┐
│ Configuration saved          │
│ Ready for game use           │
└──────────────────────────────┘
```

## Pacing Defaults

```
5 turns (Quick Test)
├─ Turn 1: Phase 1 (Introduction)
├─ Turn 2: Phase 2 (Victory conditions)
├─ Turn 3: Phase 3 (Progress)
├─ Turn 4: Phase 3 (Progress + twist)
└─ Turn 5: Phase 4 (Finale)

10 turns (Standard)
├─ Turns 1-3: Phase 1 (Introduction)
├─ Turns 4-6: Phase 2 (Victory conditions)
├─ Turns 7-9: Phase 3 (Progress/twists)
└─ Turn 10: Phase 4 (Finale)

15 turns (Extended)
├─ Turns 1-4: Phase 1 (Introduction)
├─ Turns 5-9: Phase 2 (Victory conditions)
├─ Turns 10-13: Phase 3 (Progress/twists)
└─ Turns 14-15: Phase 4 (Finale)

20 turns (Epic)
├─ Turns 1-5: Phase 1 (Introduction)
├─ Turns 6-11: Phase 2 (Victory conditions)
├─ Turns 12-17: Phase 3 (Progress/twists)
└─ Turns 18-20: Phase 4 (Finale)
```

## Key Components

### 1. Configuration Model (models.py)
```python
class Configuration(models.Model):
    total_turns = IntegerField(choices=[(5,'5 turns'),(10,'10 turns')...])
    phase1_turns = IntegerField(default=3)
    phase2_turns = IntegerField(default=3)
    phase3_turns = IntegerField(default=3)
    phase4_turns = IntegerField(default=1)
    
    def get_pacing_dict(self):
        return {
            'TOTAL_TURNS': self.total_turns,
            'PHASE1_END': self.phase1_turns,
            'PHASE2_END': self.phase1_turns + self.phase2_turns,
            ...
        }
```

### 2. Template Substitution (views.py)
```python
def apply_pacing_template(prompt_text, config):
    pacing = config.get_pacing_dict()
    result = prompt_text
    for key, value in pacing.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value))
    return result
```

### 3. Admin Form (admin_views.py)
```python
def config_editor(request, config_id=None):
    if request.method == 'POST':
        total_turns = request.POST.get('total_turns', '10')
        phase1_turns = request.POST.get('phase1_turns', '3')
        phase2_turns = request.POST.get('phase2_turns', '3')
        phase3_turns = request.POST.get('phase3_turns', '3')
        phase4_turns = request.POST.get('phase4_turns', '1')
        # ... create/update configuration
```

### 4. Reload Command (management/commands/)
```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        # Clear existing adventure prompts
        Prompt.objects.exclude(prompt_type='judge').delete()
        
        # Load from .txt files
        for filepath in txt_files:
            prompt_text = open(filepath).read()
            Prompt.objects.create(
                prompt_type=adventure_type,
                prompt_text=prompt_text,
                ...
            )
```

## Benefits Summary

```
┌─────────────────────────────────────────────────────┐
│ BEFORE: Hardcoded 20-turn games                     │
├─────────────────────────────────────────────────────┤
│ ❌ Long testing cycles (20 turns to test changes)    │
│ ❌ Fixed pacing for all players                      │
│ ❌ Manual prompt editing to change turn counts       │
│ ❌ Inconsistencies across prompts                    │
└─────────────────────────────────────────────────────┘
                      ⬇
┌─────────────────────────────────────────────────────┐
│ AFTER: Configurable turn-based pacing               │
├─────────────────────────────────────────────────────┤
│ ✅ Fast 5-turn testing mode                          │
│ ✅ 4 game lengths (5/10/15/20)                       │
│ ✅ Customizable phase distribution                   │
│ ✅ Single configuration point                        │
│ ✅ Automatic template substitution                   │
│ ✅ Consistent behavior across all prompts            │
└─────────────────────────────────────────────────────┘
```

## Database Schema

```sql
-- New fields in Configuration table
ALTER TABLE game_configuration ADD COLUMN total_turns INTEGER DEFAULT 10;
ALTER TABLE game_configuration ADD COLUMN phase1_turns INTEGER DEFAULT 3;
ALTER TABLE game_configuration ADD COLUMN phase2_turns INTEGER DEFAULT 3;
ALTER TABLE game_configuration ADD COLUMN phase3_turns INTEGER DEFAULT 3;
ALTER TABLE game_configuration ADD COLUMN phase4_turns INTEGER DEFAULT 1;

-- Constraints
CHECK (total_turns IN (5, 10, 15, 20))
CHECK (phase1_turns >= 1)
CHECK (phase2_turns >= 1)
CHECK (phase3_turns >= 1)
CHECK (phase4_turns >= 1)
```

## Template Variable Reference

| Variable | Description | Example (5-turn) | Example (10-turn) |
|----------|-------------|------------------|-------------------|
| `{TOTAL_TURNS}` | Total game length | `5` | `10` |
| `{PHASE1_TURNS}` | Phase 1 duration | `1` | `3` |
| `{PHASE2_TURNS}` | Phase 2 duration | `1` | `3` |
| `{PHASE3_TURNS}` | Phase 3 duration | `2` | `3` |
| `{PHASE4_TURNS}` | Phase 4 duration | `1` | `1` |
| `{PHASE1_END}` | Last turn of phase 1 | `1` | `3` |
| `{PHASE2_END}` | Last turn of phase 2 | `2` | `6` |
| `{PHASE3_END}` | Last turn of phase 3 | `4` | `9` |
| `{PHASE4_END}` | Last turn of phase 4 | `5` | `10` |
