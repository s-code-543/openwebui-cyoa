# Mac Version TODO List

## Overview
Adapting the openwebui-cyoa stack to run on Mac. Key changes: Remove services requiring Nvidia/GPU from Docker. CYOA game server (Django) stays in Docker. Whisper STT and LLMs run natively on Mac for hardware access.

## Tasks

### 1. Remove Ollama service from docker-compose.yml
- [ ] Delete the Ollama container service since Mac LLMs need hardware access outside Docker
- [ ] Remove service definition and any volume/network references

### 2. Remove speeches (Whisper STT) service from docker-compose.yml
- [ ] Remove the speeches service that uses Nvidia container image
- [ ] This needs GPU/hardware access that Docker doesn't provide on Mac

### 3. Set up native Whisper STT server on Mac
- [ ] Install Whisper dependencies locally (likely via Python/pip or Homebrew)
- [ ] Configure Whisper to run as local service
- [ ] Determine best port/endpoint configuration for Open Web UI integration

### 4. Decide on LLM strategy (native Ollama vs 100% API)
- [ ] Test if native Mac Ollama install is viable for development/testing
- [ ] Or go full API (Anthropic/OpenAI) to save credits
- [ ] Document decision

### 5. Create launch script/documentation for Mac setup
- [ ] Document startup sequence: Whisper server, Docker compose (nginx + Open Web UI + CYOA server)
- [ ] Include any Ollama setup if applicable

### 6. Test full stack integration
- [ ] Verify Open Web UI → nginx → CYOA server → LLM backend chain works end-to-end on Mac
- [ ] Test Whisper STT integration with Open Web UI
