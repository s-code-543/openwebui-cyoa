# External Provider System - Implementation Summary

## ✅ What Was Implemented

I've completely refactored the LLM routing system from name-based logic to a robust database-driven provider management system. This gives you full control over which external models to use without being overwhelmed by hundreds of options.

## 🏗️ Architecture Changes

### Database Models Created

#### 1. **APIProvider Model**
Stores external API provider configurations:
- `name` - Friendly name (e.g., "Office Ollama", "My Anthropic")
- `provider_type` - "ollama" or "anthropic"
- `base_url` - API endpoint URL (for Ollama)
- `api_key` - Authentication key (for Anthropic)
- `is_active` - Enable/disable provider
- `last_tested` - Last successful connection test
- `test_status` - Result of last test

#### 2. **LLMModel Model**
Registers individual models with routing information:
- `name` - Display name for UI
- `model_identifier` - Backend model ID (e.g., "claude-opus-4")
- `source` - "local_ollama" or "external"
- `provider` - FK to APIProvider (if external)
- `is_available` - Enable/disable model
- `capabilities` - JSON metadata
- `get_routing_info()` - Returns routing configuration for call_llm()

### New Python Modules

#### 1. **external_ollama_utils.py**
Functions for external Ollama servers:
- `test_external_ollama_connection()` - Validate connectivity
- `get_external_ollama_models()` - List available models
- `call_external_ollama()` - Execute model calls

#### 2. **external_anthropic_utils.py**
Functions for Anthropic API:
- `test_anthropic_connection()` - Validate API key
- `get_anthropic_models()` - Return known Claude models
- `call_anthropic()` - Execute API calls with proper formatting

### Routing Refactor

#### Old System (Name-Based)
```python
# views.py - BEFORE
if model.startswith("claude"):
    return call_anthropic(...)
elif ":" in model:
    return call_ollama(...)
```

**Problems:**
- Hardcoded patterns
- No control over which models available
- Fragile and error-prone
- Can't mix providers easily

#### New System (Database-Driven)
```python
# views.py - AFTER
llm_model = LLMModel.objects.get(name=model)
routing_info = llm_model.get_routing_info()

if routing_info['type'] == 'local_ollama':
    return call_ollama(...)
elif routing_info['type'] == 'ollama':
    return call_external_ollama(..., routing_info['base_url'])
elif routing_info['type'] == 'anthropic':
    return call_anthropic_api(..., routing_info['api_key'])
```

**Benefits:**
- ✅ Explicit configuration in database
- ✅ Control which models are exposed
- ✅ Easy to add/remove models
- ✅ Mix local and external providers
- ✅ No code changes to add new models

## 📋 Admin Interface (Next Step)

The backend is complete. You still need to create the HTML templates:

### Templates Needed

1. **`cyoa_admin/provider_list.html`**
   - List all API providers
   - Show test status
   - Add/Edit/Delete buttons

2. **`cyoa_admin/provider_editor.html`**
   - Form for provider details (name, type, URL, API key)
   - Test connection button
   - Save/Delete actions

3. **`cyoa_admin/model_list.html`**
   - List all registered models
   - Show source (local/external)
   - Enable/Disable toggle
   - Link to browse more models

4. **`cyoa_admin/browse_models.html`**
   - Show available models from a provider
   - Checkboxes to select models
   - Import selected button

### URL Routes Added

```
/admin/providers/              # List providers
/admin/providers/new/          # Create provider
/admin/providers/<id>/         # Edit provider
/admin/models/                 # List models
/admin/models/browse/<id>/     # Browse provider models
/admin/api/test-provider/      # Test connection (AJAX)
/admin/api/import-models/      # Import models (AJAX)
```

## 🔧 Usage Flow

### 1. Add External Ollama Server

```
1. Go to /admin/providers/new/
2. Fill in:
   - Name: "Office Desktop"
   - Type: Ollama Server
   - Base URL: http://192.168.1.100:11434
3. Click "Test Connection"
4. If successful, click "Save"
5. Go to /admin/models/browse/<provider_id>/
6. Select desired models (e.g., qwen3:70b, llama3.1:405b)
7. Click "Import Selected"
8. Models now available in Configuration dropdown!
```

### 2. Add Anthropic API

```
1. Go to /admin/providers/new/
2. Fill in:
   - Name: "My Anthropic"
   - Type: Anthropic (Claude)
   - API Key: sk-ant-xxxxx
3. Click "Test Connection"
4. If successful, click "Save"
5. Go to /admin/models/browse/<provider_id>/
6. Select desired models:
   - Claude 3.5 Opus
   - Claude 3.5 Sonnet
   - Claude 3.5 Haiku
7. Click "Import Selected"
8. Models now available!
```

### 3. Use in Configuration

```
1. Go to /admin/configurations/edit/
2. Storyteller Model dropdown now shows:
   - 🖥️ Local: qwen3:4b ✓
   - 🖥️ Local: mistral:7b ✓
   - 🌐 Office Desktop: qwen3:70b ✓
   - 🌐 Office Desktop: llama3.1:405b ✓
   - 🌐 My Anthropic: Claude 3.5 Opus ✓
3. Select any model
4. Save configuration
5. views.py automatically routes to correct provider!
```

## 🔄 Migration Path

### Backwards Compatibility

The new `call_llm()` includes legacy fallback:

```python
# Step 1: Try database lookup (NEW)
llm_model = LLMModel.objects.get(name=model)
return route_via_database(llm_model)

# Step 2: Fall back to name-based routing (LEGACY)
if model.startswith("claude"):
    return old_anthropic_routing()
```

This means:
- ✅ Existing configurations keep working
- ✅ Old model names still route correctly
- ⚠️ Warning logged to encourage migration
- 🎯 Eventually remove legacy code once all models in database

### Recommended Migration

1. **Run migration** - ✅ Already done!
2. **Create templates** - Next step
3. **Import local Ollama models** - Register existing models in database
4. **Update configurations** - Switch to database models
5. **Remove legacy code** - Clean up old routing logic

## 📊 Database Schema

```sql
-- API Providers
CREATE TABLE game_apiprovider (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) UNIQUE,
    provider_type VARCHAR(50),  -- 'ollama' or 'anthropic'
    base_url VARCHAR(500),
    api_key VARCHAR(500),
    is_active BOOLEAN,
    last_tested DATETIME,
    test_status VARCHAR(500),
    created_at DATETIME,
    updated_at DATETIME
);

-- LLM Models
CREATE TABLE game_llmmodel (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) UNIQUE,
    model_identifier VARCHAR(200),
    source VARCHAR(50),  -- 'local_ollama' or 'external'
    provider_id INTEGER,  -- FK to apiprovider
    is_available BOOLEAN,
    capabilities JSON,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY (provider_id) REFERENCES game_apiprovider(id)
);
```

## 🎯 Next Steps

### Immediate (Create Templates)

1. Copy existing template structure from config_editor.html
2. Create the 4 new templates listed above
3. Test adding a provider
4. Test importing models
5. Test using external model in configuration

### Short Term (Populate Database)

1. Run management command to import local Ollama models
2. Add your external Ollama server
3. Add Anthropic API if you have a key
4. Import desired models

### Long Term (Cleanup)

1. Once all configs use database models, remove legacy routing
2. Add more provider types (OpenAI, Google, etc.)
3. Add model capabilities/tags for filtering
4. Add cost tracking per model

## 🧪 Testing Checklist

- [ ] Migration applied successfully
- [ ] Can create Ollama provider with URL
- [ ] Test connection works
- [ ] Can browse Ollama models
- [ ] Can import selected models
- [ ] Can create Anthropic provider with API key
- [ ] Can browse Claude models
- [ ] Can import Claude models
- [ ] Models appear in config dropdown
- [ ] Can select external model in config
- [ ] Game uses external model correctly
- [ ] Routing logs show database lookup
- [ ] Legacy models still work (fallback)

## 🚀 Benefits Summary

| Before | After |
|--------|-------|
| Hardcoded routing patterns | Database-driven routing |
| All models auto-discovered | Choose which to expose |
| Name-based guessing | Explicit configuration |
| Local Ollama only | Any external provider |
| Code changes for new models | UI-based management |
| Hundreds of models clutter | Curated model list |
| No connection testing | Test before save |
| Fragile and error-prone | Robust and maintainable |

## 📁 Files Modified

### Backend
- `game/models.py` - Added APIProvider, LLMModel
- `game/views.py` - Refactored call_llm() with database routing
- `game/external_ollama_utils.py` - NEW: External Ollama support
- `game/external_anthropic_utils.py` - NEW: Anthropic API support
- `game/admin_views.py` - Added provider/model management views
- `game/admin_urls.py` - Added new routes
- `game/migrations/0008_apiprovider_llmmodel.py` - NEW: Database schema

### Frontend (TODO)
- `game/templates/cyoa_admin/provider_list.html` - TO CREATE
- `game/templates/cyoa_admin/provider_editor.html` - TO CREATE
- `game/templates/cyoa_admin/model_list.html` - TO CREATE
- `game/templates/cyoa_admin/browse_models.html` - TO CREATE

## 💡 Usage Examples

### Python Shell Examples

```python
# Create an external Ollama provider
from game.models import APIProvider
provider = APIProvider.objects.create(
    name="Office Ollama",
    provider_type="ollama",
    base_url="http://192.168.1.100:11434",
    is_active=True
)

# Register a model
from game.models import LLMModel
model = LLMModel.objects.create(
    name="Office: qwen3:70b",
    model_identifier="qwen3:70b",
    source="external",
    provider=provider,
    is_available=True
)

# Get routing info
routing = model.get_routing_info()
# Returns: {'type': 'ollama', 'model': 'qwen3:70b', 'base_url': 'http://...'}

# Use in configuration
from game.models import Configuration
config = Configuration.objects.first()
config.storyteller_model = "Office: qwen3:70b"  # Model name from database
config.save()

# Now views.py will automatically route to external Ollama!
```

---

**Status:** ✅ Backend complete, templates needed  
**Ready for:** Template creation and testing  
**Backwards compatible:** Yes (legacy fallback included)
