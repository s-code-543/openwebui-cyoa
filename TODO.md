# Mac Version TODO List

## Overview
Mac adaptation complete for basic stack. Open Web UI running with native Whisper.cpp STT and Ollama. Next steps: CYOA game server integration, API configuration, and remote access setup.

## Completed ✅
- Native Whisper.cpp STT server with Core ML acceleration
- Native Ollama installation for local LLM testing
- Open Web UI with HTTPS via nginx and self-signed certificates
- Colima-based Docker environment

## Remaining Tasks

### 1. Enable CYOA Game Server
- [ ] Uncomment cyoa-game-server in docker-compose.mac.yml
- [ ] Test Django server starts correctly in Docker
- [ ] Verify Open Web UI can connect to CYOA server
- [ ] Test CYOA models appear in model selection

### 2. Configure API Keys
- [ ] Figure out how to recover/locate existing API keys
- [ ] Set ANTHROPIC_API_KEY in .env file
- [ ] Verify CYOA server can reach Claude API

### 3. Add OpenRouter Support
- [ ] Research OpenRouter API integration
- [ ] Add OpenRouter configuration to CYOA server
- [ ] Test OpenRouter as alternative to direct Anthropic API

### 4. Test Full End-to-End Workflow
- [ ] Test basic chat with Ollama models
- [ ] Test STT (speech-to-text) with Whisper
- [ ] Test CYOA game with Claude via Anthropic API
- [ ] Verify all pirate CYOA context files load correctly

### 5. Remote Access Setup
- [ ] Obtain domain name
- [ ] Set up Cloudflare tunnel for secure remote access
- [ ] Update nginx configuration for proper domain
- [ ] Test remote access from external network
